"""Usage analytics data models for DynamoDB storage.

This module defines dataclasses for storing and querying usage metrics
from agent invocations. Records are stored in DynamoDB with user_id as
partition key and timestamp as sort key.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, Optional, List


@dataclass
class ToolUsageRecord:
    """Record of tool usage within a single invocation.
    
    Attributes:
        call_count: Number of times the tool was called
        success_count: Number of successful calls
        error_count: Number of failed calls
    """
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolUsageRecord":
        """Create instance from dictionary."""
        return cls(
            call_count=data.get("call_count", 0),
            success_count=data.get("success_count", 0),
            error_count=data.get("error_count", 0),
        )


@dataclass
class UsageRecord:
    """A single usage record from an agent invocation.
    
    Stored in DynamoDB with user_id as partition key and timestamp as sort key.
    A GSI on session_id enables session-based lookups.
    
    Attributes:
        user_id: Partition key - the user who made the request (UUID from Cognito sub)
        timestamp: Sort key - ISO 8601 timestamp of the invocation
        session_id: GSI partition key - conversation session identifier
        model_id: The LLM model used for the invocation
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/response tokens
        total_tokens: Total tokens (input + output)
        latency_ms: Response latency in milliseconds
        tool_usage: Dictionary of tool name to ToolUsageRecord
        user_email: Human-readable email for admin display (optional)
    """
    user_id: str
    timestamp: str
    session_id: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    tool_usage: Dict[str, ToolUsageRecord] = field(default_factory=dict)
    user_email: Optional[str] = None
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format.
        
        Returns:
            Dictionary suitable for DynamoDB put_item operation
        """
        # Serialize tool_usage to JSON string
        tool_usage_json = json.dumps({
            name: record.to_dict() 
            for name, record in self.tool_usage.items()
        })
        
        item = {
            "user_id": {"S": self.user_id},
            "timestamp": {"S": self.timestamp},
            "session_id": {"S": self.session_id},
            "model_id": {"S": self.model_id},
            "input_tokens": {"N": str(self.input_tokens)},
            "output_tokens": {"N": str(self.output_tokens)},
            "total_tokens": {"N": str(self.total_tokens)},
            "latency_ms": {"N": str(self.latency_ms)},
            "tool_usage": {"S": tool_usage_json},
        }
        
        if self.user_email:
            item["user_email"] = {"S": self.user_email}
        
        return item
    
    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "UsageRecord":
        """Create instance from DynamoDB item.
        
        Args:
            item: DynamoDB item with typed attribute values
            
        Returns:
            UsageRecord instance
        """
        # Parse tool_usage from JSON string
        tool_usage_json = item.get("tool_usage", {}).get("S", "{}")
        tool_usage_data = json.loads(tool_usage_json)
        tool_usage = {
            name: ToolUsageRecord.from_dict(data)
            for name, data in tool_usage_data.items()
        }
        
        return cls(
            user_id=item.get("user_id", {}).get("S", ""),
            timestamp=item.get("timestamp", {}).get("S", ""),
            session_id=item.get("session_id", {}).get("S", ""),
            model_id=item.get("model_id", {}).get("S", ""),
            input_tokens=int(item.get("input_tokens", {}).get("N", "0")),
            output_tokens=int(item.get("output_tokens", {}).get("N", "0")),
            total_tokens=int(item.get("total_tokens", {}).get("N", "0")),
            latency_ms=int(item.get("latency_ms", {}).get("N", "0")),
            tool_usage=tool_usage,
            user_email=item.get("user_email", {}).get("S"),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary.
        
        Returns:
            Dictionary representation of the record
        """
        return {
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "tool_usage": {
                name: record.to_dict() 
                for name, record in self.tool_usage.items()
            },
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UsageRecord":
        """Create instance from plain dictionary.
        
        Args:
            data: Dictionary with record data
            
        Returns:
            UsageRecord instance
        """
        tool_usage_data = data.get("tool_usage", {})
        tool_usage = {
            name: ToolUsageRecord.from_dict(record_data)
            for name, record_data in tool_usage_data.items()
        }
        
        return cls(
            user_id=data.get("user_id", ""),
            timestamp=data.get("timestamp", ""),
            session_id=data.get("session_id", ""),
            model_id=data.get("model_id", ""),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            total_tokens=data.get("total_tokens", 0),
            latency_ms=data.get("latency_ms", 0),
            tool_usage=tool_usage,
        )


@dataclass
class AggregateStats:
    """Aggregate usage statistics for a time period.
    
    Attributes:
        total_input_tokens: Sum of all input tokens
        total_output_tokens: Sum of all output tokens
        total_tokens: Sum of all tokens
        total_cost: Estimated total cost in USD
        invocation_count: Number of agent invocations
        unique_users: Count of unique users
        unique_sessions: Count of unique sessions
        avg_latency_ms: Average latency in milliseconds
        projected_monthly_cost: Projected monthly cost based on usage rate
    """
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    invocation_count: int = 0
    unique_users: int = 0
    unique_sessions: int = 0
    avg_latency_ms: float = 0.0
    projected_monthly_cost: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ModelStats:
    """Usage statistics for a specific model.
    
    Attributes:
        model_id: The model identifier
        input_tokens: Total input tokens for this model
        output_tokens: Total output tokens for this model
        total_tokens: Total tokens for this model
        cost: Estimated cost for this model's usage
        invocation_count: Number of invocations using this model
    """
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    invocation_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class UserStats:
    """Usage statistics for a specific user.
    
    Attributes:
        user_id: The user identifier
        total_input_tokens: Total input tokens for this user
        total_output_tokens: Total output tokens for this user
        total_tokens: Total tokens for this user
        total_cost: Estimated cost for this user's usage
        session_count: Number of unique sessions
        invocation_count: Number of invocations
    """
    user_id: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    session_count: int = 0
    invocation_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ToolAnalytics:
    """Aggregated analytics for a specific tool.
    
    Attributes:
        tool_name: Name of the tool
        call_count: Total number of calls across all invocations
        success_count: Total successful calls
        error_count: Total failed calls
        success_rate: Ratio of successful calls (0.0 to 1.0)
        error_rate: Ratio of failed calls (0.0 to 1.0)
    """
    tool_name: str
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    success_rate: float = 0.0
    error_rate: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
