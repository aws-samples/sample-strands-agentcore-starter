"""App settings storage service for persisting settings to DynamoDB.

This module provides the AppSettingsStorageService class for asynchronously
storing and querying application settings.
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.models.app_settings import AppSetting

logger = logging.getLogger(__name__)


class AppSettingsStorageService:
    """Async service for storing app settings in DynamoDB.
    
    Attributes:
        table_name: Name of the DynamoDB table
        region: AWS region for DynamoDB
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the app settings storage service.
        
        Args:
            table_name: DynamoDB table name (defaults to APP_SETTINGS_TABLE_NAME env var)
            region: AWS region (defaults to AWS_REGION env var)
        """
        self.table_name = table_name or os.environ.get(
            "APP_SETTINGS_TABLE_NAME", "agentcore-app-settings"
        )
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        
        # Configure boto3 client with retry settings
        boto_config = Config(
            region_name=self.region,
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        
        self._client = boto3.client("dynamodb", config=boto_config)

    async def get_all_settings(self) -> Dict[str, AppSetting]:
        """Get all app settings.
        
        Returns:
            Dictionary mapping setting_key to AppSetting
        """
        try:
            loop = asyncio.get_event_loop()
            items = await loop.run_in_executor(None, self._scan_all_sync)
            return {
                item.setting_key: item
                for item in [AppSetting.from_dynamodb_item(i) for i in items]
            }
        except ClientError as e:
            logger.error(
                "Failed to get all settings (DynamoDB error)",
                extra={
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return {}
        except Exception as e:
            logger.error(
                "Failed to get all settings (unexpected error)",
                extra={"error": str(e)},
            )
            return {}

    def _scan_all_sync(self) -> list:
        """Synchronous helper to scan all items.
        
        Returns:
            List of DynamoDB items
        """
        items = []
        paginator = self._client.get_paginator("scan")
        
        for page in paginator.paginate(TableName=self.table_name):
            items.extend(page.get("Items", []))
        
        return items

    async def get_setting(self, setting_key: str) -> Optional[AppSetting]:
        """Get a specific setting by key.
        
        Args:
            setting_key: The setting key to retrieve
            
        Returns:
            AppSetting if found, None otherwise
        """
        try:
            loop = asyncio.get_event_loop()
            item = await loop.run_in_executor(
                None, self._get_item_sync, setting_key
            )
            if item:
                return AppSetting.from_dynamodb_item(item)
            return None
        except ClientError as e:
            logger.error(
                "Failed to get setting (DynamoDB error)",
                extra={
                    "setting_key": setting_key,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to get setting (unexpected error)",
                extra={"setting_key": setting_key, "error": str(e)},
            )
            return None

    def _get_item_sync(self, setting_key: str) -> Optional[dict]:
        """Synchronous helper to get item by key.
        
        Args:
            setting_key: The setting key to retrieve
            
        Returns:
            DynamoDB item if found, None otherwise
        """
        response = self._client.get_item(
            TableName=self.table_name,
            Key={"setting_key": {"S": setting_key}},
        )
        return response.get("Item")

    async def update_setting(
        self,
        setting_key: str,
        setting_value: str,
        setting_type: str = "text",
        description: str = "",
    ) -> Optional[AppSetting]:
        """Update or create a setting.
        
        Args:
            setting_key: The setting key
            setting_value: The new value
            setting_type: Type of the setting
            description: Description of the setting
            
        Returns:
            Updated AppSetting if successful, None otherwise
        """
        try:
            now = datetime.utcnow().isoformat()
            
            setting = AppSetting(
                setting_key=setting_key,
                setting_value=setting_value,
                setting_type=setting_type,
                description=description,
                updated_at=now,
            )
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._put_item_sync, setting)
            
            logger.info(
                "Updated app setting",
                extra={"setting_key": setting_key},
            )
            return setting
        except ClientError as e:
            logger.error(
                "Failed to update setting (DynamoDB error)",
                extra={
                    "setting_key": setting_key,
                    "error_code": e.response.get("Error", {}).get("Code"),
                    "error_message": str(e),
                },
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to update setting (unexpected error)",
                extra={"setting_key": setting_key, "error": str(e)},
            )
            return None

    def _put_item_sync(self, setting: AppSetting) -> None:
        """Synchronous helper to put item in DynamoDB.
        
        Args:
            setting: The app setting to store
        """
        self._client.put_item(
            TableName=self.table_name,
            Item=setting.to_dynamodb_item(),
        )
