"""Guardrail repository for querying and aggregating guardrail analytics data.

This module provides the GuardrailRepository class for querying guardrail violation
records from DynamoDB and computing aggregate statistics for admin views.
"""

import asyncio
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.guardrail import GuardrailRecord

logger = logging.getLogger(__name__)


@dataclass
class GuardrailAggregateStats:
    """Aggregate statistics for guardrail evaluations.
    
    Attributes:
        total_evaluations: Total number of guardrail evaluations
        violation_count: Number of evaluations that triggered violations
        violation_rate: Ratio of violations to total evaluations
        input_violations: Number of violations from user input
        output_violations: Number of violations from assistant output
        policy_breakdown: Count of violations by policy type
        filter_breakdown: Count of violations by specific filter type (e.g., content:INSULTS)
        unique_users: Number of unique users with violations
        unique_sessions: Number of unique sessions with violations
        top_filter: The most common filter type (e.g., "INSULTS")
        top_filter_count: Count of the most common filter type
    """
    total_evaluations: int = 0
    violation_count: int = 0
    violation_rate: float = 0.0
    input_violations: int = 0
    output_violations: int = 0
    policy_breakdown: Dict[str, int] = None
    filter_breakdown: Dict[str, int] = None
    unique_users: int = 0
    unique_sessions: int = 0
    top_filter: str = ""
    top_filter_count: int = 0
    
    def __post_init__(self):
        if self.policy_breakdown is None:
            self.policy_breakdown = {}
        if self.filter_breakdown is None:
            self.filter_breakdown = {}


class GuardrailRepository:
    """Repository for querying guardrail analytics data.
    
    This class provides methods for querying and aggregating guardrail violation
    records from DynamoDB, including time range filtering, policy breakdown,
    and source breakdown (INPUT vs OUTPUT).
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the guardrail repository.
        
        Args:
            table_name: DynamoDB table name (defaults to GUARDRAIL_TABLE_NAME env var)
            region: AWS region (defaults to AWS_REGION env var)
        """
        self.table_name = table_name or os.environ.get(
            "GUARDRAIL_TABLE_NAME", "agentcore-guardrail-violations"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
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
    ) -> List[GuardrailRecord]:
        """Get all guardrail records within a time range.
        
        Performs a full table scan filtered by timestamp.
        
        Args:
            start_time: Start of the time range (inclusive)
            end_time: End of the time range (inclusive)
            
        Returns:
            List of guardrail records within the time range
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._scan_by_time_range,
                start_time.isoformat(),
                end_time.isoformat(),
            )
            return [GuardrailRecord.from_dynamodb_item(item) for item in items]
        except ClientError as e:
            logger.error(
                "Failed to scan guardrail records",
                extra={
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to scan guardrail records (unexpected error)",
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

    async def get_aggregate_stats(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> GuardrailAggregateStats:
        """Get aggregate statistics for a time period.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            GuardrailAggregateStats with totals and breakdowns
        """
        records = await self.get_all_records(start_time, end_time)
        
        if not records:
            return GuardrailAggregateStats()
        
        # Count violations (action == "GUARDRAIL_INTERVENED")
        violations = [r for r in records if r.action == "GUARDRAIL_INTERVENED"]
        violation_count = len(violations)
        total_evaluations = len(records)
        
        # Calculate violation rate
        violation_rate = violation_count / total_evaluations if total_evaluations > 0 else 0.0
        
        # Count by source
        input_violations = sum(1 for r in violations if r.source == "INPUT")
        output_violations = sum(1 for r in violations if r.source == "OUTPUT")
        
        # Count by policy type
        policy_breakdown = defaultdict(int)
        for record in violations:
            policy_types = record.get_policy_types()
            for policy_type in policy_types:
                policy_breakdown[policy_type] += 1
        
        # Count by specific filter type (e.g., content:INSULTS)
        filter_breakdown = defaultdict(int)
        for record in violations:
            filter_types = record.get_filter_types()
            for filter_info in filter_types:
                key = f"{filter_info['policy']}:{filter_info['type']}"
                filter_breakdown[key] += 1
        
        # Count unique users and sessions with violations
        unique_user_ids = set(r.user_id for r in violations)
        unique_session_ids = set(r.session_id for r in violations)
        
        # Find top filter type
        top_filter = ""
        top_filter_count = 0
        if filter_breakdown:
            top_key = max(filter_breakdown, key=filter_breakdown.get)
            # Extract just the filter type (after the colon)
            top_filter = top_key.split(":")[-1] if ":" in top_key else top_key
            top_filter_count = filter_breakdown[top_key]
        
        return GuardrailAggregateStats(
            total_evaluations=total_evaluations,
            violation_count=violation_count,
            violation_rate=violation_rate,
            input_violations=input_violations,
            output_violations=output_violations,
            policy_breakdown=dict(policy_breakdown),
            filter_breakdown=dict(filter_breakdown),
            unique_users=len(unique_user_ids),
            unique_sessions=len(unique_session_ids),
            top_filter=top_filter,
            top_filter_count=top_filter_count,
        )

    async def get_recent_violations(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 50,
    ) -> List[GuardrailRecord]:
        """Get recent violations with full details.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            limit: Maximum number of records to return
            
        Returns:
            List of guardrail records sorted by timestamp descending
        """
        records = await self.get_all_records(start_time, end_time)
        
        # Filter to only violations
        violations = [r for r in records if r.action == "GUARDRAIL_INTERVENED"]
        
        # Sort by timestamp descending (most recent first)
        violations.sort(key=lambda r: r.timestamp, reverse=True)
        
        return violations[:limit]

    async def get_violation_by_policy(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, int]:
        """Get violation counts grouped by policy type.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            Dictionary mapping policy type to violation count
        """
        records = await self.get_all_records(start_time, end_time)
        
        # Filter to only violations
        violations = [r for r in records if r.action == "GUARDRAIL_INTERVENED"]
        
        # Count by policy type
        policy_counts = defaultdict(int)
        for record in violations:
            policy_types = record.get_policy_types()
            for policy_type in policy_types:
                policy_counts[policy_type] += 1
        
        return dict(policy_counts)
