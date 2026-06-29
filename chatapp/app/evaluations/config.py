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
        llm_evaluators: List of enabled LLM-based evaluator names (binary judges)
        programmatic_evaluators: List of enabled programmatic evaluator names
        llm_sample_rate: Fraction of turns (0.0-1.0) on which to run LLM judges.
            Programmatic evaluators always run. Defaults to 1.0 (every turn);
            lower it to control cost in higher-traffic deployments.
        max_output_length: Max chars of agent output to send to judge. 0 (default)
            means no truncation — send the full response.
        max_context_length: Max chars of retrieved source context to send to the
            faithfulness judge. 0 (default) means no truncation — send the full
            source material so grounding is never cut.
        max_reason_length: Max chars to store for evaluation reasons
    """
    enabled: bool = True
    judge_model_id: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    llm_evaluators: List[str] = field(default_factory=lambda: [
        "answer_quality",
        "faithfulness",
    ])
    programmatic_evaluators: List[str] = field(default_factory=lambda: [
        "tool_selection",
    ])
    llm_sample_rate: float = 1.0
    # 0 (or any non-positive value) means "no truncation" — send the full agent
    # output and full source context to the judge. Truncating either causes
    # faithfulness/quality false negatives because the judge can't see the
    # content the response is actually grounded in. Set a positive limit only if
    # you explicitly need to cap cost.
    max_output_length: int = 0
    max_context_length: int = 0
    max_reason_length: int = 2000

    @classmethod
    def from_env(cls) -> "EvalConfig":
        """Load evaluation config from environment variables."""
        enabled = os.environ.get("EVALUATIONS_ENABLED", "true").lower() in (
            "true", "1", "yes"
        )

        judge_model = os.environ.get(
            "EVALUATIONS_JUDGE_MODEL",
            "global.anthropic.claude-haiku-4-5-20251001-v1:0",
        )

        # Allow disabling specific evaluators via comma-separated list
        disabled_evals = set(
            os.environ.get("EVALUATIONS_DISABLED", "").split(",")
        )
        disabled_evals.discard("")

        default_llm = ["answer_quality", "faithfulness"]
        default_prog = ["tool_selection"]

        llm_evals = [e for e in default_llm if e not in disabled_evals]
        prog_evals = [e for e in default_prog if e not in disabled_evals]

        try:
            sample_rate = float(os.environ.get("EVALUATIONS_LLM_SAMPLE_RATE", "1.0"))
        except ValueError:
            sample_rate = 1.0
        sample_rate = max(0.0, min(1.0, sample_rate))

        # 0 = no truncation (default). Only a positive value imposes a cap.
        try:
            max_context = int(os.environ.get("EVALUATIONS_MAX_CONTEXT_LENGTH", "0"))
        except ValueError:
            max_context = 0

        try:
            max_output = int(os.environ.get("EVALUATIONS_MAX_OUTPUT_LENGTH", "0"))
        except ValueError:
            max_output = 0

        return cls(
            enabled=enabled,
            judge_model_id=judge_model,
            llm_evaluators=llm_evals,
            programmatic_evaluators=prog_evals,
            llm_sample_rate=sample_rate,
            max_context_length=max_context,
            max_output_length=max_output,
        )
