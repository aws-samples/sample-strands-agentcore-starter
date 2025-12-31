"""Runtime usage repository for querying AgentCore runtime metrics.

This module provides the RuntimeUsageRepository class for querying runtime
usage records from DynamoDB, including vCPU hours and memory GB-hours.
"""

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional
from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# AgentCore Runtime pricing (USD)
VCPU_HOUR_RATE = Decimal("0.0895")  # per vCPU-hour
MEMORY_GB_HOUR_RATE = Decimal("0.00945")  # per GB-hour


@dataclass
class RuntimeUsageRecord:
    """A single runtime usage record from AgentCore Runtime."""
    
    session_id: str
    timestamp: int
    vcpu_hours: Decimal
    memory_gb_hours: Decimal
    time_elapsed_seconds: Decimal
    agent_name: str
    region: str
    date_partition: str
    
    @classmethod
    def from_dynamodb_item(cls, item: dict) -> "RuntimeUsageRecord":
        """Create a RuntimeUsageRecord from a DynamoDB item."""
        return cls(
            session_id=item.get("session_id", {}).get("S", ""),
            timestamp=int(item.get("timestamp", {}).get("N", 0)),
            vcpu_hours=Decimal(item.get("vcpu_hours", {}).get("S", "0")),
            memory_gb_hours=Decimal(item.get("memory_gb_hours", {}).get("S", "0")),
            time_elapsed_seconds=Decimal(item.get("time_elapsed_seconds", {}).get("S", "0")),
            agent_name=item.get("agent_name", {}).get("S", ""),
            region=item.get("region", {}).get("S", ""),
            date_partition=item.get("date_partition", {}).get("S", ""),
        )


@dataclass
class RuntimeUsageStats:
    """Aggregate runtime usage statistics."""
    
    total_vcpu_hours: Decimal = Decimal("0")
    total_memory_gb_hours: Decimal = Decimal("0")
    total_time_seconds: Decimal = Decimal("0")
    total_runtime_cost: Decimal = Decimal("0")
    invocation_count: int = 0
    unique_sessions: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_vcpu_hours": float(self.total_vcpu_hours),
            "total_memory_gb_hours": float(self.total_memory_gb_hours),
            "total_time_seconds": float(self.total_time_seconds),
            "total_runtime_cost": float(self.total_runtime_cost),
            "invocation_count": self.invocation_count,
            "unique_sessions": self.unique_sessions,
        }


@dataclass
class SessionRuntimeStats:
    """Runtime usage statistics for a single session."""
    
    session_id: str
    total_vcpu_hours: Decimal = Decimal("0")
    total_memory_gb_hours: Decimal = Decimal("0")
    total_time_seconds: Decimal = Decimal("0")
    runtime_cost: Decimal = Decimal("0")
    invocation_count: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "total_vcpu_hours": float(self.total_vcpu_hours),
            "total_memory_gb_hours": float(self.total_memory_gb_hours),
            "total_time_seconds": float(self.total_time_seconds),
            "runtime_cost": float(self.runtime_cost),
            "invocation_count": self.invocation_count,
        }


class RuntimeUsageRepository:
    """Repository for querying runtime usage data from DynamoDB."""
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the runtime usage repository.
        
        Args:
            table_name: DynamoDB table name (defaults to config or env var)
            region: AWS region (defaults to AWS_REGION env var)
        """
        if table_name:
            self.table_name = table_name
        else:
            # Try to get from config first, fall back to env var
            try:
                from app.config import get_config
                config = get_config()
                self.table_name = config.runtime_usage_table_name
            except Exception:
                self.table_name = os.environ.get(
                    "RUNTIME_USAGE_TABLE_NAME", "agentcore-runtime-usage"
                )
        
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        self._client = boto3.client("dynamodb", config=boto_config)
    
    def calculate_runtime_cost(
        self,
        vcpu_hours: Decimal,
        memory_gb_hours: Decimal,
    ) -> Decimal:
        """Calculate runtime cost from vCPU and memory usage.
        
        Args:
            vcpu_hours: Total vCPU hours consumed
            memory_gb_hours: Total memory GB-hours consumed
            
        Returns:
            Total runtime cost in USD
        """
        vcpu_cost = vcpu_hours * VCPU_HOUR_RATE
        memory_cost = memory_gb_hours * MEMORY_GB_HOUR_RATE
        return vcpu_cost + memory_cost
    
    async def get_all_records(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> List[RuntimeUsageRecord]:
        """Get all runtime usage records within a time range.
        
        Args:
            start_time: Start of the time range (inclusive)
            end_time: End of the time range (inclusive)
            
        Returns:
            List of runtime usage records
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._scan_by_time_range,
                int(start_time.timestamp() * 1000),
                int(end_time.timestamp() * 1000),
            )
            return [RuntimeUsageRecord.from_dynamodb_item(item) for item in items]
        except ClientError as e:
            logger.error(
                "Failed to scan runtime usage records",
                extra={
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to scan runtime usage records (unexpected error)",
                extra={"error": str(e)},
            )
            return []
    
    def _scan_by_time_range(
        self,
        start_timestamp_ms: int,
        end_timestamp_ms: int,
    ) -> List[dict]:
        """Synchronous helper to scan by time range."""
        items = []
        paginator = self._client.get_paginator("scan")
        
        for page in paginator.paginate(
            TableName=self.table_name,
            FilterExpression="#ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":start": {"N": str(start_timestamp_ms)},
                ":end": {"N": str(end_timestamp_ms)},
            },
        ):
            items.extend(page.get("Items", []))
        
        return items
    
    def compute_aggregate_stats(
        self,
        records: List[RuntimeUsageRecord],
    ) -> RuntimeUsageStats:
        """Compute aggregate statistics from records.
        
        Args:
            records: List of runtime usage records
            
        Returns:
            RuntimeUsageStats with totals
        """
        if not records:
            return RuntimeUsageStats()
        
        total_vcpu = sum(r.vcpu_hours for r in records)
        total_memory = sum(r.memory_gb_hours for r in records)
        total_time = sum(r.time_elapsed_seconds for r in records)
        unique_sessions = len(set(r.session_id for r in records))
        
        total_cost = self.calculate_runtime_cost(total_vcpu, total_memory)
        
        return RuntimeUsageStats(
            total_vcpu_hours=total_vcpu,
            total_memory_gb_hours=total_memory,
            total_time_seconds=total_time,
            total_runtime_cost=total_cost,
            invocation_count=len(records),
            unique_sessions=unique_sessions,
        )
    
    async def get_aggregate_stats(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> RuntimeUsageStats:
        """Get aggregate runtime usage statistics for a time period.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            RuntimeUsageStats with totals
        """
        records = await self.get_all_records(start_time, end_time)
        return self.compute_aggregate_stats(records)
    
    def compute_stats_by_session(
        self,
        records: List[RuntimeUsageRecord],
    ) -> List[SessionRuntimeStats]:
        """Compute per-session runtime usage stats.
        
        Args:
            records: List of runtime usage records
            
        Returns:
            List of SessionRuntimeStats sorted by runtime_cost descending
        """
        session_data: Dict[str, Dict] = defaultdict(lambda: {
            "vcpu_hours": Decimal("0"),
            "memory_gb_hours": Decimal("0"),
            "time_seconds": Decimal("0"),
            "invocation_count": 0,
        })
        
        for record in records:
            session_data[record.session_id]["vcpu_hours"] += record.vcpu_hours
            session_data[record.session_id]["memory_gb_hours"] += record.memory_gb_hours
            session_data[record.session_id]["time_seconds"] += record.time_elapsed_seconds
            session_data[record.session_id]["invocation_count"] += 1
        
        result = []
        for session_id, data in session_data.items():
            cost = self.calculate_runtime_cost(
                data["vcpu_hours"],
                data["memory_gb_hours"],
            )
            result.append(SessionRuntimeStats(
                session_id=session_id,
                total_vcpu_hours=data["vcpu_hours"],
                total_memory_gb_hours=data["memory_gb_hours"],
                total_time_seconds=data["time_seconds"],
                runtime_cost=cost,
                invocation_count=data["invocation_count"],
            ))
        
        # Sort by runtime_cost descending
        result.sort(key=lambda x: x.runtime_cost, reverse=True)
        
        return result
    
    async def get_stats_by_session(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> List[SessionRuntimeStats]:
        """Get per-session runtime usage stats.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            List of SessionRuntimeStats sorted by runtime_cost descending
        """
        records = await self.get_all_records(start_time, end_time)
        return self.compute_stats_by_session(records)
    
    async def get_session_runtime_stats(
        self,
        session_id: str,
    ) -> Optional[SessionRuntimeStats]:
        """Get runtime stats for a specific session.
        
        Args:
            session_id: The session ID to query
            
        Returns:
            SessionRuntimeStats or None if no records found
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._query_by_session_sync,
                session_id,
            )
            
            if not items:
                return None
            
            records = [RuntimeUsageRecord.from_dynamodb_item(item) for item in items]
            stats_list = self.compute_stats_by_session(records)
            
            return stats_list[0] if stats_list else None
            
        except ClientError as e:
            logger.error(
                "Failed to query session runtime stats",
                extra={
                    "session_id": session_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return None
    
    def _query_by_session_sync(self, session_id: str) -> List[dict]:
        """Synchronous helper to query by session."""
        items = []
        paginator = self._client.get_paginator("query")
        
        for page in paginator.paginate(
            TableName=self.table_name,
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={
                ":sid": {"S": session_id},
            },
        ):
            items.extend(page.get("Items", []))
        
        return items
    
    async def get_runtime_costs_for_sessions(
        self,
        session_ids: List[str],
    ) -> Dict[str, Decimal]:
        """Get runtime costs for multiple sessions.
        
        Args:
            session_ids: List of session IDs to query
            
        Returns:
            Dictionary mapping session_id to runtime_cost
        """
        if not session_ids:
            return {}
        
        costs = {}
        for session_id in session_ids:
            stats = await self.get_session_runtime_stats(session_id)
            if stats:
                costs[session_id] = stats.runtime_cost
            else:
                costs[session_id] = Decimal("0")
        
        return costs
