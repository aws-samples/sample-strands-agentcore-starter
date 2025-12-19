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
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._scan_by_time_range,
                start_time.isoformat(),
                end_time.isoformat(),
            )
            return [UsageRecord.from_dynamodb_item(item) for item in items]
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
