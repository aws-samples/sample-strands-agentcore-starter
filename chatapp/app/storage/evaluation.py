"""Evaluation storage service for persisting evaluation records to DynamoDB.

This module provides the EvaluationStorageService class for asynchronously
storing and querying evaluation records. Storage operations are fire-and-forget
to avoid blocking user responses.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.evaluation import EvaluationRecord

logger = logging.getLogger(__name__)


class EvaluationStorageService:
    """Async service for storing evaluation records in DynamoDB.
    
    Fire-and-forget storage that logs errors but never raises exceptions,
    ensuring chat responses are not blocked by evaluation overhead.
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.table_name = table_name or os.environ.get(
            "EVALUATIONS_TABLE_NAME", "agentcore-evaluations"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")

        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        self._client = boto3.client("dynamodb", config=boto_config)

    async def store_evaluation(self, record: EvaluationRecord) -> None:
        """Store a single evaluation record without blocking."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._put_item, record)
            logger.debug(
                "Stored evaluation record",
                extra={
                    "session_id": record.session_id,
                    "evaluator": record.evaluator_name,
                    "score": record.score,
                },
            )
        except Exception as e:
            logger.error(
                "Failed to store evaluation record",
                extra={
                    "session_id": record.session_id,
                    "evaluator": record.evaluator_name,
                    "error": str(e),
                },
            )

    async def store_evaluations_batch(self, records: List[EvaluationRecord]) -> None:
        """Store multiple evaluation records using batch write."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._batch_write, records)
            logger.info(
                "Stored evaluation batch",
                extra={"count": len(records)},
            )
        except Exception as e:
            logger.error(
                "Failed to store evaluation batch",
                extra={"count": len(records), "error": str(e)},
            )

    def _put_item(self, record: EvaluationRecord) -> None:
        """Synchronous helper to put item in DynamoDB."""
        self._client.put_item(
            TableName=self.table_name,
            Item=record.to_dynamodb_item(),
        )

    def _batch_write(self, records: List[EvaluationRecord]) -> None:
        """Synchronous helper for batch write (max 25 items per batch)."""
        for i in range(0, len(records), 25):
            batch = records[i:i + 25]
            request_items = {
                self.table_name: [
                    {"PutRequest": {"Item": r.to_dynamodb_item()}}
                    for r in batch
                ]
            }
            self._client.batch_write_item(RequestItems=request_items)

    async def query_by_session(self, session_id: str) -> List[EvaluationRecord]:
        """Query all evaluation records for a session."""
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None, self._query_by_session_sync, session_id
            )
            return [EvaluationRecord.from_dynamodb_item(item) for item in items]
        except Exception as e:
            logger.error(
                "Failed to query evaluations by session",
                extra={"session_id": session_id, "error": str(e)},
            )
            return []

    def _query_by_session_sync(self, session_id: str) -> List[dict]:
        """Synchronous helper to query by session."""
        items = []
        paginator = self._client.get_paginator("query")
        for page in paginator.paginate(
            TableName=self.table_name,
            KeyConditionExpression="session_id = :sid",
            ExpressionAttributeValues={":sid": {"S": session_id}},
        ):
            items.extend(page.get("Items", []))
        return items

    async def query_by_user(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[EvaluationRecord]:
        """Query evaluation records for a user within a time range using GSI."""
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._query_by_user_sync,
                user_id,
                start_time.isoformat(),
                end_time.isoformat(),
            )
            return [EvaluationRecord.from_dynamodb_item(item) for item in items]
        except Exception as e:
            logger.error(
                "Failed to query evaluations by user",
                extra={"user_id": user_id, "error": str(e)},
            )
            return []

    def _query_by_user_sync(
        self, user_id: str, start_iso: str, end_iso: str
    ) -> List[dict]:
        """Synchronous helper to query by user using GSI."""
        items = []
        paginator = self._client.get_paginator("query")
        for page in paginator.paginate(
            TableName=self.table_name,
            IndexName="user-index",
            KeyConditionExpression="user_id = :uid AND #ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":uid": {"S": user_id},
                ":start": {"S": start_iso},
                ":end": {"S": end_iso},
            },
        ):
            items.extend(page.get("Items", []))
        return items

    async def scan_by_time_range(
        self,
        start_time: str,
        end_time: str,
        limit: int = 5000,
    ) -> List[EvaluationRecord]:
        """Scan evaluations within a time range (for admin dashboard).
        
        Uses a scan with filter - acceptable for PoC/starter kit volumes.
        For production, consider a GSI on a date partition key.
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None, self._scan_by_time_sync, start_time, end_time, limit
            )
            return [EvaluationRecord.from_dynamodb_item(item) for item in items]
        except Exception as e:
            logger.error(
                "Failed to scan evaluations by time range",
                extra={"error": str(e)},
            )
            return []

    def _scan_by_time_sync(
        self, start_time: str, end_time: str, limit: int
    ) -> List[dict]:
        """Synchronous helper to scan by time range."""
        items = []
        paginator = self._client.get_paginator("scan")
        for page in paginator.paginate(
            TableName=self.table_name,
            FilterExpression="#ts BETWEEN :start AND :end",
            ExpressionAttributeNames={"#ts": "timestamp"},
            ExpressionAttributeValues={
                ":start": {"S": start_time},
                ":end": {"S": end_time},
            },
            PaginationConfig={"MaxItems": limit},
        ):
            items.extend(page.get("Items", []))
            if len(items) >= limit:
                break
        return items[:limit]
