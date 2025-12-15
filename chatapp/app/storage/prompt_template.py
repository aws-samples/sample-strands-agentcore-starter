"""Prompt template storage service for persisting templates to DynamoDB.

This module provides the PromptTemplateStorageService class for asynchronously
storing and querying prompt templates.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.prompt_template import PromptTemplate

logger = logging.getLogger(__name__)


class PromptTemplateStorageService:
    """Async service for storing prompt templates in DynamoDB.
    
    Attributes:
        table_name: Name of the DynamoDB table
        region: AWS region for DynamoDB
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the prompt template storage service.
        
        Args:
            table_name: DynamoDB table name (defaults to PROMPT_TEMPLATES_TABLE_NAME env var)
            region: AWS region (defaults to AWS_REGION env var)
        """
        self.table_name = table_name or os.environ.get(
            "PROMPT_TEMPLATES_TABLE_NAME", "agentcore-prompt-templates"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
        # Configure boto3 client with retry settings
        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        self._client = boto3.client("dynamodb", config=boto_config)

    async def get_all_templates(self) -> List[PromptTemplate]:
        """Get all prompt templates.
        
        Returns:
            List of all prompt templates
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(None, self._scan_all_sync)
            return [PromptTemplate.from_dynamodb_item(item) for item in items]
        except ClientError as e:
            logger.error(
                "Failed to get all templates (DynamoDB error)",
                extra={
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return []
        except Exception as e:
            logger.error(
                "Failed to get all templates (unexpected error)",
                extra={"error": str(e)},
            )
            return []

    def _scan_all_sync(self) -> List[dict]:
        """Synchronous helper to scan all items.
        
        Returns:
            List of DynamoDB items
        """
        items = []
        paginator = self._client.get_paginator("scan")
        
        for page in paginator.paginate(TableName=self.table_name):
            items.extend(page.get("Items", []))
        
        return items

    async def get_template_by_id(self, template_id: str) -> Optional[PromptTemplate]:
        """Get a prompt template by ID.
        
        Args:
            template_id: The template ID to retrieve
            
        Returns:
            PromptTemplate if found, None otherwise
        """
        try:
            loop = asyncio.get_event_loop()
            item = await loop.run_in_executor(
                None, self._get_item_sync, template_id
            )
            if item:
                return PromptTemplate.from_dynamodb_item(item)
            return None
        except ClientError as e:
            logger.error(
                "Failed to get template by ID (DynamoDB error)",
                extra={
                    "template_id": template_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to get template by ID (unexpected error)",
                extra={"template_id": template_id, "error": str(e)},
            )
            return None

    def _get_item_sync(self, template_id: str) -> Optional[dict]:
        """Synchronous helper to get item by ID.
        
        Args:
            template_id: The template ID to retrieve
            
        Returns:
            DynamoDB item if found, None otherwise
        """
        response = self._client.get_item(
            TableName=self.table_name,
            Key={"template_id": {"S": template_id}},
        )
        return response.get("Item")


    async def create_template(
        self,
        title: str,
        description: str,
        prompt_detail: str,
    ) -> Optional[PromptTemplate]:
        """Create a new prompt template.
        
        Args:
            title: Display title for the template
            description: Brief description
            prompt_detail: The actual prompt text
            
        Returns:
            Created PromptTemplate if successful, None otherwise
        """
        try:
            template_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()
            
            template = PromptTemplate(
                template_id=template_id,
                title=title,
                description=description,
                prompt_detail=prompt_detail,
                created_at=now,
                updated_at=now,
            )
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._put_item_sync, template)
            
            logger.info(
                "Created prompt template",
                extra={"template_id": template_id, "title": title},
            )
            return template
        except ClientError as e:
            logger.error(
                "Failed to create template (DynamoDB error)",
                extra={
                    "title": title,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to create template (unexpected error)",
                extra={"title": title, "error": str(e)},
            )
            return None

    def _put_item_sync(self, template: PromptTemplate) -> None:
        """Synchronous helper to put item in DynamoDB.
        
        Args:
            template: The prompt template to store
        """
        self._client.put_item(
            TableName=self.table_name,
            Item=template.to_dynamodb_item(),
        )

    async def update_template(
        self,
        template_id: str,
        title: str,
        description: str,
        prompt_detail: str,
    ) -> Optional[PromptTemplate]:
        """Update an existing prompt template.
        
        Args:
            template_id: The template ID to update
            title: New display title
            description: New description
            prompt_detail: New prompt text
            
        Returns:
            Updated PromptTemplate if successful, None otherwise
        """
        try:
            # First check if template exists
            existing = await self.get_template_by_id(template_id)
            if not existing:
                logger.warning(
                    "Template not found for update",
                    extra={"template_id": template_id},
                )
                return None
            
            now = datetime.utcnow().isoformat()
            
            template = PromptTemplate(
                template_id=template_id,
                title=title,
                description=description,
                prompt_detail=prompt_detail,
                created_at=existing.created_at,
                updated_at=now,
            )
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._put_item_sync, template)
            
            logger.info(
                "Updated prompt template",
                extra={"template_id": template_id, "title": title},
            )
            return template
        except ClientError as e:
            logger.error(
                "Failed to update template (DynamoDB error)",
                extra={
                    "template_id": template_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to update template (unexpected error)",
                extra={"template_id": template_id, "error": str(e)},
            )
            return None

    async def delete_template(self, template_id: str) -> bool:
        """Delete a prompt template.
        
        Args:
            template_id: The template ID to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._delete_item_sync, template_id
            )
            
            logger.info(
                "Deleted prompt template",
                extra={"template_id": template_id},
            )
            return True
        except ClientError as e:
            logger.error(
                "Failed to delete template (DynamoDB error)",
                extra={
                    "template_id": template_id,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return False
        except Exception as e:
            logger.error(
                "Failed to delete template (unexpected error)",
                extra={"template_id": template_id, "error": str(e)},
            )
            return False

    def _delete_item_sync(self, template_id: str) -> None:
        """Synchronous helper to delete item from DynamoDB.
        
        Args:
            template_id: The template ID to delete
        """
        self._client.delete_item(
            TableName=self.table_name,
            Key={"template_id": {"S": template_id}},
        )
