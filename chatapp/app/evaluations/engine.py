"""Async evaluation engine for real-time agent response assessment.

Runs evaluations as fire-and-forget tasks after each chat response completes.

Design (aligned with evaluation best practices):
- Programmatic checks run on every turn (zero cost): tool_selection.
- LLM-as-judge evaluators are binary pass/fail (not Likert scales) and are
  sampled to control cost: answer_quality and faithfulness.
- faithfulness only runs when the turn used tools/KB, so there is retrieved
  context to ground the response against. Without sources, "faithfulness" is
  not measurable, so it is skipped rather than guessed.
- Safety is intentionally NOT evaluated here; Amazon Bedrock Guardrails covers
  content safety, and the results are tracked separately.
"""

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.evaluations.config import EvalConfig
from app.evaluations.capabilities import AGENT_CAPABILITIES_MANIFEST
from app.evaluations.evaluators import (
    EvalResult,
    ToolSelectionEvaluator,
)
from app.models.evaluation import EvaluationRecord
from app.storage.evaluation import EvaluationStorageService

logger = logging.getLogger(__name__)

# Singleton instance for the programmatic evaluator (stateless, reusable)
_tool_selection_evaluator = ToolSelectionEvaluator()


# Binary rubrics for LLM-as-judge evaluators. Each asks for a single
# yes/no judgment with an explicit pass criterion (not a 0-5 scale).
ANSWER_QUALITY_RUBRIC = """\
Decide whether the assistant's response is a good answer to the user's latest
message.

You are given a description of the assistant's actual capabilities (the tools it
really has). Treat it as ground truth: if the response describes capabilities
that match this list, those statements are ACCURATE and must NOT be penalized as
false or misleading. Only treat capability claims as a problem when they
contradict the listed capabilities or go beyond them.

The user's latest message may be a short follow-up (e.g. "yes", "do it", "the
second one") that only makes sense in light of the conversation so far. When
prior conversation is provided, interpret the latest message in that context;
do NOT penalize the response for addressing the established topic rather than the
literal words of the latest message.

A response PASSES only if ALL of the following hold:
- It addresses what the user actually asked, interpreted in light of the
  conversation so far.
- It is complete enough to be useful (no major missing pieces).
- It is clear and on-topic (no significant irrelevant content).
- It does not misrepresent the assistant's actual capabilities.

Set test_pass to true and score to 1.0 if the response PASSES.
Set test_pass to false and score to 0.0 if it FAILS any criterion.
In reason, briefly state the single most important factor in your decision.\
"""

FAITHFULNESS_RUBRIC = """\
Decide whether the assistant's response is faithful to the provided source \
material (retrieved context and tool results). You are checking for \
hallucination: claims that are not supported by the sources.

A response PASSES only if every factual claim in it is supported by the \
provided sources. Reasonable paraphrasing is fine. If the response adds facts \
that are not in the sources, it FAILS.

Set test_pass to true and score to 1.0 if the response is fully grounded.
Set test_pass to false and score to 0.0 if it contains unsupported claims.
In reason, name the unsupported claim if it fails, or confirm grounding if it passes.\
"""


def _run_binary_judge(
    rubric: str,
    judge_input: str,
    agent_output: str,
    config: EvalConfig,
) -> Optional[EvalResult]:
    """Run a single binary LLM-as-judge evaluation synchronously.

    Runs in a thread pool executor to avoid blocking the event loop.

    Args:
        rubric: Binary pass/fail rubric for the judge
        judge_input: The input shown to the judge (question, plus context for
            faithfulness)
        agent_output: The agent's full response (sent untruncated unless a
            positive config.max_output_length is explicitly set)
        config: Evaluation configuration

    Returns:
        EvalResult with score 1.0/0.0 driven by the judge's pass decision,
        or None if evaluation fails or the SDK is unavailable.
    """
    try:
        from strands import Agent
        from strands_evals.types import EvaluationData
        from strands_evals.types.evaluation import EvaluationOutput
        from strands_evals.evaluators.prompt_templates.case_prompt_template import (
            compose_test_prompt,
        )
        from strands_evals.evaluators.prompt_templates.prompt_templates import (
            judge_output_template,
        )

        # Send the full response by default. Truncating the agent output starves
        # the judge of the very content it must assess, producing false
        # negatives. Only cap when a positive limit is explicitly configured.
        judge_output = (
            agent_output[:config.max_output_length]
            if config.max_output_length and config.max_output_length > 0
            else agent_output
        )

        # Run the judge with the SDK's own prompt composition (identical to
        # OutputEvaluator) but invoke the agent directly so we can capture the
        # judge call's token usage — OutputEvaluator.evaluate() discards it.
        evaluation_case = EvaluationData(input=judge_input, actual_output=judge_output)
        judge_prompt = compose_test_prompt(
            evaluation_case=evaluation_case, rubric=rubric, include_inputs=True
        )
        judge_agent = Agent(
            model=config.judge_model_id,
            system_prompt=judge_output_template,
            callback_handler=None,
        )
        agent_result = judge_agent(judge_prompt, structured_output_model=EvaluationOutput)
        result = agent_result.structured_output
        if result is None:
            return None

        # Capture judge token usage and price it. accumulated_usage is a dict
        # {inputTokens, outputTokens, totalTokens}; missing/zero on failure.
        usage = getattr(agent_result.metrics, "accumulated_usage", None) or {}
        input_tokens = int(usage.get("inputTokens", 0) or 0)
        output_tokens = int(usage.get("outputTokens", 0) or 0)
        cost = _judge_cost(input_tokens, output_tokens, config.judge_model_id)

        passed = bool(result.test_pass)
        return EvalResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            label="Pass" if passed else "Fail",
            reason=(result.reason or "")[:config.max_reason_length],
            judge_model_id=config.judge_model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )

    except ImportError:
        logger.warning("strands-agents-evals not installed, skipping LLM evaluation")
        return None
    except Exception as e:
        logger.error("LLM evaluation failed", extra={"error": str(e)})
        return None


def _judge_cost(input_tokens: int, output_tokens: int, judge_model_id: str) -> float:
    """Price a judge call using the shared CostCalculator / model catalog.

    The CostCalculator resolves fully-qualified Bedrock ids (e.g.
    ``global.anthropic.claude-haiku-4-5-20251001-v1:0``) to the catalog entry
    (``anthropic.claude-haiku-4-5``), so judge pricing comes from the same
    single source of truth (models.json) as agent inference pricing.
    """
    try:
        from app.admin.cost_calculator import CostCalculator
        return CostCalculator().calculate_cost(input_tokens, output_tokens, judge_model_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to compute judge cost: %s", e)
        return 0.0


def _build_grounded_context(context_items: List[str], max_total: int) -> str:
    """Join tool/KB results into one grounding block within a char budget.

    Allocates the budget fairly across results so a few large results (e.g. a
    fetched web page or web-search dump) cannot starve later ones (e.g. a
    weather tool result that happened to run last). Without this, a blind
    `joined[:max_total]` truncation drops the tail, causing faithfulness false
    negatives when the response is grounded in a late tool call.

    Strategy: process shortest results first so small ones are kept whole, and
    redistribute the freed budget to larger results. Output preserves the
    original call order, and truncated results are marked so the judge knows
    the source was cut rather than absent.
    """
    items = [i for i in context_items if i and i.strip()]
    if not items:
        return ""

    # No budget (<= 0) means send all source material in full. The faithfulness
    # judge can only verify grounding against complete tool/KB results, so any
    # truncation here risks false negatives.
    if not max_total or max_total <= 0:
        return "\n\n".join(items)

    budgets = [0] * len(items)
    remaining = max_total
    slots = len(items)
    for idx in sorted(range(len(items)), key=lambda i: len(items[i])):
        share = remaining // slots if slots else 0
        take = min(len(items[idx]), share)
        budgets[idx] = take
        remaining -= take
        slots -= 1

    parts = []
    for i, item in enumerate(items):
        if budgets[i] <= 0:
            continue
        if budgets[i] < len(item):
            parts.append(item[:budgets[i]] + " …[truncated]")
        else:
            parts.append(item)
    return "\n\n".join(parts)


async def run_evaluations(
    user_input: str,
    agent_output: str,
    session_id: str,
    user_id: str,
    model_id: str,
    tool_usage: Optional[Dict[str, Dict[str, int]]] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    context_items: Optional[List[str]] = None,
    conversation_history: Optional[str] = None,
) -> None:
    """Run all enabled evaluations asynchronously and store results.

    Fire-and-forget entry point called from the chat route after the SSE
    stream completes.

    Args:
        user_input: The user's message
        agent_output: The full accumulated agent response text
        session_id: Chat session identifier
        user_id: User identifier
        model_id: Model used for the agent response
        tool_usage: Dict of tool_name -> usage counts
        input_tokens: Input tokens consumed (operational; not evaluated here)
        output_tokens: Output tokens generated (operational; not evaluated here)
        context_items: Retrieved source material as a list of individual
            tool/KB results (one string per tool call), required for
            faithfulness. Passed as a list (not a pre-joined string) so the
            budget can be allocated fairly across results.
        conversation_history: Prior turns of the conversation (a plain-text
            transcript), used so judges can interpret follow-up messages like
            "yes" that only make sense in context. Optional.
    """
    config = EvalConfig.from_env()

    if not config.enabled:
        logger.debug("Evaluations disabled, skipping")
        return

    if not agent_output or not agent_output.strip():
        logger.debug("Empty agent output, skipping evaluations")
        return

    base_timestamp = datetime.now(timezone.utc).isoformat()
    records: List[EvaluationRecord] = []
    loop = asyncio.get_event_loop()

    # --- Programmatic evaluators (fast, in-process, every turn) ---

    if "tool_selection" in config.programmatic_evaluators:
        start = time.monotonic()
        result = _tool_selection_evaluator.evaluate(
            user_input, agent_output, tool_usage or {}
        )
        latency = int((time.monotonic() - start) * 1000)
        records.append(_make_record(
            "tool_selection", result, "programmatic", latency,
            session_id, base_timestamp, user_id, model_id, user_input,
        ))

    # --- LLM-as-judge evaluators (binary, sampled, in thread pool) ---

    run_llm = config.llm_evaluators and random.random() < config.llm_sample_rate
    if config.llm_evaluators and not run_llm:
        logger.debug(
            "LLM judges skipped by sampling",
            extra={"sample_rate": config.llm_sample_rate},
        )

    llm_tasks = []
    if run_llm:
        if "answer_quality" in config.llm_evaluators:
            # Ground the judge with the agent's real capabilities so it does not
            # flag truthful tool/capability claims as hallucinations, and with
            # prior turns so follow-ups like "yes" are interpreted in context.
            history_block = (
                f"Conversation so far (prior turns, for context):\n"
                f"{conversation_history}\n\n"
                if conversation_history else ""
            )
            answer_quality_input = (
                f"Assistant's actual capabilities:\n{AGENT_CAPABILITIES_MANIFEST}\n\n"
                f"{history_block}"
                f"User's latest message:\n{user_input}"
            )
            llm_tasks.append(("answer_quality", loop.run_in_executor(
                None, _run_binary_judge,
                ANSWER_QUALITY_RUBRIC, answer_quality_input, agent_output, config,
            )))

        # Faithfulness only makes sense when there is source material to
        # ground against. Skip it for turns that used no tools/KB.
        grounded_context = _build_grounded_context(
            context_items or [], config.max_context_length
        )
        if "faithfulness" in config.llm_evaluators and grounded_context:
            # Include the capability manifest alongside retrieved context so
            # truthful capability statements are also treated as grounded, plus
            # prior turns so the judge can interpret follow-up messages.
            history_block = (
                f"Conversation so far (prior turns, for context):\n"
                f"{conversation_history}\n\n"
                if conversation_history else ""
            )
            faithfulness_input = (
                f"{history_block}"
                f"User's latest message:\n{user_input}\n\n"
                f"Source material (assistant capabilities, retrieved context, "
                f"and tool results):\n"
                f"{AGENT_CAPABILITIES_MANIFEST}\n\n"
                f"{grounded_context}"
            )
            llm_tasks.append(("faithfulness", loop.run_in_executor(
                None, _run_binary_judge,
                FAITHFULNESS_RUBRIC, faithfulness_input, agent_output, config,
            )))

    if llm_tasks:
        task_names = [name for name, _ in llm_tasks]
        task_futures = [future for _, future in llm_tasks]
        start_times = {name: time.monotonic() for name in task_names}
        results = await asyncio.gather(*task_futures, return_exceptions=True)

        for name, result in zip(task_names, results):
            latency = int((time.monotonic() - start_times[name]) * 1000)
            if isinstance(result, Exception):
                logger.error(
                    "LLM evaluation raised exception",
                    extra={"evaluator": name, "error": str(result)},
                )
                continue
            if result is None:
                continue
            records.append(_make_record(
                name, result, "llm_judge", latency,
                session_id, base_timestamp, user_id, model_id, user_input,
            ))

    # --- Store all results ---

    if records:
        storage = EvaluationStorageService()
        await storage.store_evaluations_batch(records)
        logger.info(
            "Evaluations completed",
            extra={
                "session_id": session_id,
                "count": len(records),
                "evaluators": [r.evaluator_name for r in records],
            },
        )


def _make_record(
    evaluator_name: str,
    result: EvalResult,
    eval_type: str,
    latency_ms: int,
    session_id: str,
    base_timestamp: str,
    user_id: str,
    model_id: str,
    user_input: str = "",
) -> EvaluationRecord:
    """Create an EvaluationRecord from an EvalResult.

    Appends evaluator name to timestamp for sort key uniqueness
    (multiple evaluators run for the same message at the same time).
    """
    unique_timestamp = f"{base_timestamp}#{evaluator_name}"
    return EvaluationRecord(
        session_id=session_id,
        timestamp=unique_timestamp,
        user_id=user_id,
        evaluator_name=evaluator_name,
        score=result.score,
        passed=result.passed,
        label=result.label,
        reason=result.reason,
        eval_type=eval_type,
        latency_ms=latency_ms,
        model_id=model_id,
        user_input=user_input,
        judge_model_id=getattr(result, "judge_model_id", ""),
        input_tokens=getattr(result, "input_tokens", 0),
        output_tokens=getattr(result, "output_tokens", 0),
        cost=getattr(result, "cost", 0.0),
    )
