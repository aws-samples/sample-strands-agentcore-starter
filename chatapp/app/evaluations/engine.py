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
Decide whether the assistant's response is a good answer to the user's question.

A response PASSES only if ALL of the following hold:
- It directly addresses what the user actually asked.
- It is complete enough to be useful (no major missing pieces).
- It is clear and on-topic (no significant irrelevant content).

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
        agent_output: The agent's response (truncated for cost control)
        config: Evaluation configuration

    Returns:
        EvalResult with score 1.0/0.0 driven by the judge's pass decision,
        or None if evaluation fails or the SDK is unavailable.
    """
    try:
        from strands_evals.evaluators import OutputEvaluator
        from strands_evals.types import EvaluationData

        truncated_output = agent_output[:config.max_output_length]

        evaluator = OutputEvaluator(
            rubric=rubric,
            include_inputs=True,
            model=config.judge_model_id,
        )
        result = evaluator.evaluate(EvaluationData(
            input=judge_input,
            actual_output=truncated_output,
        ))

        if isinstance(result, list):
            result = result[0] if result else None
        if result is None:
            return None

        passed = bool(result.test_pass)
        return EvalResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            label="Pass" if passed else "Fail",
            reason=(result.reason or "")[:config.max_reason_length],
        )

    except ImportError:
        logger.warning("strands-agents-evals not installed, skipping LLM evaluation")
        return None
    except Exception as e:
        logger.error("LLM evaluation failed", extra={"error": str(e)})
        return None


async def run_evaluations(
    user_input: str,
    agent_output: str,
    session_id: str,
    user_id: str,
    model_id: str,
    tool_usage: Optional[Dict[str, Dict[str, int]]] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    context: Optional[str] = None,
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
        context: Retrieved source material (tool/KB results) used in the turn,
            required for faithfulness evaluation
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
            session_id, base_timestamp, user_id, model_id,
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
            llm_tasks.append(("answer_quality", loop.run_in_executor(
                None, _run_binary_judge,
                ANSWER_QUALITY_RUBRIC, user_input, agent_output, config,
            )))

        # Faithfulness only makes sense when there is source material to
        # ground against. Skip it for turns that used no tools/KB.
        if "faithfulness" in config.llm_evaluators and context and context.strip():
            faithfulness_input = (
                f"User question:\n{user_input}\n\n"
                f"Source material (retrieved context and tool results):\n"
                f"{context[:config.max_output_length]}"
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
                session_id, base_timestamp, user_id, model_id,
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
    )
