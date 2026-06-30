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
from app.helpers.model_catalog import get_model_api
from app.models.events import MessageEvent, MetadataEvent, ToolUseEvent, ToolResultEvent, GuardrailEvent, ReasoningEvent, DoneEvent
from app.models.guardrail import GuardrailRecord
from app.models.usage import UsageRecord, ToolUsageRecord
from app.storage.guardrail import GuardrailStorageService
from app.storage.usage import UsageStorageService
from app.evaluations.engine import run_evaluations

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
        default="anthropic.claude-haiku-4-5",
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
    model_id: str = "anthropic.claude-haiku-4-5",
    model_api: str = "messages",
    user_email: str | None = None,
):
    """Generate SSE stream from AgentCore response.

    Accumulates metrics during the stream and stores the usage record
    asynchronously (fire-and-forget) after the stream completes. Also runs
    response evaluations fire-and-forget once the stream finishes.

    Sends SSE comment keepalives every 15s while waiting for the next token so
    a load balancer / proxy idle timeout never drops a long-running connection.

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

    # Track wall-clock latency since the new providers don't report it
    import time as _time
    _stream_start = _time.time()
    # Server-measured time-to-first-token (ms). Set when the first answer token
    # (MessageEvent) arrives. Measured the SAME way for every model so the
    # per-lane footer in compare mode is an apples-to-apples comparison —
    # provider self-reported latency is inconsistent (some report
    # generation-only, some omit it and we'd fall back to wall-clock).
    _first_token_ms = None

    # Accumulate metrics during stream
    accumulated_metrics: Dict[str, Any] = {}
    # Track tool usage from ToolUseEvents in the stream
    tool_usage_counts: Dict[str, Dict[str, int]] = {}
    # Track pending tool uses by ID to correlate with results
    pending_tool_uses: Dict[str, Dict[str, Any]] = {}
    # Accumulate full agent output text for post-stream evaluation
    accumulated_output: list[str] = []
    # Accumulate tool/KB result content to ground the faithfulness evaluator
    accumulated_context: list[str] = []

    # Keepalive via asyncio.Queue + producer task.
    #
    # asyncio.wait_for() on an async generator's __anext__() is unsafe: when the
    # timeout fires it cancels the coroutine and leaves the generator in a
    # broken state, causing a RuntimeError on the next iteration. That unhandled
    # exception inside StreamingResponse makes uvicorn RST the HTTP/2 stream
    # (ERR_HTTP2_PROTOCOL_ERROR 200).
    #
    # The safe pattern: run the generator in a separate task that pushes events
    # onto a Queue. The consumer waits on the queue with a timeout; on timeout
    # it yields an SSE comment (invisible to the browser, resets the idle timer)
    # and loops. The generator task is never interrupted.
    KEEPALIVE_INTERVAL = 15  # seconds — well under typical 60s LB idle timeouts
    _SENTINEL = object()  # signals end-of-stream
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    async def _producer():
        try:
            async for ev in client.invoke_stream(
                prompt=prompt,
                session_id=session_id,
                user_id=user_id,
                model_id=model_id,
                model_api=model_api,
            ):
                await queue.put(ev)
        except Exception as exc:
            logger.error("AgentCore stream error in producer: %s", exc)
        finally:
            await queue.put(_SENTINEL)

    producer_task = asyncio.create_task(_producer())

    try:
      while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
        except asyncio.TimeoutError:
            # No event within the interval — send an SSE comment to reset the
            # proxy/LB idle timer. Comments are ignored by EventSource clients.
            yield ": keepalive\n\n"
            continue

        if item is _SENTINEL:
            break

        event = item

        # Accumulate full output for post-stream evaluation.
        # Tool/text separation (line breaks) is handled client-side in chat.js.
        if isinstance(event, MessageEvent) and event.content:
            accumulated_output.append(event.content)
            if _first_token_ms is None:
                _first_token_ms = int((_time.time() - _stream_start) * 1000)

        # Track reasoning events but don't include in evaluation output
        if isinstance(event, ReasoningEvent):
            pass  # Just pass through to SSE, don't accumulate for eval

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

                # Determine if result indicates success or error (usage stats only)
                is_error = _is_error_result(event.tool_result, event.status)

                if is_error:
                    tool_usage_counts[tool_name]["error_count"] += 1
                else:
                    tool_usage_counts[tool_name]["success_count"] += 1

            # Capture the tool/KB output as grounding context for the
            # faithfulness judge, regardless of the error heuristic. The
            # heuristic does substring matching ("error", "cannot", ...) that
            # misclassifies legitimate source text, so it must not gate what
            # the judge sees.
            if event.tool_result is not None:
                tool_label = (event.tool_use_id or "tool")
                result_text = (
                    event.tool_result
                    if isinstance(event.tool_result, str)
                    else json.dumps(event.tool_result, default=str)
                )
                accumulated_context.append(f"[{tool_label}] {result_text}")

        # Capture metrics from MetadataEvent
        if isinstance(event, MetadataEvent) and event.data:
            accumulated_metrics = event.data
            # Inject wall-clock latency if not provided by the model
            if not accumulated_metrics.get('latencyMs'):
                accumulated_metrics['latencyMs'] = int((_time.time() - _stream_start) * 1000)

        # Store guardrail violations asynchronously (fire-and-forget) so
        # violation capture never blocks the streamed response.
        if isinstance(event, GuardrailEvent) and event.action == "GUARDRAIL_INTERVENED":
            asyncio.create_task(
                _store_guardrail_violation(event, session_id, user_id)
            )

        # Right before the terminal [DONE], emit one authoritative,
        # server-measured timing event so every lane's footer uses the SAME
        # clock. `ttftMs` = time to first answer token; `totalMs` = full
        # wall-clock. Both are measured identically for every model, unlike the
        # provider-reported `latencyMs`. We also set `latencyMs = totalMs` for
        # back-compat with any consumer still reading the old field.
        if isinstance(event, DoneEvent):
            total_ms = int((_time.time() - _stream_start) * 1000)
            ttft_ms = _first_token_ms if _first_token_ms is not None else total_ms
            timing = {'ttftMs': ttft_ms, 'totalMs': total_ms, 'latencyMs': total_ms}
            # Always send the timing to the client (drives the footer), even
            # when the model reported no token metrics.
            yield MetadataEvent(data={**(accumulated_metrics or {}), **timing}).to_sse_format()
            # Only fold timings into the stored usage record when real model
            # metrics exist, preserving the "don't store empty usage" behavior.
            if accumulated_metrics:
                accumulated_metrics.update(timing)
            yield event.to_sse_format()
            continue

        yield event.to_sse_format()

    finally:
        # Always cancel the producer task to avoid resource leaks if the client
        # disconnects before the stream finishes.
        producer_task.cancel()
        try:
            await producer_task
        except (asyncio.CancelledError, Exception):
            pass

    # Handle any remaining pending tool uses (tools that started but never completed)
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

    # Run evaluations asynchronously after stream completes (fire-and-forget).
    # Evaluation failures are handled internally and never impact the response.
    # The wrapper first pulls recent conversation history from memory so judges
    # can interpret follow-up turns (e.g. "yes") in context.
    full_output = "".join(accumulated_output)
    if full_output.strip():
        asyncio.create_task(
            _evaluate_turn_with_history(
                prompt=prompt,
                full_output=full_output,
                session_id=session_id,
                user_id=user_id,
                model_id=model_id,
                tool_usage_counts=tool_usage_counts or None,
                input_tokens=accumulated_metrics.get("inputTokens", 0) or 0,
                output_tokens=accumulated_metrics.get("outputTokens", 0) or 0,
                context_items=list(accumulated_context) if accumulated_context else None,
            )
        )


async def _fetch_conversation_history(
    session_id: str,
    user_id: str,
    exclude_texts: set[str],
    max_messages: int = 10,
) -> Optional[str]:
    """Fetch recent conversation history from AgentCore Memory for eval context.

    Returns a plain-text transcript of up to `max_messages` recent messages
    (chronological), excluding any whose text matches the current turn so the
    judge is not handed the answer it is supposed to assess. Returns None when
    memory is unconfigured/empty or on any error (evaluation still runs without
    history).
    """
    try:
        from app.agentcore.memory import MemoryClient

        mem = MemoryClient()
        events = await mem.get_events(
            session_id=session_id,
            user_id=user_id,
            max_results=max_messages * 2 + 4,
        )
        if not events:
            return None

        events = sorted(events, key=lambda e: e.timestamp)
        lines = []
        for ev in events:
            text = (ev.content or "").strip()
            if not text or text in exclude_texts:
                continue
            role = "User" if (ev.role or "").lower() == "user" else "Assistant"
            lines.append(f"{role}: {text}")

        if not lines:
            return None
        return "\n".join(lines[-max_messages:])
    except Exception as e:
        logger.warning("Failed to fetch conversation history for evaluation: %s", e)
        return None


async def _evaluate_turn_with_history(
    prompt: str,
    full_output: str,
    session_id: str,
    user_id: str,
    model_id: str,
    tool_usage_counts: Optional[Dict[str, Dict[str, int]]],
    input_tokens: int,
    output_tokens: int,
    context_items: Optional[list[str]],
) -> None:
    """Fetch conversation history, then run evaluations (fire-and-forget)."""
    history = await _fetch_conversation_history(
        session_id=session_id,
        user_id=user_id,
        exclude_texts={prompt.strip(), full_output.strip()},
    )
    await run_evaluations(
        user_input=prompt,
        agent_output=full_output,
        session_id=session_id,
        user_id=user_id,
        model_id=model_id,
        tool_usage=tool_usage_counts,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        context_items=context_items,
        conversation_history=history,
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
            model_api=get_model_api(body.model_id),
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
