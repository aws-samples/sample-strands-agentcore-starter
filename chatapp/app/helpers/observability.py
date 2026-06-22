"""Helpers for building deep links into AWS CloudWatch GenAI Observability.

The agent emits OpenTelemetry traces (including full message content) to
X-Ray / CloudWatch via AgentCore Runtime. Rather than duplicating that
content into the app, the admin UI shows evaluation results and links out
to the CloudWatch GenAI Observability console for the full trace.
"""

from typing import Optional


def cloudwatch_session_url(region: str, session_id: str) -> str:
    """Build a deep link to a session in CloudWatch GenAI Observability.

    Args:
        region: AWS region (e.g. "us-west-2")
        session_id: AgentCore session identifier

    Returns:
        Console URL that lands on the session's traces in GenAI Observability.
    """
    return (
        f"https://{region}.console.aws.amazon.com/cloudwatch/home"
        f"?region={region}#gen-ai-observability/agent-core/session/{session_id}"
    )


def cloudwatch_trace_url(
    region: str,
    session_id: str,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
) -> str:
    """Build a deep link to a specific trace/span within a session.

    Falls back to the session-level URL when trace identifiers are not
    available (the app does not capture trace IDs by default).

    Args:
        region: AWS region (e.g. "us-west-2")
        session_id: AgentCore session identifier
        trace_id: OTEL trace ID for the turn (optional)
        span_id: OTEL span ID for the turn (optional)

    Returns:
        Console URL targeting the trace/span, or the session URL as fallback.
    """
    base = cloudwatch_session_url(region, session_id)
    if trace_id:
        base += f"?traceId={trace_id}"
        if span_id:
            base += f"&spanId={span_id}"
    return base
