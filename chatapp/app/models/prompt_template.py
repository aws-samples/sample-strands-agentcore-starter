"""Prompt template data models for DynamoDB storage.

This module defines dataclasses for storing and querying prompt templates.
Records are stored in DynamoDB with template_id as partition key.
"""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class PromptTemplate:
    """A prompt template record.
    
    Stored in DynamoDB with template_id as partition key.
    
    Attributes:
        template_id: Unique identifier (UUID)
        title: Display title for the template
        description: Brief description shown in the list
        prompt_detail: The actual prompt text to insert
        created_at: ISO 8601 timestamp
        updated_at: ISO 8601 timestamp
    """
    template_id: str
    title: str
    description: str
    prompt_detail: str
    created_at: str
    updated_at: str
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format.
        
        Returns:
            Dictionary suitable for DynamoDB put_item operation
        """
        return {
            "template_id": {"S": self.template_id},
            "title": {"S": self.title},
            "description": {"S": self.description},
            "prompt_detail": {"S": self.prompt_detail},
            "created_at": {"S": self.created_at},
            "updated_at": {"S": self.updated_at},
        }
    
    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "PromptTemplate":
        """Create instance from DynamoDB item.
        
        Args:
            item: DynamoDB item with typed attribute values
            
        Returns:
            PromptTemplate instance
        """
        return cls(
            template_id=item.get("template_id", {}).get("S", ""),
            title=item.get("title", {}).get("S", ""),
            description=item.get("description", {}).get("S", ""),
            prompt_detail=item.get("prompt_detail", {}).get("S", ""),
            created_at=item.get("created_at", {}).get("S", ""),
            updated_at=item.get("updated_at", {}).get("S", ""),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary.
        
        Returns:
            Dictionary representation of the record
        """
        return {
            "template_id": self.template_id,
            "title": self.title,
            "description": self.description,
            "prompt_detail": self.prompt_detail,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
