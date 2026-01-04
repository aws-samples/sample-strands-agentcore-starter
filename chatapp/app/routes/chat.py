"""Chat API routes for HTMX ChatApp.

This module provides the SSE streaming chat endpoint that communicates
with AgentCore Runtime and streams responses back to the client.
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.cognito import extract_user_id, TokenValidationError
from app.auth.middleware import SESSION_COOKIE_NAME
from app.agentcore.client import AgentCoreClient
from app.models.events import MetadataEvent, ToolUseEvent, ToolResultEvent, GuardrailEvent
from app.models.guardrail import GuardrailRecord
from app.models.usage import UsageRecord, ToolUsageRecord
from app.storage.guardrail import GuardrailStorageService
from app.storage.usage import UsageStorageService

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    """Request body for chat endpoint.
    
    Attributes:
        prompt: User message to send to the agent
        session_id: Session ID for conversation context
        model_id: Optional model identifier for LLM selection
    """
    prompt: str = Field(..., min_length=1, description="User message")
    session_id: str = Field(..., min_length=1, description="Session ID")
    model_id: Optional[str] = Field(
        default="global.amazon.nova-2-lite-v1:0",
        description="Model identifier for LLM selection"
    )


def _get_user_info_from_session(request: Request) -> tuple[str, str | None]:
    """Extract user ID and email from session cookie or dev mode.
    
    Args:
        request: Incoming request with session cookie
        
    Returns:
        Tuple of (user_id, user_email) - user_id is UUID, email may be None
        
    Raises:
        HTTPException: If session is invalid or user ID cannot be extracted
    """
    # Check for user from middleware (set by AuthMiddleware)
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "user_id"):
        return user.user_id, getattr(user, "email", None)
    
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        raise HTTPException(status_code=401, detail="No session found")
    
    try:
        session_data = json.loads(session_cookie)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid session")
    
    id_token = session_data.get("id_token")
    if not id_token:
        raise HTTPException(status_code=401, detail="No ID token in session")
    
    try:
        user_id = extract_user_id(id_token)
        # Also extract email from token for display
        from jose import jwt
        claims = jwt.get_unverified_claims(id_token)
        user_email = claims.get("email")
        return user_id, user_email
    except TokenValidationError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


def _is_error_result(result: Any, status: Optional[str] = None) -> bool:
    """Check if a tool result indicates an error.
    
    Args:
        result: The tool result (string, dict, or other)
        status: Optional status field from the event
        
    Returns:
        True if the result indicates an error, False otherwise
    """
    # Check status field first
    if status and status.lower() in ("error", "failed"):
        return True
    
    # Check string results for error indicators
    if isinstance(result, str):
        result_lower = result.lower()
        error_indicators = [
            "error", "failed", "exception", "not found", 
            "invalid", "unable to", "could not", "cannot",
            "traceback", "404", "403", "500", "timeout"
        ]
        return any(indicator in result_lower for indicator in error_indicators)
    
    # Check dict results for error fields
    if isinstance(result, dict):
        return result.get("error") or result.get("status") == "error"
    
    return False


async def _stream_chat_response(
    prompt: str,
    session_id: str,
    user_id: str,
    model_id: str = "global.amazon.nova-2-lite-v1:0",
    user_email: str | None = None,
):
    """Generate SSE stream from AgentCore response.
    
    Accumulates metrics during stream and stores usage record asynchronously
    after stream completes (fire-and-forget pattern per Requirements 2.1, 8.1).
    
    Args:
        prompt: User message
        session_id: Session ID for conversation context
        user_id: User ID for memory operations (UUID)
        model_id: Model identifier for LLM selection
        user_email: User email for analytics display
        
    Yields:
        SSE formatted event strings
    """
    client = AgentCoreClient()
    
    # Accumulate metrics during stream
    accumulated_metrics: Dict[str, Any] = {}
    # Track tool usage from ToolUseEvents in the stream
    tool_usage_counts: Dict[str, Dict[str, int]] = {}
    # Track pending tool uses by ID to correlate with results
    pending_tool_uses: Dict[str, Dict[str, Any]] = {}
    
    async for event in client.invoke_stream(
        prompt=prompt,
        session_id=session_id,
        user_id=user_id,
        model_id=model_id,
    ):
        # Track tool usage from ToolUseEvent
        if isinstance(event, ToolUseEvent):
            tool_name = event.tool_name or "unknown"
            tool_use_id = event.tool_use_id
            
            # Initialize tool in counts if needed
            if tool_name not in tool_usage_counts:
                tool_usage_counts[tool_name] = {
                    "call_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                }
            
            # Track this tool use as pending (will be resolved when result arrives)
            pending_tool_uses[tool_use_id] = {
                "tool_name": tool_name,
                "status": "pending"
            }
            tool_usage_counts[tool_name]["call_count"] += 1
        
        # Track tool results and update success/error counts
        elif isinstance(event, ToolResultEvent):
            tool_use_id = event.tool_use_id
            
            # Find the corresponding tool use
            if tool_use_id in pending_tool_uses:
                tool_info = pending_tool_uses.pop(tool_use_id)
                tool_name = tool_info["tool_name"]
                
                # Determine if result indicates success or error
                is_error = _is_error_result(event.tool_result, event.status)
                
                if is_error:
                    tool_usage_counts[tool_name]["error_count"] += 1
                else:
                    tool_usage_counts[tool_name]["success_count"] += 1
        
        # Capture metrics from MetadataEvent
        if isinstance(event, MetadataEvent) and event.data:
            accumulated_metrics = event.data
        
        # Store guardrail violations asynchronously (fire-and-forget)
        # Requirements 5.1, 5.4: Store violation without blocking response
        if isinstance(event, GuardrailEvent) and event.action == "GUARDRAIL_INTERVENED":
            asyncio.create_task(
                _store_guardrail_violation(event, session_id, user_id)
            )
        
        yield event.to_sse_format()
    
    # Handle any remaining pending tool uses (tools that started but never completed)
    # Mark them as errors since they didn't produce a result
    for tool_use_id, tool_info in pending_tool_uses.items():
        tool_name = tool_info["tool_name"]
        tool_usage_counts[tool_name]["error_count"] += 1
    
    # Merge tool usage into accumulated metrics
    if tool_usage_counts:
        accumulated_metrics["toolMetrics"] = tool_usage_counts
    
    # Store usage asynchronously after stream completes (fire-and-forget)
    # Requirements 2.1, 8.1: Store usage record without blocking response
    if accumulated_metrics:
        asyncio.create_task(
            _store_usage_record(accumulated_metrics, session_id, user_id, model_id, user_email)
        )


async def _store_usage_record(
    metrics: Dict[str, Any],
    session_id: str,
    user_id: str,
    model_id: str,
    user_email: str | None = None,
) -> None:
    """Store usage record from accumulated metrics.
    
    This function is called asynchronously (fire-and-forget) after the stream
    completes. Errors are logged but never raised to ensure chat responses
    are not impacted (Requirements 2.4, 8.2).
    
    Args:
        metrics: Accumulated metrics from MetadataEvent
        session_id: Session ID for the conversation
        user_id: User ID who made the request
        model_id: Model used for the invocation
    """
    from datetime import datetime, timezone
    
    try:
        logger.info(
            "Processing metrics for storage",
            extra={
                "session_id": session_id,
                "metrics_keys": list(metrics.keys()),
                "has_toolMetrics": 'toolMetrics' in metrics,
                "toolMetrics_value": metrics.get('toolMetrics'),
            },
        )
        
        # Build tool_usage from toolMetrics (if available from enhanced metrics)
        tool_usage: Dict[str, ToolUsageRecord] = {}
        tool_metrics_data = metrics.get('toolMetrics', {})
        if tool_metrics_data:
            for tool_name, tool_data in tool_metrics_data.items():
                tool_usage[tool_name] = ToolUsageRecord(
                    call_count=tool_data.get('call_count', 0),
                    success_count=tool_data.get('success_count', 0),
                    error_count=tool_data.get('error_count', 0),
                )
        
        # Generate timestamp if not provided
        timestamp = metrics.get('timestamp') or datetime.now(timezone.utc).isoformat()
        
        # Calculate total_tokens if not provided
        input_tokens = metrics.get('inputTokens', 0) or 0
        output_tokens = metrics.get('outputTokens', 0) or 0
        total_tokens = metrics.get('totalTokens', 0) or (input_tokens + output_tokens)
        
        # Create UsageRecord from metrics
        record = UsageRecord(
            user_id=user_id,
            timestamp=timestamp,
            session_id=session_id,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=metrics.get('latencyMs', 0) or 0,
            tool_usage=tool_usage,
            user_email=user_email,
        )
        
        # Store asynchronously
        storage_service = UsageStorageService()
        await storage_service.store_usage(record)
        
        logger.info(
            "Usage record stored",
            extra={
                "user_id": record.user_id,
                "session_id": record.session_id,
                "total_tokens": record.total_tokens,
            },
        )
    except Exception as e:
        # Log error but don't raise - storage failures should not impact chat
        logger.error(
            "Failed to store usage record",
            extra={
                "user_id": user_id,
                "session_id": session_id,
                "error": str(e),
            },
        )


async def _store_guardrail_violation(
    event: GuardrailEvent,
    session_id: str,
    user_id: str,
) -> None:
    """Store guardrail violation record asynchronously.
    
    This function is called asynchronously (fire-and-forget) when a guardrail
    violation is detected. Errors are logged but never raised to ensure chat
    responses are not impacted (Requirements 5.4).
    
    Args:
        event: GuardrailEvent containing violation details
        session_id: Session ID for the conversation
        user_id: User ID who triggered the violation
    """
    from datetime import datetime, timezone
    
    try:
        # Create GuardrailRecord from event
        record = GuardrailRecord(
            user_id=user_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            source=event.source,
            action=event.action,
            assessments=event.assessments,
            content_preview="",  # Content not available in event for privacy
        )
        
        # Store asynchronously
        storage_service = GuardrailStorageService()
        await storage_service.store_violation(record)
        
        logger.info(
            "Guardrail violation stored",
            extra={
                "user_id": user_id,
                "session_id": session_id,
                "source": event.source,
                "action": event.action,
            },
        )
    except Exception as e:
        # Log error but don't raise - storage failures should not impact chat
        logger.error(
            "Failed to store guardrail violation",
            extra={
                "user_id": user_id,
                "session_id": session_id,
                "error": str(e),
            },
        )


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """SSE streaming chat endpoint.
    
    Accepts a chat request with prompt and session_id, validates authentication,
    and streams the agent response back to the client using SSE.
    
    Args:
        request: Incoming request with session cookie
        body: Chat request with prompt and session_id
        
    Returns:
        SSE stream response
    """
    # Extract user ID and email from session
    user_id, user_email = _get_user_info_from_session(request)
    
    # Validate request
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    
    if not body.session_id.strip():
        raise HTTPException(status_code=400, detail="Session ID cannot be empty")
    
    # Return SSE streaming response
    return StreamingResponse(
        _stream_chat_response(
            prompt=body.prompt,
            session_id=body.session_id,
            user_id=user_id,
            model_id=body.model_id,
            user_email=user_email,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.options("/chat")
async def chat_options():
    """CORS preflight handler for chat endpoint.
    
    Returns:
        Empty response with CORS headers
    """
    return StreamingResponse(
        content=iter([]),
        status_code=204,
        headers={
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
    )
