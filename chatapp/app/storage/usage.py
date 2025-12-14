"""Usage storage service for persisting usage records to DynamoDB.

This module provides the UsageStorageService class for asynchronously storing
and querying usage records. Storage operations are fire-and-forget to avoid
blocking user responses.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.usage import UsageRecord

logger = logging.getLogger(__name__)


class UsageStorageService:
    """Async service for storing usage records in DynamoDB.
    
    This service provides fire-and-forget storage operations that log errors
    but never raise exceptions, ensuring chat responses are not blocked by
    analytics overhead.
    
    Attributes:
        table_name: Name of the DynamoDB table
        region: AWS region for DynamoDB
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the usage storage service.
        
        Args:
            table_name: DynamoDB table name (defaults to USAGE_TABLE_NAME env var)
            region: AWS region (defaults to AWS_REGION env var)
        """
        self.table_name = table_name or os.environ.get(
            "USAGE_TABLE_NAME", "agentcore-usage-records"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
        # Configure boto3 client with retry settings
        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        self._client = boto3.client("dynamodb", config=boto_config)

    async def store_usage(self, record: UsageRecord) -> None:
        """Store a usage record without blocking.
        
        This method performs the storage operation asynchronously using
        fire-and-forget pattern. Errors are logged but never raised to
        ensure chat responses are not impacted.
        
        Args:
            record: The usage record to store
        """
        try:
            # Run the synchronous boto3 call in a thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                self._put_item,
                record,
            )
            logger.info(
                "Stored usage record",
                extra={
                    "user_id": record.user_id,
                    "session_id": record.session_id,
                    "total_tokens": record.total_tokens,
                },
            )
        except ClientError as e:
            logger.error(
                "Failed to store usage record (DynamoDB error)",
                extra={
                    "user_id": record.user_id,
                    "session_id": record.session_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
        except Exception as e:
            logger.error(
                "Failed to store usage record (unexpected error)",
                extra={
                    "user_id": record.user_id,
                    "session_id": record.session_id,
                    "error": str(e),
                },
            )
    
    def _put_item(self, record: UsageRecord) -> None:
        """Synchronous helper to put item in DynamoDB.
        
        Args:
            record: The usage record to store
        """
        self._client.put_item(
            TableName=self.table_name,
            Item=record.to_dynamodb_item(),
        )

    async def query_by_user(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[UsageRecord]:
        """Query usage records for a user within a time range.
        
        Args:
            user_id: The user ID to query
            start_time: Start of the time range (inclusive)
            end_time: End of the time range (inclusive)
            
        Returns:
            List of usage records for the user within the time range
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
                "Failed to query usage records by user",
                extra={
                    "user_id": user_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to query usage records by user (unexpected error)",
                extra={
                    "user_id": user_id,
                    "error": str(e),
                },
            )
            return []
    
    def _query_by_user_sync(
        self,
        user_id: str,
        start_time_iso: str,
        end_time_iso: str,
    ) -> List[dict]:
        """Synchronous helper to query by user.
        
        Args:
            user_id: The user ID to query
            start_time_iso: Start time in ISO format
            end_time_iso: End time in ISO format
            
        Returns:
            List of DynamoDB items
        """
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

    async def query_by_session(self, session_id: str) -> List[UsageRecord]:
        """Query all usage records for a session.
        
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
                "Failed to query usage records by session",
                extra={
                    "session_id": session_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to query usage records by session (unexpected error)",
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
