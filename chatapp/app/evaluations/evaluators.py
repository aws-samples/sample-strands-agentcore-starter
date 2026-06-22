"""Custom programmatic evaluator for real-time agent evaluation.

Runs without LLM calls (zero cost) and assesses tool selection quality.
Content safety is handled by Amazon Bedrock Guardrails, not here.
"""

import logging
import re
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
    """
    score: float
    passed: bool
    label: str
    reason: str


class ToolSelectionEvaluator:
    """Programmatic evaluator for tool selection quality.
    
    Assesses whether the agent selected appropriate tools and avoided
    unnecessary tool calls based on the user's query.
    """

    # Keywords that suggest specific tools should be used
    TOOL_HINTS = {
        "calculator": [
            r'\b(?:calculate|compute|math|sum|add|subtract|multiply|divide|percentage|%)\b',
            r'\b\d+\s*[\+\-\*\/\%]\s*\d+\b',
        ],
        "current_time": [
            r'\b(?:time|date|today|now|clock|day of week)\b',
        ],
        "get_current_weather": [
            r'\b(?:weather|temperature|forecast|rain|snow|sunny|cloudy)\b',
        ],
        "ddg_web_search": [
            r'\b(?:search|look up|find|google|latest|recent|news)\b',
        ],
        "search_knowledge_base": [
            r'\b(?:knowledge base|documentation|docs|internal|curated)\b',
        ],
        "fetch_url_content": [
            r'\b(?:url|link|website|webpage|http|https)\b',
        ],
    }

    def evaluate(
        self,
        user_input: str,
        agent_output: str,
        tools_used: Dict[str, Dict[str, int]],
    ) -> EvalResult:
        """Evaluate tool selection quality.
        
        Args:
            user_input: The user's message
            agent_output: The agent's response text
            tools_used: Dict of tool_name -> {call_count, success_count, error_count}
            
        Returns:
            EvalResult with tool selection assessment
        """
        if not tools_used:
            # No tools used - check if tools should have been used
            expected = self._get_expected_tools(user_input)
            if expected:
                return EvalResult(
                    score=0.5,
                    passed=True,
                    label="Possibly missed tools",
                    reason=f"No tools used, but query may have benefited from: {', '.join(expected)}",
                )
            return EvalResult(
                score=1.0,
                passed=True,
                label="Appropriate (no tools needed)",
                reason="No tools used and none appeared necessary",
            )

        used_names = set(tools_used.keys())
        expected = set(self._get_expected_tools(user_input))

        # Calculate metrics
        total_calls = sum(t.get("call_count", 0) for t in tools_used.values())
        total_errors = sum(t.get("error_count", 0) for t in tools_used.values())
        error_rate = total_errors / total_calls if total_calls > 0 else 0

        # Score components
        scores = []

        # 1. Were expected tools used?
        if expected:
            overlap = used_names & expected
            expected_score = len(overlap) / len(expected) if expected else 1.0
            scores.append(expected_score)

        # 2. Error rate penalty
        error_score = 1.0 - error_rate
        scores.append(error_score)

        # 3. Efficiency - penalize excessive tool calls (>5 is suspicious)
        efficiency_score = min(1.0, 5.0 / total_calls) if total_calls > 5 else 1.0
        scores.append(efficiency_score)

        avg_score = sum(scores) / len(scores) if scores else 1.0

        reasons = []
        if expected and not (used_names & expected):
            reasons.append(f"Expected tools not used: {', '.join(expected - used_names)}")
        if error_rate > 0:
            reasons.append(f"Tool error rate: {error_rate:.0%}")
        if total_calls > 5:
            reasons.append(f"High tool call count: {total_calls}")
        if not reasons:
            reasons.append(f"Tools used appropriately: {', '.join(used_names)}")

        label = "Good" if avg_score >= 0.7 else ("Fair" if avg_score >= 0.4 else "Poor")

        return EvalResult(
            score=round(avg_score, 3),
            passed=avg_score >= 0.5,
            label=label,
            reason="; ".join(reasons),
        )

    def _get_expected_tools(self, user_input: str) -> List[str]:
        """Determine which tools the query likely needs."""
        expected = []
        input_lower = user_input.lower()
        for tool_name, patterns in self.TOOL_HINTS.items():
            for pattern in patterns:
                if re.search(pattern, input_lower):
                    expected.append(tool_name)
                    break
        return expected
