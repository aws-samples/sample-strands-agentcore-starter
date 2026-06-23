"""Usage repository for querying and aggregating usage analytics data.

This module provides the UsageRepository class for querying usage records
from DynamoDB and computing aggregate statistics.
"""

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.usage import (
    UsageRecord,
    AggregateStats,
    ModelStats,
    UserStats,
    ToolAnalytics,
)
from app.admin.cost_calculator import CostCalculator

logger = logging.getLogger(__name__)

# Short-TTL cache for range fetches, shared across admin pages that request
# the same window. Keyed by (table, start-minute, end-minute) so the "live"
# range (end = now) still hits within the same minute.
import time as _time

_RECORDS_CACHE: Dict[tuple, tuple] = {}
_RECORDS_CACHE_TTL_SECONDS = 60


def _range_cache_key(table_name: str, start_time: datetime, end_time: datetime) -> tuple:
    return (
        table_name,
        start_time.replace(second=0, microsecond=0).isoformat(),
        end_time.replace(second=0, microsecond=0).isoformat(),
    )


class UsageRepository:
    """Repository for querying usage analytics data.
    
    This class provides methods for querying and aggregating usage records
    from DynamoDB, including time range filtering, model breakdown,
    user statistics, and tool analytics.
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
        cost_calculator: Optional[CostCalculator] = None,
    ):
        """Initialize the usage repository.
        
        Args:
            table_name: DynamoDB table name (defaults to USAGE_TABLE_NAME env var)
            region: AWS region (defaults to AWS_REGION env var)
            cost_calculator: Optional CostCalculator instance
        """
        self.table_name = table_name or os.environ.get(
            "USAGE_TABLE_NAME", "agentcore-usage-records"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.cost_calculator = cost_calculator or CostCalculator()
        
        # Configure boto3 client with retry settings
        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        self._client = boto3.client("dynamodb", config=boto_config)


    async def get_all_records(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> List[UsageRecord]:
        """Get all usage records within a time range.
        
        Performs a full table scan filtered by timestamp. For large datasets,
        consider using more specific queries.
        
        Args:
            start_time: Start of the time range (inclusive)
            end_time: End of the time range (inclusive)
            
        Returns:
            List of usage records within the time range
        """
        # Serve from the short-TTL cache when possible.
        cache_key = _range_cache_key(self.table_name, start_time, end_time)
        cached = _RECORDS_CACHE.get(cache_key)
        if cached is not None and cached[0] > _time.time():
            return cached[1]

        try:
            loop = asyncio.get_event_loop()
            # Prefer the time-based `date-index` GSI: Query a small set of day
            # partitions for the range instead of scanning the whole table.
            items: List[dict] = []
            try:
                items = await loop.run_in_executor(
                    None,
                    self._query_by_date_range,
                    start_time,
                    end_time,
                )
            except ClientError as gsi_err:
                # The index may not exist yet (e.g. before the CDK stack is
                # redeployed). Degrade gracefully to a scan instead of failing.
                logger.warning(
                    "date-index query failed; falling back to scan",
                    extra={
                        "error_code": gsi_err.response.get("Error", {}).get("Code"),
                    },
                )
                items = []
            # Fall back to a full scan when the index returns nothing, which
            # also covers legacy records written before `date_partition`
            # existed (a no-op extra call when the table is simply empty).
            if not items:
                items = await loop.run_in_executor(
                    None,
                    self._scan_by_time_range,
                    start_time.isoformat(),
                    end_time.isoformat(),
                )
            records = [UsageRecord.from_dynamodb_item(item) for item in items]
            _RECORDS_CACHE[cache_key] = (_time.time() + _RECORDS_CACHE_TTL_SECONDS, records)
            return records
        except ClientError as e:
            logger.error(
                "Failed to scan usage records",
                extra={
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to scan usage records (unexpected error)",
                extra={"error": str(e)},
            )
            return []
    
    def _scan_by_time_range(
        self,
        start_time_iso: str,
        end_time_iso: str,
    ) -> List[dict]:
        """Synchronous helper to scan by time range.
        
        Args:
            start_time_iso: Start time in ISO format
            end_time_iso: End time in ISO format
            
        Returns:
            List of DynamoDB items
        """
        items = []
        paginator = self._client.get_paginator("scan")
        
        for page in paginator.paginate(
            TableName=self.table_name,
            FilterExpression="#ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":start": {"S": start_time_iso},
                ":end": {"S": end_time_iso},
            },
        ):
            items.extend(page.get("Items", []))
        
        return items

    def _query_by_date_range(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> List[dict]:
        """Query the `date-index` GSI for each UTC day in the range.

        Each day partition is queried with a timestamp BETWEEN condition so
        the first/last days are trimmed to the exact range. This replaces a
        full-table Scan with a bounded number of indexed Queries (one per day).

        Args:
            start_time: Start of the range (inclusive)
            end_time: End of the range (inclusive)

        Returns:
            List of DynamoDB items across the day partitions
        """
        from datetime import timedelta

        start_iso = start_time.isoformat()
        end_iso = end_time.isoformat()
        items: List[dict] = []
        paginator = self._client.get_paginator("query")

        cursor = start_time.date()
        end_date = end_time.date()
        # Safety cap mirrors compute_daily_series; avoids pathological ranges.
        for _ in range(367):
            if cursor > end_date:
                break
            day_key = cursor.isoformat()
            for page in paginator.paginate(
                TableName=self.table_name,
                IndexName="date-index",
                KeyConditionExpression="date_partition = :d AND #ts BETWEEN :start AND :end",
                ExpressionAttributeNames={"#ts": "timestamp"},
                ExpressionAttributeValues={
                    ":d": {"S": day_key},
                    ":start": {"S": start_iso},
                    ":end": {"S": end_iso},
                },
            ):
                items.extend(page.get("Items", []))
            cursor += timedelta(days=1)

        return items

    def compute_aggregate_stats(
        self,
        records: List[UsageRecord],
        start_time: datetime,
        end_time: datetime,
    ) -> AggregateStats:
        """Compute aggregate statistics from pre-fetched records.
        
        Args:
            records: List of usage records to aggregate
            start_time: Start of the time range (for projection calculation)
            end_time: End of the time range (for projection calculation)
            
        Returns:
            AggregateStats with totals and projections
        """
        if not records:
            return AggregateStats()
        
        total_input = sum(r.input_tokens for r in records)
        total_output = sum(r.output_tokens for r in records)
        total_tokens = sum(r.total_tokens for r in records)
        total_latency = sum(r.latency_ms for r in records)
        
        unique_users = len(set(r.user_id for r in records))
        unique_sessions = len(set(r.session_id for r in records))
        
        # Calculate total cost
        total_cost = sum(
            self.cost_calculator.calculate_cost(
                r.input_tokens, r.output_tokens, r.model_id
            )
            for r in records
        )
        
        # Calculate days in period for projection
        days_in_period = max(1, (end_time - start_time).days)
        projected_monthly = self.cost_calculator.calculate_monthly_projection(
            total_cost, days_in_period
        )
        
        return AggregateStats(
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tokens=total_tokens,
            total_cost=total_cost,
            invocation_count=len(records),
            unique_users=unique_users,
            unique_sessions=unique_sessions,
            avg_latency_ms=total_latency / len(records) if records else 0.0,
            projected_monthly_cost=projected_monthly,
        )

    async def get_aggregate_stats(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> AggregateStats:
        """Get aggregate statistics for a time period.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            AggregateStats with totals and projections
        """
        records = await self.get_all_records(start_time, end_time)
        return self.compute_aggregate_stats(records, start_time, end_time)

    def compute_daily_series(
        self,
        records: List[UsageRecord],
        start_time: datetime,
        end_time: datetime,
    ) -> List[Dict[str, float]]:
        """Bucket usage records into per-day totals for trend charts.

        Computed from already-fetched records, so this adds no extra
        DynamoDB queries to the page load.

        Args:
            records: Usage records to bucket (already fetched for the range)
            start_time: Start of the range (inclusive)
            end_time: End of the range (inclusive)

        Returns:
            Ordered list of dicts, one per calendar day in the range, each
            with keys: date (YYYY-MM-DD), cost, tokens, invocations.
        """
        from datetime import timedelta

        buckets: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"cost": 0.0, "tokens": 0, "invocations": 0}
        )
        for r in records:
            day = (r.timestamp or "")[:10]
            if not day:
                continue
            bucket = buckets[day]
            bucket["cost"] += self.cost_calculator.calculate_cost(
                r.input_tokens, r.output_tokens, r.model_id
            )
            bucket["tokens"] += r.total_tokens
            bucket["invocations"] += 1

        series: List[Dict[str, float]] = []
        cursor = start_time.date()
        end_date = end_time.date()
        # Safety cap to avoid pathological ranges blowing up the payload
        for _ in range(367):
            if cursor > end_date:
                break
            key = cursor.isoformat()
            bucket = buckets.get(key, {"cost": 0.0, "tokens": 0, "invocations": 0})
            series.append({
                "date": key,
                "cost": round(float(bucket["cost"]), 6),
                "tokens": int(bucket["tokens"]),
                "invocations": int(bucket["invocations"]),
            })
            cursor += timedelta(days=1)

        return series


    def compute_stats_by_model(
        self,
        records: List[UsageRecord],
    ) -> Dict[str, ModelStats]:
        """Compute usage breakdown by model from pre-fetched records.
        
        Args:
            records: List of usage records to aggregate
            
        Returns:
            Dictionary mapping model_id to ModelStats
        """
        model_data: Dict[str, Dict] = defaultdict(lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "invocation_count": 0,
        })
        
        for record in records:
            model_data[record.model_id]["input_tokens"] += record.input_tokens
            model_data[record.model_id]["output_tokens"] += record.output_tokens
            model_data[record.model_id]["total_tokens"] += record.total_tokens
            model_data[record.model_id]["invocation_count"] += 1
        
        result = {}
        for model_id, data in model_data.items():
            cost = self.cost_calculator.calculate_cost(
                data["input_tokens"],
                data["output_tokens"],
                model_id,
            )
            result[model_id] = ModelStats(
                model_id=model_id,
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                total_tokens=data["total_tokens"],
                cost=cost,
                invocation_count=data["invocation_count"],
            )
        
        return result

    async def get_stats_by_model(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, ModelStats]:
        """Get usage breakdown by model.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            Dictionary mapping model_id to ModelStats
        """
        records = await self.get_all_records(start_time, end_time)
        return self.compute_stats_by_model(records)

    def compute_stats_by_user(
        self,
        records: List[UsageRecord],
    ) -> List[UserStats]:
        """Compute per-user usage stats from pre-fetched records.
        
        Args:
            records: List of usage records to aggregate
            
        Returns:
            List of UserStats sorted by total_tokens descending
        """
        user_data: Dict[str, Dict] = defaultdict(lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "sessions": set(),
            "invocation_count": 0,
            "costs": [],
        })
        
        for record in records:
            user_data[record.user_id]["input_tokens"] += record.input_tokens
            user_data[record.user_id]["output_tokens"] += record.output_tokens
            user_data[record.user_id]["total_tokens"] += record.total_tokens
            user_data[record.user_id]["sessions"].add(record.session_id)
            user_data[record.user_id]["invocation_count"] += 1
            
            cost = self.cost_calculator.calculate_cost(
                record.input_tokens, record.output_tokens, record.model_id
            )
            user_data[record.user_id]["costs"].append(cost)
        
        result = []
        for user_id, data in user_data.items():
            result.append(UserStats(
                user_id=user_id,
                total_input_tokens=data["input_tokens"],
                total_output_tokens=data["output_tokens"],
                total_tokens=data["total_tokens"],
                total_cost=sum(data["costs"]),
                session_count=len(data["sessions"]),
                invocation_count=data["invocation_count"],
            ))
        
        # Sort by total_tokens descending
        result.sort(key=lambda x: x.total_tokens, reverse=True)
        
        return result

    async def get_stats_by_user(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> List[UserStats]:
        """Get per-user usage stats, sorted by total tokens descending.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            List of UserStats sorted by total_tokens descending
        """
        records = await self.get_all_records(start_time, end_time)
        return self.compute_stats_by_user(records)


    def compute_tool_analytics(
        self,
        records: List[UsageRecord],
    ) -> List[ToolAnalytics]:
        """Compute tool usage statistics from pre-fetched records.
        
        Args:
            records: List of usage records to aggregate
            
        Returns:
            List of ToolAnalytics for all tools used in the period
        """
        tool_data: Dict[str, Dict] = defaultdict(lambda: {
            "call_count": 0,
            "success_count": 0,
            "error_count": 0,
        })
        
        for record in records:
            for tool_name, usage in record.tool_usage.items():
                tool_data[tool_name]["call_count"] += usage.call_count
                tool_data[tool_name]["success_count"] += usage.success_count
                tool_data[tool_name]["error_count"] += usage.error_count
        
        result = []
        for tool_name, data in tool_data.items():
            call_count = data["call_count"]
            success_rate = (
                data["success_count"] / call_count if call_count > 0 else 0.0
            )
            error_rate = (
                data["error_count"] / call_count if call_count > 0 else 0.0
            )
            
            result.append(ToolAnalytics(
                tool_name=tool_name,
                call_count=call_count,
                success_count=data["success_count"],
                error_count=data["error_count"],
                success_rate=success_rate,
                error_rate=error_rate,
            ))
        
        # Sort by call_count descending
        result.sort(key=lambda x: x.call_count, reverse=True)
        
        return result

    async def get_tool_analytics(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> List[ToolAnalytics]:
        """Get aggregated tool usage statistics.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            List of ToolAnalytics for all tools used in the period
        """
        records = await self.get_all_records(start_time, end_time)
        return self.compute_tool_analytics(records)

    async def search_users(
        self,
        query: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[UserStats]:
        """Search for users by ID prefix/substring.
        
        Args:
            query: Search query (case-insensitive substring match)
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            List of UserStats for matching users, sorted by total_tokens desc
        """
        all_users = await self.get_stats_by_user(start_time, end_time)
        
        # Filter by case-insensitive substring match
        query_lower = query.lower()
        filtered = [
            user for user in all_users
            if query_lower in user.user_id.lower()
        ]
        
        return filtered

    async def get_user_detail(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[UserStats]:
        """Get detailed stats for a specific user.
        
        Args:
            user_id: The user ID to look up
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            UserStats for the user, or None if not found
        """
        all_users = await self.get_stats_by_user(start_time, end_time)
        
        for user in all_users:
            if user.user_id == user_id:
                return user
        
        return None

    async def get_records_by_user(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[UsageRecord]:
        """Get a single user's records via a partition-key Query.

        ``user_id`` is the table partition key and ``timestamp`` the sort key,
        so this is a direct Query rather than a full-table Scan + Python filter.

        Args:
            user_id: The user ID (partition key) to query
            start_time: Start of the time range (inclusive)
            end_time: End of the time range (inclusive)

        Returns:
            List of usage records for the user within the range
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._query_by_user_sync,
                user_id,
                start_time.isoformat(),
                end_time.isoformat(),
            )
            return [UsageRecord.from_dynamodb_item(item) for item in items]
        except ClientError as e:
            logger.error(
                "Failed to query user records",
                extra={
                    "user_id": user_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to query user records (unexpected error)",
                extra={"user_id": user_id, "error": str(e)},
            )
            return []

    def _query_by_user_sync(
        self,
        user_id: str,
        start_time_iso: str,
        end_time_iso: str,
    ) -> List[dict]:
        """Synchronous helper to query the main table by user_id partition key."""
        items = []
        paginator = self._client.get_paginator("query")
        for page in paginator.paginate(
            TableName=self.table_name,
            KeyConditionExpression="user_id = :uid AND #ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":uid": {"S": user_id},
                ":start": {"S": start_time_iso},
                ":end": {"S": end_time_iso},
            },
        ):
            items.extend(page.get("Items", []))
        return items

    async def get_session_records(
        self,
        session_id: str,
    ) -> List[UsageRecord]:
        """Get all usage records for a specific session.
        
        Uses the GSI on session_id for efficient lookups.
        
        Args:
            session_id: The session ID to query
            
        Returns:
            List of usage records for the session
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._query_by_session_sync,
                session_id,
            )
            return [UsageRecord.from_dynamodb_item(item) for item in items]
        except ClientError as e:
            logger.error(
                "Failed to query session records",
                extra={
                    "session_id": session_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to query session records (unexpected error)",
                extra={
                    "session_id": session_id,
                    "error": str(e),
                },
            )
            return []
    
    def _query_by_session_sync(self, session_id: str) -> List[dict]:
        """Synchronous helper to query by session using GSI.
        
        Args:
            session_id: The session ID to query
            
        Returns:
            List of DynamoDB items
        """
        items = []
        paginator = self._client.get_paginator("query")
        
        for page in paginator.paginate(
            TableName=self.table_name,
            IndexName="session-index",
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={
                ":sid": {"S": session_id},
            },
        ):
            items.extend(page.get("Items", []))
        
        return items
