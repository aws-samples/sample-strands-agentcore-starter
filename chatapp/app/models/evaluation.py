"""Evaluation data models for DynamoDB storage.

This module defines dataclasses for storing and querying evaluation results
from Strands Evals SDK. Records are stored in DynamoDB with session_id as
partition key and timestamp as sort key. One record per evaluator per message.
"""

import json
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional


@dataclass
class EvaluationRecord:
    """Record of a single evaluator result for a chat message.
    
    Stored in DynamoDB with session_id as partition key and timestamp as sort key.
    A GSI on user_id + timestamp enables user-based lookups.
    
    Attributes:
        session_id: Partition key - chat session identifier
        timestamp: Sort key - ISO 8601 timestamp (includes evaluator suffix for uniqueness)
        user_id: GSI partition key - user who triggered the evaluation
        evaluator_name: Name of the evaluator (e.g., "helpfulness", "faithfulness")
        score: Evaluation score from 0.0 to 1.0
        passed: Whether the score meets the pass threshold
        label: Human-readable label (e.g., "Very helpful", "Completely Yes")
        reason: Judge explanation or programmatic reason (truncated)
        eval_type: "llm_judge" or "programmatic"
        latency_ms: How long the evaluation took in milliseconds
        model_id: The model that was evaluated (agent model, not judge model)
        judge_model_id: The model that performed the evaluation (LLM judge).
            Empty for programmatic evaluators.
        input_tokens: Judge prompt tokens consumed (0 for programmatic evaluators)
        output_tokens: Judge response tokens generated (0 for programmatic evaluators)
        cost: USD cost of this judge call (0.0 for programmatic evaluators)
    """
    session_id: str
    timestamp: str
    user_id: str
    evaluator_name: str
    score: float
    passed: bool
    label: str
    reason: str
    eval_type: str
    latency_ms: int
    model_id: str
    user_input: str = ""
    judge_model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format."""
        return {
            "session_id": {"S": self.session_id},
            "timestamp": {"S": self.timestamp},
            "user_id": {"S": self.user_id},
            "evaluator_name": {"S": self.evaluator_name},
            "score": {"N": str(self.score)},
            "passed": {"BOOL": self.passed},
            "label": {"S": self.label},
            "reason": {"S": self.reason[:2000]},  # Truncate long reasons
            "eval_type": {"S": self.eval_type},
            "latency_ms": {"N": str(self.latency_ms)},
            "model_id": {"S": self.model_id},
            "user_input": {"S": self.user_input[:1000]},  # Truncate long questions
            "judge_model_id": {"S": self.judge_model_id},
            "input_tokens": {"N": str(self.input_tokens)},
            "output_tokens": {"N": str(self.output_tokens)},
            "cost": {"N": str(self.cost)},
        }

    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "EvaluationRecord":
        """Create instance from DynamoDB item."""
        return cls(
            session_id=item.get("session_id", {}).get("S", ""),
            timestamp=item.get("timestamp", {}).get("S", ""),
            user_id=item.get("user_id", {}).get("S", ""),
            evaluator_name=item.get("evaluator_name", {}).get("S", ""),
            score=float(item.get("score", {}).get("N", "0")),
            passed=item.get("passed", {}).get("BOOL", False),
            label=item.get("label", {}).get("S", ""),
            reason=item.get("reason", {}).get("S", ""),
            eval_type=item.get("eval_type", {}).get("S", ""),
            latency_ms=int(item.get("latency_ms", {}).get("N", "0")),
            model_id=item.get("model_id", {}).get("S", ""),
            user_input=item.get("user_input", {}).get("S", ""),
            judge_model_id=item.get("judge_model_id", {}).get("S", ""),
            input_tokens=int(item.get("input_tokens", {}).get("N", "0")),
            output_tokens=int(item.get("output_tokens", {}).get("N", "0")),
            cost=float(item.get("cost", {}).get("N", "0")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary."""
        return asdict(self)


@dataclass
class EvaluationAggregateStats:
    """Aggregate evaluation statistics for a time period.
    
    Attributes:
        total_evaluations: Total number of evaluation records
        total_messages_evaluated: Approximate number of messages evaluated
        avg_scores: Average score per evaluator name
        pass_rates: Pass rate per evaluator name (0.0 to 1.0)
        eval_counts: Number of evaluations per evaluator name
    """
    total_evaluations: int = 0
    total_messages_evaluated: int = 0
    total_failed: int = 0
    total_cost: float = 0.0
    avg_scores: Dict[str, float] = None
    pass_rates: Dict[str, float] = None
    eval_counts: Dict[str, int] = None

    def __post_init__(self):
        if self.avg_scores is None:
            self.avg_scores = {}
        if self.pass_rates is None:
            self.pass_rates = {}
        if self.eval_counts is None:
            self.eval_counts = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_evaluations": self.total_evaluations,
            "total_messages_evaluated": self.total_messages_evaluated,
            "total_failed": self.total_failed,
            "total_cost": self.total_cost,
            "avg_scores": self.avg_scores,
            "pass_rates": self.pass_rates,
            "eval_counts": self.eval_counts,
        }
