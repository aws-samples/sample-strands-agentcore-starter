"""Unit tests for data models."""

import pytest
from app.models.usage import (
    ToolUsageRecord,
    UsageRecord,
    AggregateStats,
)


class TestToolUsageRecord:
    """Tests for ToolUsageRecord dataclass."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        record = ToolUsageRecord(call_count=5, success_count=4, error_count=1)
        
        result = record.to_dict()
        
        assert result == {"call_count": 5, "success_count": 4, "error_count": 1}

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {"call_count": 10, "success_count": 8, "error_count": 2}
        
        record = ToolUsageRecord.from_dict(data)
        
        assert record.call_count == 10
        assert record.success_count == 8
        assert record.error_count == 2

    def test_from_dict_with_missing_keys(self):
        """Test deserialization handles missing keys with defaults."""
        record = ToolUsageRecord.from_dict({})
        
        assert record.call_count == 0
        assert record.success_count == 0
        assert record.error_count == 0


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_to_dynamodb_item(self):
        """Test conversion to DynamoDB item format."""
        record = UsageRecord(
            user_id="user-123",
            timestamp="2025-01-03T10:00:00",
            session_id="session-456",
            model_id="claude-3",
            input_tokens=100,
            output_tokens=200,
            total_tokens=300,
            latency_ms=500,
        )
        
        item = record.to_dynamodb_item()
        
        assert item["user_id"] == {"S": "user-123"}
        assert item["timestamp"] == {"S": "2025-01-03T10:00:00"}
        assert item["input_tokens"] == {"N": "100"}
        assert item["output_tokens"] == {"N": "200"}

    def test_from_dynamodb_item(self):
        """Test creation from DynamoDB item format."""
        item = {
            "user_id": {"S": "user-abc"},
            "timestamp": {"S": "2025-01-03T12:00:00"},
            "session_id": {"S": "sess-xyz"},
            "model_id": {"S": "claude-3"},
            "input_tokens": {"N": "150"},
            "output_tokens": {"N": "250"},
            "total_tokens": {"N": "400"},
            "latency_ms": {"N": "750"},
            "tool_usage": {"S": "{}"},
        }
        
        record = UsageRecord.from_dynamodb_item(item)
        
        assert record.user_id == "user-abc"
        assert record.input_tokens == 150
        assert record.output_tokens == 250
        assert record.latency_ms == 750

    def test_dynamodb_roundtrip(self):
        """Test that DynamoDB serialization round-trips correctly."""
        original = UsageRecord(
            user_id="user-roundtrip",
            timestamp="2025-01-03T15:30:00",
            session_id="session-rt",
            model_id="test-model",
            input_tokens=1000,
            output_tokens=2000,
            total_tokens=3000,
            latency_ms=1500,
            tool_usage={
                "web_search": ToolUsageRecord(call_count=3, success_count=2, error_count=1)
            },
        )
        
        item = original.to_dynamodb_item()
        restored = UsageRecord.from_dynamodb_item(item)
        
        assert restored.user_id == original.user_id
        assert restored.input_tokens == original.input_tokens
        assert restored.tool_usage["web_search"].call_count == 3

    def test_to_dict_and_from_dict_roundtrip(self):
        """Test plain dict serialization round-trips correctly."""
        original = UsageRecord(
            user_id="user-dict",
            timestamp="2025-01-03T16:00:00",
            session_id="session-dict",
            model_id="model-dict",
            input_tokens=500,
            output_tokens=1000,
            total_tokens=1500,
            latency_ms=800,
        )
        
        data = original.to_dict()
        restored = UsageRecord.from_dict(data)
        
        assert restored.user_id == original.user_id
        assert restored.total_tokens == original.total_tokens


class TestAggregateStats:
    """Tests for AggregateStats dataclass."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        stats = AggregateStats(
            total_input_tokens=10000,
            total_output_tokens=20000,
            total_cost=5.50,
            invocation_count=100,
        )
        
        result = stats.to_dict()
        
        assert result["total_input_tokens"] == 10000
        assert result["total_cost"] == 5.50
        assert result["invocation_count"] == 100
