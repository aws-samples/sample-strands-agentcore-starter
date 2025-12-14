"""User feedback data models for DynamoDB storage.

This module defines dataclasses for storing and querying user feedback
on assistant responses. Records are stored in DynamoDB with user_id as
partition key and timestamp as sort key.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List


@dataclass
class FeedbackRecord:
    """A single feedback record from a user.
    
    Stored in DynamoDB with user_id as partition key and timestamp as sort key.
    A GSI on session_id enables session-based lookups.
    
    Attributes:
        user_id: Partition key - the user who submitted feedback
        timestamp: Sort key - ISO 8601 timestamp
        session_id: GSI partition key - conversation session
        message_id: Unique identifier for the rated message
        user_message: The user's original message/prompt
        assistant_response: The assistant's response that was rated
        tools_used: List of tool names used in the response
        sentiment: 'positive' or 'negative'
        user_comment: Optional comment explaining the rating
    """
    user_id: str
    timestamp: str
    session_id: str
    message_id: str
    user_message: str
    assistant_response: str
    tools_used: List[str]
    sentiment: str  # 'positive' or 'negative'
    user_comment: Optional[str] = None
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format.
        
        Returns:
            Dictionary suitable for DynamoDB put_item operation
        """
        # Serialize tools_used to JSON string
        tools_used_json = json.dumps(self.tools_used)
        
        item = {
            "user_id": {"S": self.user_id},
            "timestamp": {"S": self.timestamp},
            "session_id": {"S": self.session_id},
            "message_id": {"S": self.message_id},
            "user_message": {"S": self.user_message},
            "assistant_response": {"S": self.assistant_response},
            "tools_used": {"S": tools_used_json},
            "sentiment": {"S": self.sentiment},
        }
        
        if self.user_comment is not None:
            item["user_comment"] = {"S": self.user_comment}
        
        return item
    
    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "FeedbackRecord":
        """Create instance from DynamoDB item.
        
        Args:
            item: DynamoDB item with typed attribute values
            
        Returns:
            FeedbackRecord instance
        """
        # Parse tools_used from JSON string
        tools_used_json = item.get("tools_used", {}).get("S", "[]")
        tools_used = json.loads(tools_used_json)
        
        # Get user_comment if present
        user_comment = item.get("user_comment", {}).get("S")
        
        return cls(
            user_id=item.get("user_id", {}).get("S", ""),
            timestamp=item.get("timestamp", {}).get("S", ""),
            session_id=item.get("session_id", {}).get("S", ""),
            message_id=item.get("message_id", {}).get("S", ""),
            user_message=item.get("user_message", {}).get("S", ""),
            assistant_response=item.get("assistant_response", {}).get("S", ""),
            tools_used=tools_used,
            sentiment=item.get("sentiment", {}).get("S", ""),
            user_comment=user_comment,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary.
        
        Returns:
            Dictionary representation of the record
        """
        result = {
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "tools_used": self.tools_used,
            "sentiment": self.sentiment,
        }
        if self.user_comment is not None:
            result["user_comment"] = self.user_comment
        return result


@dataclass
class FeedbackSubmission:
    """Request body for feedback submission API.
    
    Attributes:
        message_id: Unique identifier for the rated message
        session_id: Conversation session identifier
        user_message: The user's original message/prompt
        assistant_response: The assistant's response that was rated
        tools_used: List of tool names used in the response
        sentiment: 'positive' or 'negative'
        user_comment: Optional comment explaining the rating
    """
    message_id: str
    session_id: str
    user_message: str
    assistant_response: str
    tools_used: List[str]
    sentiment: str
    user_comment: Optional[str] = None


@dataclass
class FeedbackStats:
    """Aggregate feedback statistics.
    
    Attributes:
        total_count: Total number of feedback records
        positive_count: Number of positive feedback records
        negative_count: Number of negative feedback records
        positive_percentage: Percentage of positive feedback (0.0 to 100.0)
    """
    total_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    positive_percentage: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_records(cls, records: List[FeedbackRecord]) -> "FeedbackStats":
        """Compute statistics from a list of feedback records.
        
        Args:
            records: List of FeedbackRecord instances
            
        Returns:
            FeedbackStats with computed values
        """
        total_count = len(records)
        positive_count = sum(1 for r in records if r.sentiment == "positive")
        negative_count = sum(1 for r in records if r.sentiment == "negative")
        
        positive_percentage = 0.0
        if total_count > 0:
            positive_percentage = (positive_count / total_count) * 100
        
        return cls(
            total_count=total_count,
            positive_count=positive_count,
            negative_count=negative_count,
            positive_percentage=positive_percentage,
        )
