"""SSE event models for streaming chat responses.

This module defines dataclasses for Server-Sent Events (SSE) that are
streamed from the AgentCore backend to the HTMX frontend.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict, List


@dataclass
class SSEEvent:
    """Base class for all SSE events.
    
    Attributes:
        type: Event type identifier (message, tool_use, tool_result, error, done, metadata)
    """
    type: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary representation.
        
        Returns:
            Dictionary with event data, excluding None values
        """
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    def to_sse_format(self) -> str:
        """Convert event to SSE wire format.
        
        Returns:
            SSE formatted string: "data: <json>\n\n"
        """
        return f"data: {json.dumps(self.to_dict())}\n\n"


@dataclass
class MessageEvent(SSEEvent):
    """Event containing message content from the agent.
    
    Attributes:
        type: Always "message"
        content: The text content of the message chunk
    """
    content: str
    type: str = field(default="message", init=False)
    
    def __post_init__(self):
        self.type = "message"


@dataclass
class ToolUseEvent(SSEEvent):
    """Event indicating the agent is using a tool.
    
    Attributes:
        type: Always "tool_use"
        tool_name: Name of the tool being invoked
        tool_input: Input parameters passed to the tool
        tool_use_id: Unique identifier for this tool invocation
        status: Current status (started, running, etc.)
    """
    tool_name: str
    tool_input: Optional[Dict[str, Any]] = None
    tool_use_id: Optional[str] = None
    status: str = "started"
    type: str = field(default="tool_use", init=False)
    
    def __post_init__(self):
        self.type = "tool_use"


@dataclass
class ToolResultEvent(SSEEvent):
    """Event containing the result of a tool execution.
    
    Attributes:
        type: Always "tool_result"
        tool_name: Name of the tool that was executed
        tool_result: Result returned by the tool
        tool_use_id: Unique identifier matching the tool_use event
        status: Completion status (completed, error, etc.)
    """
    tool_name: str
    tool_result: Any = None
    tool_use_id: Optional[str] = None
    status: str = "completed"
    type: str = field(default="tool_result", init=False)
    
    def __post_init__(self):
        self.type = "tool_result"


@dataclass
class ErrorEvent(SSEEvent):
    """Event indicating an error occurred.
    
    Attributes:
        type: Always "error"
        message: Human-readable error message
        details: Optional additional error details
    """
    message: str
    details: Optional[str] = None
    type: str = field(default="error", init=False)
    
    def __post_init__(self):
        self.type = "error"


@dataclass
class MetadataEvent(SSEEvent):
    """Event containing metadata about the response.
    
    Attributes:
        type: Always "metadata"
        data: Dictionary containing metadata (token usage, latency, etc.)
    """
    data: Dict[str, Any] = field(default_factory=dict)
    type: str = field(default="metadata", init=False)
    
    def __post_init__(self):
        self.type = "metadata"


@dataclass
class DoneEvent(SSEEvent):
    """Event indicating the stream has completed.
    
    Attributes:
        type: Always "done"
    """
    type: str = field(default="done", init=False)
    
    def __post_init__(self):
        self.type = "done"


@dataclass
class GuardrailEvent(SSEEvent):
    """Event indicating a guardrail would have intervened.
    
    This event is emitted when content evaluation against Bedrock guardrails
    detects a violation in shadow mode. The content is not blocked, but the
    violation is reported for monitoring and UI display.
    
    Attributes:
        type: Always "guardrail"
        source: "INPUT" for user messages, "OUTPUT" for assistant responses
        action: "GUARDRAIL_INTERVENED" or "NONE"
        assessments: List of policy assessments with violation details
    """
    source: str  # "INPUT" or "OUTPUT"
    action: str  # "GUARDRAIL_INTERVENED" or "NONE"
    assessments: List[Dict[str, Any]]
    type: str = field(default="guardrail", init=False)
    
    def __post_init__(self):
        self.type = "guardrail"


def parse_event_from_dict(data: Dict[str, Any]) -> Optional[SSEEvent]:
    """Parse a dictionary into the appropriate SSEEvent subclass.
    
    Args:
        data: Dictionary containing event data with 'type' field
        
    Returns:
        Appropriate SSEEvent subclass instance, or None if type is unknown
    """
    event_type = data.get("type")
    
    if event_type == "message":
        return MessageEvent(content=data.get("content", ""))
    
    elif event_type == "tool_use":
        return ToolUseEvent(
            tool_name=data.get("tool_name", "unknown"),
            tool_input=data.get("tool_input"),
            tool_use_id=data.get("tool_use_id"),
            status=data.get("status", "started"),
        )
    
    elif event_type == "tool_result":
        return ToolResultEvent(
            tool_name=data.get("tool_name", "unknown"),
            tool_result=data.get("tool_result"),
            tool_use_id=data.get("tool_use_id"),
            status=data.get("status", "completed"),
        )
    
    elif event_type == "error":
        return ErrorEvent(
            message=data.get("message", "Unknown error"),
            details=data.get("details"),
        )
    
    elif event_type == "metadata":
        return MetadataEvent(data=data.get("data", {}))
    
    elif event_type == "done":
        return DoneEvent()
    
    elif event_type == "guardrail":
        return GuardrailEvent(
            source=data.get("source", "INPUT"),
            action=data.get("action", "NONE"),
            assessments=data.get("assessments", []),
        )
    
    return None
