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

        # Estimate messages evaluated (each message produces N eval records)
        total_evals = len(records)
        num_evaluators = len(scores_by_eval)
        approx_messages = total_evals // max(num_evaluators, 1)
        total_failed = sum(1 for r in records if not r.passed)
        # Sum the cost of the LLM-judge calls (programmatic evaluators are 0).
        total_cost = round(sum(r.cost for r in records), 6)

        return EvaluationAggregateStats(
            total_evaluations=total_evals,
            total_messages_evaluated=approx_messages,
            total_failed=total_failed,
            total_cost=total_cost,
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

    async def get_recent_sessions(
        self,
        start_time: str,
        end_time: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get the most recently evaluated sessions.

        Sessions are ordered by their latest evaluation timestamp (newest
        first). Each entry includes the same pass-rate summary used by the
        sessions table.

        Returns:
            List of dicts with session_id, pass_rate, avg_score, eval_count,
            failed_count, last_activity, and per-evaluator pass rates.
        """
        records = await self.storage.scan_by_time_range(start_time, end_time)

        if not records:
            return []

        session_scores: Dict[str, List[float]] = defaultdict(list)
        session_passes: Dict[str, List[bool]] = defaultdict(list)
        session_evals: Dict[str, Dict[str, List[bool]]] = defaultdict(
            lambda: defaultdict(list)
        )
        session_last_ts: Dict[str, str] = {}

        for record in records:
            sid = record.session_id
            session_scores[sid].append(record.score)
            session_passes[sid].append(record.passed)
            session_evals[sid][record.evaluator_name].append(record.passed)
            base_ts = record.timestamp.split("#")[0]
            if base_ts > session_last_ts.get(sid, ""):
                session_last_ts[sid] = base_ts

        sessions = []
        for sid, passes in session_passes.items():
            pass_rate = sum(1 for p in passes if p) / len(passes)
            failed_count = sum(1 for p in passes if not p)
            scores = session_scores[sid]
            evaluator_pass_rates = {
                name: round(sum(1 for p in p_list if p) / len(p_list), 3)
                for name, p_list in session_evals[sid].items()
            }
            sessions.append({
                "session_id": sid,
                "pass_rate": round(pass_rate, 3),
                "avg_score": round(sum(scores) / len(scores), 3),
                "eval_count": len(passes),
                "failed_count": failed_count,
                "last_activity": session_last_ts[sid],
                "evaluator_scores": evaluator_pass_rates,
            })

        sessions.sort(key=lambda x: x["last_activity"], reverse=True)
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
                    "user_input": record.user_input,
                    "evaluations": [],
                },
            )
            # Backfill the question from whichever record carries it
            if not turn.get("user_input") and record.user_input:
                turn["user_input"] = record.user_input
            turn["evaluations"].append({
                "evaluator_name": record.evaluator_name,
                "eval_type": record.eval_type,
                "score": record.score,
                "passed": record.passed,
                "label": record.label,
                "reason": record.reason,
                "latency_ms": record.latency_ms,
                "judge_model_id": record.judge_model_id,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "cost": record.cost,
            })

        result = []
        for base_ts in sorted(turns.keys()):
            turn = turns[base_ts]
            evals = turn["evaluations"]
            scores = [e["score"] for e in evals]
            turn["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
            turn["all_passed"] = all(e["passed"] for e in evals) if evals else False
            turn["cost"] = round(sum(e.get("cost", 0.0) for e in evals), 6)
            # Stable ordering of evaluators within a turn
            turn["evaluations"] = sorted(evals, key=lambda e: e["evaluator_name"])
            result.append(turn)
        return result
