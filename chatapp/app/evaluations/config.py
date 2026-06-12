"""Evaluation configuration.

Controls which evaluators are enabled and their settings.
Can be toggled via environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class EvalConfig:
    """Configuration for the evaluation engine.
    
    Attributes:
        enabled: Global enable/disable switch for all evaluations
        judge_model_id: Bedrock model ID for LLM-as-judge evaluators
        llm_evaluators: List of enabled LLM-based evaluator names
        programmatic_evaluators: List of enabled programmatic evaluator names
        max_output_length: Max chars of agent output to send to judge (cost control)
        max_reason_length: Max chars to store for evaluation reasons
    """
    enabled: bool = True
    judge_model_id: str = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
    llm_evaluators: List[str] = field(default_factory=lambda: [
        "helpfulness",
        "faithfulness",
        "relevance",
        "completeness",
    ])
    programmatic_evaluators: List[str] = field(default_factory=lambda: [
        "safety",
        "tool_selection",
        "response_efficiency",
    ])
    max_output_length: int = 4000
    max_reason_length: int = 2000

    @classmethod
    def from_env(cls) -> "EvalConfig":
        """Load evaluation config from environment variables."""
        enabled = os.environ.get("EVALUATIONS_ENABLED", "true").lower() in (
            "true", "1", "yes"
        )

        judge_model = os.environ.get(
            "EVALUATIONS_JUDGE_MODEL",
            "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        )

        # Allow disabling specific evaluators via comma-separated list
        disabled_evals = set(
            os.environ.get("EVALUATIONS_DISABLED", "").split(",")
        )
        disabled_evals.discard("")

        default_llm = ["helpfulness", "faithfulness", "relevance", "completeness"]
        default_prog = ["safety", "tool_selection", "response_efficiency"]

        llm_evals = [e for e in default_llm if e not in disabled_evals]
        prog_evals = [e for e in default_prog if e not in disabled_evals]

        return cls(
            enabled=enabled,
            judge_model_id=judge_model,
            llm_evaluators=llm_evals,
            programmatic_evaluators=prog_evals,
        )
