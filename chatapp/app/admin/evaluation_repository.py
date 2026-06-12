"""Evaluation repository for admin dashboard queries.

Provides aggregation and query methods for evaluation records
to power the admin evaluations dashboard.
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.models.evaluation import EvaluationRecord, EvaluationAggregateStats
from app.storage.evaluation import EvaluationStorageService

logger = logging.getLogger(__name__)


class EvaluationRepository:
    """Repository for querying and aggregating evaluation data."""

    def __init__(self):
        self.storage = EvaluationStorageService()

    async def get_aggregate_stats(
        self,
        start_time: str,
        end_time: str,
    ) -> EvaluationAggregateStats:
        """Get aggregate evaluation statistics for a time range.
        
        Args:
            start_time: ISO 8601 start time
            end_time: ISO 8601 end time
            
        Returns:
            EvaluationAggregateStats with averages and pass rates
        """
        records = await self.storage.scan_by_time_range(start_time, end_time)

        if not records:
            return EvaluationAggregateStats()

        # Aggregate by evaluator name
        scores_by_eval: Dict[str, List[float]] = defaultdict(list)
        passes_by_eval: Dict[str, List[bool]] = defaultdict(list)
        sessions_seen = set()

        for record in records:
            scores_by_eval[record.evaluator_name].append(record.score)
            passes_by_eval[record.evaluator_name].append(record.passed)
            sessions_seen.add(record.session_id)

        avg_scores = {
            name: round(sum(scores) / len(scores), 3)
            for name, scores in scores_by_eval.items()
        }

        pass_rates = {
            name: round(sum(1 for p in passes if p) / len(passes), 3)
            for name, passes in passes_by_eval.items()
        }

        eval_counts = {
            name: len(scores) for name, scores in scores_by_eval.items()
        }

        # Estimate messages evaluated (each message produces ~7 eval records)
        total_evals = len(records)
        num_evaluators = len(scores_by_eval)
        approx_messages = total_evals // max(num_evaluators, 1)

        return EvaluationAggregateStats(
            total_evaluations=total_evals,
            total_messages_evaluated=approx_messages,
            avg_scores=avg_scores,
            pass_rates=pass_rates,
            eval_counts=eval_counts,
        )

    async def get_daily_trends(
        self,
        start_time: str,
        end_time: str,
    ) -> Dict[str, Dict[str, float]]:
        """Get daily average scores per evaluator for trend charts.
        
        Returns:
            Dict of date_str -> {evaluator_name: avg_score}
        """
        records = await self.storage.scan_by_time_range(start_time, end_time)

        if not records:
            return {}

        # Group by date and evaluator
        daily_scores: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for record in records:
            # Extract date from timestamp (before the # separator)
            ts = record.timestamp.split("#")[0]
            try:
                date_str = ts[:10]  # YYYY-MM-DD
            except (ValueError, IndexError):
                continue
            daily_scores[date_str][record.evaluator_name].append(record.score)

        # Calculate daily averages
        result = {}
        for date_str in sorted(daily_scores.keys()):
            result[date_str] = {
                name: round(sum(scores) / len(scores), 3)
                for name, scores in daily_scores[date_str].items()
            }

        return result

    async def get_worst_sessions(
        self,
        start_time: str,
        end_time: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get sessions with the lowest average evaluation scores.
        
        Returns:
            List of dicts with session_id, avg_score, eval_count, evaluator_scores
        """
        records = await self.storage.scan_by_time_range(start_time, end_time)

        if not records:
            return []

        # Group by session
        session_scores: Dict[str, List[float]] = defaultdict(list)
        session_evals: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for record in records:
            session_scores[record.session_id].append(record.score)
            session_evals[record.session_id][record.evaluator_name].append(
                record.score
            )

        # Calculate session averages and sort
        sessions = []
        for sid, scores in session_scores.items():
            avg = sum(scores) / len(scores)
            eval_avgs = {
                name: round(sum(s) / len(s), 3)
                for name, s in session_evals[sid].items()
            }
            sessions.append({
                "session_id": sid,
                "avg_score": round(avg, 3),
                "eval_count": len(scores),
                "evaluator_scores": eval_avgs,
            })

        sessions.sort(key=lambda x: x["avg_score"])
        return sessions[:limit]

    async def get_session_evaluations(
        self,
        session_id: str,
    ) -> List[EvaluationRecord]:
        """Get all evaluation records for a specific session."""
        return await self.storage.query_by_session(session_id)

    async def get_session_turns(
        self,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """Get a session's evaluations grouped into conversation turns.

        Each evaluator stores one record per turn, all sharing the same base
        timestamp (the sort key is ``<timestamp>#<evaluator_name>``). This
        groups those records back into turns for the per-turn admin view.

        Returns:
            List of turn dicts ordered chronologically, each containing:
            - timestamp: ISO 8601 base timestamp of the turn
            - model_id: model used for the turn (from the records)
            - avg_score: mean score across the turn's evaluators
            - all_passed: True if every evaluator passed
            - evaluations: list of per-evaluator dicts
              (evaluator_name, eval_type, score, passed, label, reason, latency_ms)
        """
        records = await self.storage.query_by_session(session_id)
        if not records:
            return []

        turns: Dict[str, Dict[str, Any]] = {}
        for record in records:
            base_ts = record.timestamp.split("#")[0]
            turn = turns.setdefault(
                base_ts,
                {
                    "timestamp": base_ts,
                    "model_id": record.model_id,
                    "evaluations": [],
                },
            )
            turn["evaluations"].append({
                "evaluator_name": record.evaluator_name,
                "eval_type": record.eval_type,
                "score": record.score,
                "passed": record.passed,
                "label": record.label,
                "reason": record.reason,
                "latency_ms": record.latency_ms,
            })

        result = []
        for base_ts in sorted(turns.keys()):
            turn = turns[base_ts]
            evals = turn["evaluations"]
            scores = [e["score"] for e in evals]
            turn["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
            turn["all_passed"] = all(e["passed"] for e in evals) if evals else False
            # Stable ordering of evaluators within a turn
            turn["evaluations"] = sorted(evals, key=lambda e: e["evaluator_name"])
            result.append(turn)
        return result

    async def get_score_distribution(
        self,
        start_time: str,
        end_time: str,
    ) -> Dict[str, Dict[str, int]]:
        """Get score distribution per evaluator for histogram charts.
        
        Returns:
            Dict of evaluator_name -> {bucket_label: count}
            Buckets: "0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"
        """
        records = await self.storage.scan_by_time_range(start_time, end_time)

        if not records:
            return {}

        buckets = ["0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"]
        distribution: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {b: 0 for b in buckets}
        )

        for record in records:
            score = record.score
            if score < 0.2:
                bucket = "0-0.2"
            elif score < 0.4:
                bucket = "0.2-0.4"
            elif score < 0.6:
                bucket = "0.4-0.6"
            elif score < 0.8:
                bucket = "0.6-0.8"
            else:
                bucket = "0.8-1.0"
            distribution[record.evaluator_name][bucket] += 1

        return dict(distribution)
