"""App settings data models for DynamoDB storage.

This module defines dataclasses for storing and querying application settings.
Settings are stored in DynamoDB with setting_key as partition key.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class AppSetting:
    """An application setting record.
    
    Stored in DynamoDB with setting_key as partition key.
    
    Attributes:
        setting_key: Unique identifier for the setting (e.g., 'app_title', 'app_subtitle', 'logo_url')
        setting_value: The value of the setting
        setting_type: Type of the setting ('text', 'image', 'boolean', 'number')
        description: Human-readable description of the setting
        updated_at: ISO 8601 timestamp of last update
    """
    setting_key: str
    setting_value: str
    setting_type: str
    description: str
    updated_at: str
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format.
        
        Returns:
            Dictionary suitable for DynamoDB put_item operation
        """
        return {
            "setting_key": {"S": self.setting_key},
            "setting_value": {"S": self.setting_value},
            "setting_type": {"S": self.setting_type},
            "description": {"S": self.description},
            "updated_at": {"S": self.updated_at},
        }
    
    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "AppSetting":
        """Create instance from DynamoDB item.
        
        Args:
            item: DynamoDB item with typed attribute values
            
        Returns:
            AppSetting instance
        """
        return cls(
            setting_key=item.get("setting_key", {}).get("S", ""),
            setting_value=item.get("setting_value", {}).get("S", ""),
            setting_type=item.get("setting_type", {}).get("S", "text"),
            description=item.get("description", {}).get("S", ""),
            updated_at=item.get("updated_at", {}).get("S", ""),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary.
        
        Returns:
            Dictionary representation of the record
        """
        return {
            "setting_key": self.setting_key,
            "setting_value": self.setting_value,
            "setting_type": self.setting_type,
            "description": self.description,
            "updated_at": self.updated_at,
        }
