"""Async evaluation engine for real-time agent response assessment.

Runs evaluations as fire-and-forget tasks after each chat response completes.
Uses Strands Evals SDK for LLM-as-judge evaluators and custom programmatic
evaluators for zero-cost checks.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.evaluations.config import EvalConfig
from app.evaluations.evaluators import (
    EvalResult,
    SafetyEvaluator,
    ToolSelectionEvaluator,
    ResponseEfficiencyEvaluator,
)
from app.models.evaluation import EvaluationRecord
from app.storage.evaluation import EvaluationStorageService

logger = logging.getLogger(__name__)

# Singleton instances for programmatic evaluators (stateless, reusable)
_safety_evaluator = SafetyEvaluator()
_tool_selection_evaluator = ToolSelectionEvaluator()
_efficiency_evaluator = ResponseEfficiencyEvaluator()


# Custom rubrics for OutputEvaluator-based LLM judges
RELEVANCE_RUBRIC = """\
Evaluate whether the assistant's response directly addresses the user's question or request.

Score 1.0 if the response is highly relevant and directly answers what was asked.
Score 0.75 if the response is mostly relevant with minor tangents.
Score 0.5 if the response is partially relevant but misses key aspects.
Score 0.25 if the response is mostly off-topic.
Score 0.0 if the response does not address the question at all.\
"""

COMPLETENESS_RUBRIC = """\
Evaluate whether the assistant's response fully and completely answers the user's question.

Score 1.0 if the response is thorough and covers all aspects of the question.
Score 0.75 if the response covers most aspects but misses minor details.
Score 0.5 if the response covers some aspects but has notable gaps.
Score 0.25 if the response is superficial and missing major aspects.
Score 0.0 if the response fails to meaningfully answer the question.\
"""


def _run_llm_evaluation(
    evaluator_name: str,
    user_input: str,
    agent_output: str,
    config: EvalConfig,
) -> Optional[EvalResult]:
    """Run a single LLM-as-judge evaluation synchronously.
    
    This runs in a thread pool executor to avoid blocking the event loop.
    
    Args:
        evaluator_name: Name of the evaluator to run
        user_input: The user's message
        agent_output: The agent's response (truncated)
        config: Evaluation configuration
        
    Returns:
        EvalResult or None if evaluation fails
    """
    try:
        from strands_evals.evaluators import OutputEvaluator

        # Truncate output for cost control
        truncated_output = agent_output[:config.max_output_length]

        if evaluator_name == "relevance":
            evaluator = OutputEvaluator(
                rubric=RELEVANCE_RUBRIC,
                include_inputs=True,
                model=config.judge_model_id,
            )
        elif evaluator_name == "completeness":
            evaluator = OutputEvaluator(
                rubric=COMPLETENESS_RUBRIC,
                include_inputs=True,
                model=config.judge_model_id,
            )
        else:
            logger.warning(f"Unknown LLM evaluator: {evaluator_name}")
            return None

        # Build evaluation data
        from strands_evals.types import EvaluationData
        eval_data = EvaluationData(
            input=user_input,
            actual_output=truncated_output,
        )

        result = evaluator.evaluate(eval_data)

        if isinstance(result, list):
            result = result[0] if result else None
        if result is None:
            return None

        return EvalResult(
            score=result.score if result.score is not None else 0.0,
            passed=result.test_pass if result.test_pass is not None else False,
            label=result.label or "",
            reason=(result.reason or "")[:config.max_reason_length],
        )

    except ImportError:
        logger.warning(
            "strands-agents-evals not installed, skipping LLM evaluation",
            extra={"evaluator": evaluator_name},
        )
        return None
    except Exception as e:
        logger.error(
            "LLM evaluation failed",
            extra={"evaluator": evaluator_name, "error": str(e)},
        )
        return None


def _run_helpfulness_evaluation(
    user_input: str,
    agent_output: str,
    config: EvalConfig,
) -> Optional[EvalResult]:
    """Run the HelpfulnessEvaluator (trace-level, simplified for online use)."""
    try:
        # For online evaluation without full trace data, we use OutputEvaluator
        # with a helpfulness-focused rubric as a practical approximation
        from strands_evals.evaluators import OutputEvaluator
        from strands_evals.types import EvaluationData

        rubric = """\
Evaluate the helpfulness of the assistant's response from the user's perspective.

Score 1.0 (Above and beyond): Exceptional value, anticipates needs, comprehensive.
Score 0.833 (Very helpful): Highly useful, well-crafted, addresses query thoroughly.
Score 0.667 (Somewhat helpful): Useful and addresses the query adequately.
Score 0.5 (Neutral): Adequate but not particularly helpful.
Score 0.333 (Somewhat unhelpful): Has issues that limit helpfulness.
Score 0.167 (Very unhelpful): Minimal or misleading value.
Score 0.0 (Not helpful at all): Completely unhelpful or counterproductive.\
"""
        evaluator = OutputEvaluator(
            rubric=rubric,
            include_inputs=True,
            model=config.judge_model_id,
        )

        truncated_output = agent_output[:config.max_output_length]
        eval_data = EvaluationData(
            input=user_input,
            actual_output=truncated_output,
        )

        result = evaluator.evaluate(eval_data)
        if isinstance(result, list):
            result = result[0] if result else None
        if result is None:
            return None
        return EvalResult(
            score=result.score if result.score is not None else 0.0,
            passed=result.test_pass if result.test_pass is not None else False,
            label=result.label or "",
            reason=(result.reason or "")[:config.max_reason_length],
        )

    except ImportError:
        logger.warning("strands-agents-evals not installed, skipping helpfulness")
        return None
    except Exception as e:
        logger.error("Helpfulness evaluation failed", extra={"error": str(e)})
        return None


def _run_faithfulness_evaluation(
    user_input: str,
    agent_output: str,
    config: EvalConfig,
) -> Optional[EvalResult]:
    """Run faithfulness evaluation (simplified for online use without traces)."""
    try:
        from strands_evals.evaluators import OutputEvaluator
        from strands_evals.types import EvaluationData

        rubric = """\
Evaluate whether the assistant's response is grounded and faithful to what was asked.
Check for hallucinations, fabricated information, or unsupported claims.

Score 1.0 (Completely faithful): All statements are grounded and accurate.
Score 0.75 (Generally faithful): Mostly grounded with minor unsupported details.
Score 0.5 (Mixed): Some faithful and some potentially fabricated elements.
Score 0.25 (Generally unfaithful): Mostly contains unsupported claims.
Score 0.0 (Not faithful): Significant fabrications or hallucinations.\
"""
        evaluator = OutputEvaluator(
            rubric=rubric,
            include_inputs=True,
            model=config.judge_model_id,
        )

        truncated_output = agent_output[:config.max_output_length]
        eval_data = EvaluationData(
            input=user_input,
            actual_output=truncated_output,
        )

        result = evaluator.evaluate(eval_data)
        if isinstance(result, list):
            result = result[0] if result else None
        if result is None:
            return None
        return EvalResult(
            score=result.score if result.score is not None else 0.0,
            passed=result.test_pass if result.test_pass is not None else False,
            label=result.label or "",
            reason=(result.reason or "")[:config.max_reason_length],
        )

    except ImportError:
        logger.warning("strands-agents-evals not installed, skipping faithfulness")
        return None
    except Exception as e:
        logger.error("Faithfulness evaluation failed", extra={"error": str(e)})
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
) -> None:
    """Run all enabled evaluations asynchronously and store results.
    
    This is the main entry point called as a fire-and-forget task from
    the chat route after the SSE stream completes.
    
    Args:
        user_input: The user's message
        agent_output: The full accumulated agent response text
        session_id: Chat session identifier
        user_id: User identifier
        model_id: Model used for the agent response
        tool_usage: Dict of tool_name -> usage counts
        input_tokens: Input tokens consumed
        output_tokens: Output tokens generated
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

    # --- Run programmatic evaluators (fast, in-process) ---

    if "safety" in config.programmatic_evaluators:
        start = time.monotonic()
        result = _safety_evaluator.evaluate(user_input, agent_output)
        latency = int((time.monotonic() - start) * 1000)
        records.append(_make_record(
            "safety", result, "programmatic", latency,
            session_id, base_timestamp, user_id, model_id,
        ))

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

    if "response_efficiency" in config.programmatic_evaluators:
        start = time.monotonic()
        result = _efficiency_evaluator.evaluate(
            user_input, agent_output, input_tokens, output_tokens
        )
        latency = int((time.monotonic() - start) * 1000)
        records.append(_make_record(
            "response_efficiency", result, "programmatic", latency,
            session_id, base_timestamp, user_id, model_id,
        ))

    # --- Run LLM-as-judge evaluators (slower, in thread pool) ---

    llm_tasks = []

    if "helpfulness" in config.llm_evaluators:
        llm_tasks.append(("helpfulness", loop.run_in_executor(
            None, _run_helpfulness_evaluation, user_input, agent_output, config
        )))

    if "faithfulness" in config.llm_evaluators:
        llm_tasks.append(("faithfulness", loop.run_in_executor(
            None, _run_faithfulness_evaluation, user_input, agent_output, config
        )))

    if "relevance" in config.llm_evaluators:
        llm_tasks.append(("relevance", loop.run_in_executor(
            None, _run_llm_evaluation, "relevance", user_input, agent_output, config
        )))

    if "completeness" in config.llm_evaluators:
        llm_tasks.append(("completeness", loop.run_in_executor(
            None, _run_llm_evaluation, "completeness", user_input, agent_output, config
        )))

    # Await all LLM evaluations concurrently
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
    # Make timestamp unique per evaluator by appending suffix
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
