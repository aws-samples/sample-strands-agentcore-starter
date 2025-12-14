"""Feedback repository for querying and aggregating feedback data.

This module provides the FeedbackRepository class for querying feedback records
from DynamoDB and computing aggregate statistics for admin views.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.feedback import FeedbackRecord, FeedbackStats

logger = logging.getLogger(__name__)


class FeedbackRepository:
    """Repository for querying feedback data for admin views.
    
    This class provides methods for querying and aggregating feedback records
    from DynamoDB, including time range filtering, sentiment filtering,
    and aggregate statistics computation.
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the feedback repository.
        
        Args:
            table_name: DynamoDB table name (defaults to FEEDBACK_TABLE_NAME env var)
            region: AWS region (defaults to AWS_REGION env var)
        """
        self.table_name = table_name or os.environ.get(
            "FEEDBACK_TABLE_NAME", "agentcore-feedback"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
        # Configure boto3 client with retry settings
        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        self._client = boto3.client("dynamodb", config=boto_config)

    async def get_all_feedback(
        self,
        start_time: datetime,
        end_time: datetime,
        sentiment: Optional[str] = None,
    ) -> List[FeedbackRecord]:
        """Get all feedback records with optional filtering.
        
        Performs a full table scan filtered by timestamp and optionally by sentiment.
        Results are sorted by timestamp descending (most recent first).
        
        Args:
            start_time: Start of the time range (inclusive)
            end_time: End of the time range (inclusive)
            sentiment: Optional sentiment filter ('positive' or 'negative')
            
        Returns:
            List of feedback records within the time range, sorted by timestamp descending
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(
                None,
                self._scan_with_filters,
                start_time.isoformat(),
                end_time.isoformat(),
                sentiment,
            )
            records = [FeedbackRecord.from_dynamodb_item(item) for item in items]
            # Sort by timestamp descending (most recent first)
            records.sort(key=lambda r: r.timestamp, reverse=True)
            return records
        except ClientError as e:
            logger.error(
                "Failed to scan feedback records",
                extra={
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to scan feedback records (unexpected error)",
                extra={"error": str(e)},
            )
            return []


    def _scan_with_filters(
        self,
        start_time_iso: str,
        end_time_iso: str,
        sentiment: Optional[str] = None,
    ) -> List[dict]:
        """Synchronous helper to scan with time range and optional sentiment filter.
        
        Args:
            start_time_iso: Start time in ISO format
            end_time_iso: End time in ISO format
            sentiment: Optional sentiment filter ('positive' or 'negative')
            
        Returns:
            List of DynamoDB items
        """
        items = []
        paginator = self._client.get_paginator("scan")
        
        # Build filter expression
        filter_expression = "#ts BETWEEN :start AND :end"
        expression_attribute_names = {"#ts": "timestamp"}
        expression_attribute_values = {
            ":start": {"S": start_time_iso},
            ":end": {"S": end_time_iso},
        }
        
        # Add sentiment filter if provided
        if sentiment:
            filter_expression += " AND sentiment = :sentiment"
            expression_attribute_values[":sentiment"] = {"S": sentiment}
        
        for page in paginator.paginate(
            TableName=self.table_name,
            FilterExpression=filter_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values,
        ):
            items.extend(page.get("Items", []))
        
        return items

    async def get_feedback_stats(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> FeedbackStats:
        """Get aggregate feedback statistics for a time period.
        
        Args:
            start_time: Start of the time range
            end_time: End of the time range
            
        Returns:
            FeedbackStats with computed totals and percentages
        """
        # Get all records without sentiment filter to compute stats
        records = await self.get_all_feedback(start_time, end_time, sentiment=None)
        return FeedbackStats.from_records(records)
