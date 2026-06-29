"""Custom programmatic evaluator for real-time agent evaluation.

Runs without LLM calls (zero cost) and assesses tool selection quality.
Content safety is handled by Amazon Bedrock Guardrails, not here.
"""

import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    """Standardized evaluation result from any evaluator.
    
    Attributes:
        score: Float between 0.0 and 1.0
        passed: Whether the evaluation passed
        label: Human-readable label
        reason: Explanation of the score
        judge_model_id: Model that produced the judgment (LLM judges only;
            empty for programmatic evaluators)
        input_tokens: Judge prompt tokens (0 for programmatic evaluators)
        output_tokens: Judge response tokens (0 for programmatic evaluators)
        cost: USD cost of the judge call (0.0 for programmatic evaluators)
    """
    score: float
    passed: bool
    label: str
    reason: str
    judge_model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class ToolSelectionEvaluator:
    """Programmatic evaluator for tool selection quality.
    
    Assesses whether the agent selected appropriate tools and avoided
    unnecessary tool calls based on the user's query.
    """

    # A turn passes if its computed tool-selection quality meets this bar.
    # Quality is computed internally only to derive Pass/Fail; it is not shown.
    PASS_THRESHOLD = 0.5

    def evaluate(
        self,
        user_input: str,
        agent_output: str,
        tools_used: Dict[str, Dict[str, int]],
    ) -> EvalResult:
        """Evaluate tool selection quality.

        Judges only what can be measured reliably from execution: whether the
        tools the agent actually invoked succeeded and were used efficiently.

        It deliberately does NOT guess which tools "should" have been used from
        the wording of the query. Keyword-based intent guessing produces false
        negatives (e.g. expecting current_time just because the word "today"
        appears), penalizing the agent for correctly skipping an unneeded tool.

        Args:
            user_input: The user's message (unused; kept for interface parity)
            agent_output: The agent's response text (unused)
            tools_used: Dict of tool_name -> {call_count, success_count, error_count}

        Returns:
            EvalResult with tool selection assessment
        """
        if not tools_used:
            # No tools were used. Without reliable intent detection we do not
            # second-guess that decision, so it passes.
            return EvalResult(
                score=1.0,
                passed=True,
                label="Pass",
                reason="No tools used",
            )

        used_names = set(tools_used.keys())

        total_calls = sum(t.get("call_count", 0) for t in tools_used.values())
        total_errors = sum(t.get("error_count", 0) for t in tools_used.values())
        error_rate = total_errors / total_calls if total_calls > 0 else 0

        # Quality components for tools that were actually invoked. Take the
        # weakest signal (min), not the average, so a high error rate cannot be
        # masked by otherwise-efficient usage.
        error_score = 1.0 - error_rate
        efficiency_score = min(1.0, 5.0 / total_calls) if total_calls > 5 else 1.0
        quality = min(error_score, efficiency_score)

        reasons = []
        if error_rate > 0:
            reasons.append(f"Tool error rate: {error_rate:.0%}")
        if total_calls > 5:
            reasons.append(f"High tool call count: {total_calls}")
        if not reasons:
            reasons.append(f"Tools used appropriately: {', '.join(used_names)}")

        passed = quality >= self.PASS_THRESHOLD

        return EvalResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            label="Pass" if passed else "Fail",
            reason="; ".join(reasons),
        )
