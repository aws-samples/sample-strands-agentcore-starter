"""Admin routes for usage analytics dashboard.

This module provides routes for the admin dashboard that displays
usage statistics, cost analysis, and projections.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.admin.repository import UsageRepository
from app.admin.cost_calculator import CostCalculator
from app.admin.guardrail_repository import GuardrailRepository, GuardrailAggregateStats
from app.admin.feedback_repository import FeedbackRepository
from app.admin.runtime_usage_repository import RuntimeUsageRepository
from app.admin.evaluation_repository import EvaluationRepository
from app.auth.cognito import get_user_emails_by_ids
from app.templates_config import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# Display metadata for the evaluators produced by the engine.
EVALUATOR_META = {
    "answer_quality": {"label": "Answer Quality", "color": "#3b82f6", "icon": "⭐"},
    "faithfulness": {"label": "Faithfulness", "color": "#8b5cf6", "icon": "🎯"},
    "tool_selection": {"label": "Tool Selection", "color": "#f59e0b", "icon": "🔧"},
}


def _get_default_time_range() -> tuple[datetime, datetime]:
    """Get default time range (last 7 days).
    
    Returns:
        Tuple of (start_time, end_time)
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=7)
    return start_time, end_time


def _parse_time_range(
    start_time: Optional[str],
    end_time: Optional[str],
) -> tuple[datetime, datetime]:
    """Parse time range from query parameters.
    
    Args:
        start_time: ISO format start time string
        end_time: ISO format end time string (if None, uses current time)
        
    Returns:
        Tuple of (start_time, end_time) as datetime objects
    """
    def parse_iso(s: str) -> datetime:
        """Parse ISO format string to datetime."""
        # Remove Z suffix
        s = s.replace('Z', '')
        # Remove timezone offset if present (e.g., +00:00)
        if '+' in s:
            s = s.split('+')[0]
        elif s.count('-') > 2:  # Has negative timezone offset
            # Split on last dash that's part of timezone
            parts = s.rsplit('-', 1)
            if ':' in parts[-1]:  # It's a timezone offset
                s = parts[0]
        return datetime.fromisoformat(s)
    
    if start_time:
        try:
            parsed_start = parse_iso(start_time)
            # If end_time not provided, use current time (allows refresh to get new data)
            if end_time:
                parsed_end = parse_iso(end_time)
            else:
                parsed_end = datetime.utcnow()
            return (parsed_start, parsed_end)
        except ValueError as e:
            logger.warning(f"Failed to parse time range: {e}, start={start_time}, end={end_time}")
            pass
    
    return _get_default_time_range()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Main admin dashboard with highlights from all sections.
    
    Displays:
    - Key metrics overview
    - Top users by usage
    - Top tools by calls
    - Cost summary (token + compute)
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repositories
    repository = UsageRepository()
    guardrail_repo = GuardrailRepository()
    feedback_repo = FeedbackRepository()
    runtime_repo = RuntimeUsageRepository()
    
    # OPTIMIZATION: the usage scan, runtime scan, guardrail scan and feedback
    # scan are independent, so run them concurrently instead of sequentially.
    # (Each repository call offloads its blocking boto3 work to a thread, so
    # asyncio.gather genuinely parallelizes them.)
    records, runtime_stats, guardrail_stats, feedback_stats = await asyncio.gather(
        repository.get_all_records(start_dt, end_dt),
        runtime_repo.get_aggregate_stats(start_dt, end_dt),
        guardrail_repo.get_aggregate_stats(start_dt, end_dt),
        feedback_repo.get_feedback_stats(start_dt, end_dt),
    )
    
    # Compute all stats from the same record set (no additional DB queries)
    aggregate_stats = repository.compute_aggregate_stats(records, start_dt, end_dt)
    user_stats = repository.compute_stats_by_user(records)
    tool_stats = repository.compute_tool_analytics(records)
    model_stats = repository.compute_stats_by_model(records)
    # Per-day series for the trend chart (computed from the same records,
    # so it adds no extra DynamoDB queries to the page load)
    daily_series = repository.compute_daily_series(records, start_dt, end_dt)
    
    # Get top 5 for each category
    top_users = user_stats[:5]
    top_tools = tool_stats[:5]
    sorted_models = sorted(
        model_stats.values(),
        key=lambda m: m.cost,
        reverse=True,
    )[:5]
    
    # Fetch user emails for top users (cached + concurrent under the hood)
    user_ids = [user.user_id for user in top_users]
    user_emails = await get_user_emails_by_ids(user_ids)
    
    # Calculate tool totals for summary card
    total_tool_calls = sum(t.call_count for t in tool_stats)
    total_tool_success = sum(t.success_count for t in tool_stats)
    total_tool_errors = sum(t.error_count for t in tool_stats)
    tool_success_rate = total_tool_success / total_tool_calls if total_tool_calls > 0 else 0.0
    
    # Get current user ID from request state (set by auth middleware)
    current_user = getattr(request.state, "user", None)
    current_user_id = current_user.user_id if current_user else None
    
    # Calculate total cost (token + runtime)
    total_cost = aggregate_stats.total_cost + float(runtime_stats.total_runtime_cost)
    
    projected_monthly = CostCalculator().calculate_monthly_projection(total_cost, days_in_period)
    
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "stats": aggregate_stats,
            "runtime_stats": runtime_stats,
            "total_cost": total_cost,
            "projected_monthly": projected_monthly,
            "top_users": top_users,
            "user_emails": user_emails,
            "top_tools": top_tools,
            "top_models": sorted_models,
            "guardrail_stats": guardrail_stats,
            "feedback_stats": feedback_stats,
            "total_tool_calls": total_tool_calls,
            "total_tool_success": total_tool_success,
            "total_tool_errors": total_tool_errors,
            "tool_success_rate": tool_success_rate,
            "daily_series": daily_series,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
            "current_user_id": current_user_id,
        },
    )


@router.get("/tokens", response_class=HTMLResponse)
async def tokens_analytics(
    request: Request,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Token usage analytics with model breakdown.
    
    Displays:
    - Total tokens (input, output, total)
    - Estimated costs
    - Invocation counts
    - Model breakdown table
    - Projected monthly cost
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository
    repository = UsageRepository()
    
    # OPTIMIZATION: Fetch records once and compute both stats
    records = await repository.get_all_records(start_dt, end_dt)
    aggregate_stats = repository.compute_aggregate_stats(records, start_dt, end_dt)
    model_stats = repository.compute_stats_by_model(records)
    
    # Sort models by cost descending
    sorted_models = sorted(
        model_stats.values(),
        key=lambda m: m.cost,
        reverse=True,
    )
    
    return templates.TemplateResponse(
        "admin/tokens.html",
        {
            "request": request,
            "stats": aggregate_stats,
            "model_stats": sorted_models,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def user_analytics(
    request: Request,
    search: Optional[str] = Query(None, description="Search query for user ID"),
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """User-level usage analytics.
    
    Displays:
    - List of users with token usage totals
    - Session counts per user
    - Runtime costs per user
    - Search functionality for filtering users
    - Users sorted by total tokens descending
    
    Requirements: 4.1, 4.3, 4.4
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repositories
    repository = UsageRepository()
    runtime_repo = RuntimeUsageRepository()
    
    # Fetch usage records once and per-session runtime costs concurrently.
    # (Previously this page scanned the usage table twice and issued one
    # runtime query per session; now it's one usage scan + one runtime scan.)
    all_records, session_runtime_costs = await asyncio.gather(
        repository.get_all_records(start_dt, end_dt),
        runtime_repo.get_runtime_costs_in_range(start_dt, end_dt),
    )
    
    # Compute user stats from the already-fetched records (no extra scan)
    user_stats = repository.compute_stats_by_user(all_records)
    if search and search.strip():
        query_lower = search.strip().lower()
        user_stats = [u for u in user_stats if query_lower in u.user_id.lower()]
    
    # Fetch user emails from Cognito (cached + concurrent under the hood)
    user_ids = [user.user_id for user in user_stats]
    user_emails = await get_user_emails_by_ids(user_ids)
    
    # Map session IDs per user from the same records
    user_sessions: Dict[str, set] = {}
    for record in all_records:
        if record.user_id not in user_sessions:
            user_sessions[record.user_id] = set()
        user_sessions[record.user_id].add(record.session_id)
    
    # Calculate total runtime cost per user
    user_runtime_costs: Dict[str, float] = {}
    for user_id, session_ids in user_sessions.items():
        total_cost = sum(
            float(session_runtime_costs.get(sid, 0))
            for sid in session_ids
        )
        user_runtime_costs[user_id] = total_cost
    
    # Add runtime costs to user stats
    for user in user_stats:
        user.runtime_cost = user_runtime_costs.get(user.user_id, 0.0)
        user.total_cost = user.total_cost + user.runtime_cost
    
    # Get current user ID from request state (set by auth middleware)
    current_user = getattr(request.state, "user", None)
    current_user_id = current_user.user_id if current_user else None
    
    return templates.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "users": user_stats,
            "user_emails": user_emails,
            "search": search or "",
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
            "current_user_id": current_user_id,
        },
    )


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
):
    """Detailed usage for a specific session.
    
    Displays:
    - Session's total token usage
    - Model used
    - Tools invoked with call counts and success rates
    - Duration and latency
    - Individual invocation records
    - Compute costs (vCPU, memory)
    
    Requirements: 4.2
    """
    # Initialize repository and cost calculator
    repository = UsageRepository()
    cost_calculator = CostCalculator()
    runtime_repo = RuntimeUsageRepository()
    
    # Fetch all records for this session using GSI
    records = await repository.get_session_records(session_id)
    
    # Fetch runtime stats for this session
    runtime_stats = await runtime_repo.get_session_runtime_stats(session_id)
    
    if not records:
        return templates.TemplateResponse(
            "admin/session_detail.html",
            {
                "request": request,
                "session_id": session_id,
                "session_stats": None,
                "records": [],
                "tool_usage": [],
                "runtime_stats": runtime_stats,
            },
        )
    
    # Calculate session-level stats
    total_input = sum(r.input_tokens for r in records)
    total_output = sum(r.output_tokens for r in records)
    total_tokens = sum(r.total_tokens for r in records)
    total_latency = sum(r.latency_ms for r in records)
    
    # Get unique models and user
    models_used = list(set(r.model_id for r in records))
    user_id = records[0].user_id if records else ""
    
    # Calculate total token cost
    token_cost = sum(
        cost_calculator.calculate_cost(r.input_tokens, r.output_tokens, r.model_id)
        for r in records
    )
    
    # Calculate total cost (token + runtime)
    runtime_cost = float(runtime_stats.runtime_cost) if runtime_stats else 0.0
    total_cost = token_cost + runtime_cost
    
    # Aggregate tool usage across all records
    tool_data = {}
    for record in records:
        for tool_name, usage in record.tool_usage.items():
            if tool_name not in tool_data:
                tool_data[tool_name] = {
                    "call_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                }
            tool_data[tool_name]["call_count"] += usage.call_count
            tool_data[tool_name]["success_count"] += usage.success_count
            tool_data[tool_name]["error_count"] += usage.error_count
    
    # Convert to list with calculated rates
    tool_usage = []
    for tool_name, data in tool_data.items():
        call_count = data["call_count"]
        success_rate = data["success_count"] / call_count if call_count > 0 else 0.0
        error_rate = data["error_count"] / call_count if call_count > 0 else 0.0
        
        tool_usage.append({
            "tool_name": tool_name,
            "call_count": call_count,
            "success_count": data["success_count"],
            "error_count": data["error_count"],
            "success_rate": success_rate,
            "error_rate": error_rate,
        })
    
    # Sort tools by call count
    tool_usage.sort(key=lambda x: x["call_count"], reverse=True)
    
    # Get time range from records
    timestamps = [r.timestamp for r in records]
    first_timestamp = min(timestamps)
    last_timestamp = max(timestamps)
    
    # Sort records by timestamp (most recent first)
    sorted_records = sorted(records, key=lambda r: r.timestamp, reverse=True)
    
    # Fetch user email from Cognito
    user_emails = await get_user_emails_by_ids([user_id]) if user_id else {}
    user_email = user_emails.get(user_id)
    
    session_stats = {
        "session_id": session_id,
        "user_id": user_id,
        "user_email": user_email,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_tokens,
        "token_cost": token_cost,
        "runtime_cost": runtime_cost,
        "total_cost": total_cost,
        "invocation_count": len(records),
        "avg_latency_ms": total_latency / len(records) if records else 0,
        "models_used": models_used,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
    }
    
    return templates.TemplateResponse(
        "admin/session_detail.html",
        {
            "request": request,
            "session_id": session_id,
            "session_stats": session_stats,
            "records": sorted_records,
            "tool_usage": tool_usage,
            "runtime_stats": runtime_stats,
        },
    )


@router.get("/tools", response_class=HTMLResponse)
async def tool_analytics(
    request: Request,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Tool usage analytics.
    
    Displays:
    - Call counts per tool
    - Success rates
    - Error rates and counts
    - Average execution times
    
    Requirements: 5.1, 5.2, 5.3
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository
    repository = UsageRepository()
    
    # Fetch tool analytics
    tool_stats = await repository.get_tool_analytics(start_dt, end_dt)
    
    # Calculate totals for summary
    total_calls = sum(t.call_count for t in tool_stats)
    total_errors = sum(t.error_count for t in tool_stats)
    overall_error_rate = total_errors / total_calls if total_calls > 0 else 0.0
    
    return templates.TemplateResponse(
        "admin/tools.html",
        {
            "request": request,
            "tools": tool_stats,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "overall_error_rate": overall_error_rate,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/tools/{tool_name}", response_class=HTMLResponse)
async def tool_detail(
    request: Request,
    tool_name: str,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Detailed invocation records for a specific tool.
    
    Displays:
    - All invocations of the tool in the time period
    - Success/error status for each invocation
    - Session and user information
    - Timestamp and latency
    
    Requirements: 5.1, 5.2, 5.3
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository
    repository = UsageRepository()
    
    # Fetch all records in time range
    all_records = await repository.get_all_records(start_dt, end_dt)
    
    # Filter records that used this tool
    tool_records = []
    for record in all_records:
        if tool_name in record.tool_usage:
            tool_usage = record.tool_usage[tool_name]
            # Create a record entry for each tool invocation
            tool_records.append({
                "timestamp": record.timestamp,
                "user_id": record.user_id,
                "session_id": record.session_id,
                "model_id": record.model_id,
                "call_count": tool_usage.call_count,
                "success_count": tool_usage.success_count,
                "error_count": tool_usage.error_count,
                "latency_ms": record.latency_ms,
                "total_tokens": record.total_tokens,
            })
    
    # Sort by timestamp descending (most recent first)
    tool_records.sort(key=lambda x: x["timestamp"], reverse=True)
    
    # Get user emails for display
    user_ids = list(set(r["user_id"] for r in tool_records))
    user_emails = await get_user_emails_by_ids(user_ids) if user_ids else {}
    
    # Calculate stats for this tool
    total_calls = sum(r["call_count"] for r in tool_records)
    total_success = sum(r["success_count"] for r in tool_records)
    total_errors = sum(r["error_count"] for r in tool_records)
    success_rate = total_success / total_calls if total_calls > 0 else 0.0
    error_rate = total_errors / total_calls if total_calls > 0 else 0.0
    
    return templates.TemplateResponse(
        "admin/tool_detail.html",
        {
            "request": request,
            "tool_name": tool_name,
            "records": tool_records,
            "user_emails": user_emails,
            "total_calls": total_calls,
            "total_success": total_success,
            "total_errors": total_errors,
            "success_rate": success_rate,
            "error_rate": error_rate,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    request: Request,
    user_id: str,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Detailed usage for a specific user.
    
    Displays:
    - User's total token usage
    - Session count and list
    - Cost breakdown (token + runtime)
    - Invocation history
    
    Requirements: 4.1, 4.2
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository and cost calculator
    repository = UsageRepository()
    cost_calculator = CostCalculator()
    runtime_repo = RuntimeUsageRepository()
    
    # Fetch this user's records via a direct partition-key Query (user_id is
    # the table PK), instead of scanning the whole table and filtering in
    # Python. Compute the user's stats from those same records.
    user_records = await repository.get_records_by_user(user_id, start_dt, end_dt)
    user_stats_list = repository.compute_stats_by_user(user_records)
    user_stats = user_stats_list[0] if user_stats_list else None
    
    # Fetch runtime costs for this user's sessions concurrently (parallel
    # per-session queries rather than a sequential loop).
    session_ids = list(set(r.session_id for r in user_records))
    session_runtime_costs = await runtime_repo.get_runtime_costs_for_sessions(session_ids)
    
    # Calculate total runtime cost for user
    total_runtime_cost = sum(
        float(cost) for cost in session_runtime_costs.values()
    )
    
    # Group records by session
    sessions = {}
    for record in user_records:
        if record.session_id not in sessions:
            sessions[record.session_id] = {
                "session_id": record.session_id,
                "records": [],
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "token_cost": 0.0,
                "runtime_cost": 0.0,
                "total_cost": 0.0,
                "invocation_count": 0,
                "first_timestamp": record.timestamp,
                "last_timestamp": record.timestamp,
                "models_used": set(),
                "tools_used": set(),
            }
        
        session = sessions[record.session_id]
        session["records"].append(record)
        session["total_tokens"] += record.total_tokens
        session["input_tokens"] += record.input_tokens
        session["output_tokens"] += record.output_tokens
        session["token_cost"] += cost_calculator.calculate_cost(
            record.input_tokens, record.output_tokens, record.model_id
        )
        session["invocation_count"] += 1
        session["models_used"].add(record.model_id)
        
        for tool_name in record.tool_usage.keys():
            session["tools_used"].add(tool_name)
        
        # Track time range
        if record.timestamp < session["first_timestamp"]:
            session["first_timestamp"] = record.timestamp
        if record.timestamp > session["last_timestamp"]:
            session["last_timestamp"] = record.timestamp
    
    # Add runtime costs to sessions and calculate total cost
    for session_id, session in sessions.items():
        if session_id in session_runtime_costs:
            session["runtime_cost"] = float(session_runtime_costs[session_id])
        session["total_cost"] = session["token_cost"] + session["runtime_cost"]
    
    # Convert sets to lists for template
    for session in sessions.values():
        session["models_used"] = list(session["models_used"])
        session["tools_used"] = list(session["tools_used"])
    
    # Sort sessions by last activity (most recent first)
    sorted_sessions = sorted(
        sessions.values(),
        key=lambda s: s["last_timestamp"],
        reverse=True,
    )
    
    # Fetch user email from Cognito
    user_emails = await get_user_emails_by_ids([user_id])
    user_email = user_emails.get(user_id)
    
    # Calculate total cost (token + runtime)
    total_token_cost = user_stats.total_cost if user_stats else 0.0
    total_cost = total_token_cost + total_runtime_cost
    
    return templates.TemplateResponse(
        "admin/user_detail.html",
        {
            "request": request,
            "user_id": user_id,
            "user_email": user_email,
            "user_stats": user_stats,
            "sessions": sorted_sessions,
            "total_token_cost": total_token_cost,
            "total_runtime_cost": total_runtime_cost,
            "total_cost": total_cost,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/api/stats")
async def api_stats(
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
) -> Dict[str, Any]:
    """JSON API endpoint for aggregate stats.
    
    Returns aggregate statistics for the specified time range as JSON.
    Used for client-side updates when time range changes.
    
    Args:
        start_time: Start of the time range (ISO format)
        end_time: End of the time range (ISO format)
        
    Returns:
        JSON object with aggregate stats including:
        - total_input_tokens
        - total_output_tokens
        - total_tokens
        - total_cost
        - invocation_count
        - unique_users
        - unique_sessions
        - avg_latency_ms
        - projected_monthly_cost
        - days_in_period
    
    Requirements: 7.3
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository
    repository = UsageRepository()
    
    # Fetch aggregate stats
    aggregate_stats = await repository.get_aggregate_stats(start_dt, end_dt)
    
    # Return stats as JSON with additional metadata
    return {
        "total_input_tokens": aggregate_stats.total_input_tokens,
        "total_output_tokens": aggregate_stats.total_output_tokens,
        "total_tokens": aggregate_stats.total_tokens,
        "total_cost": aggregate_stats.total_cost,
        "invocation_count": aggregate_stats.invocation_count,
        "unique_users": aggregate_stats.unique_users,
        "unique_sessions": aggregate_stats.unique_sessions,
        "avg_latency_ms": aggregate_stats.avg_latency_ms,
        "projected_monthly_cost": aggregate_stats.projected_monthly_cost,
        "days_in_period": days_in_period,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
    }


@router.get("/guardrails", response_class=HTMLResponse)
async def guardrails_analytics(
    request: Request,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Guardrail analytics page.
    
    Displays:
    - Aggregate statistics (total evaluations, violations, rate)
    - Policy type breakdown
    - Source breakdown (INPUT vs OUTPUT)
    - Recent violations with expandable details
    
    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository
    repository = GuardrailRepository()
    
    # Fetch aggregate stats
    aggregate_stats = await repository.get_aggregate_stats(start_dt, end_dt)
    
    # Fetch recent violations
    recent_violations = await repository.get_recent_violations(start_dt, end_dt, limit=50)
    
    # Fetch user emails for violations
    user_ids = list(set(v.user_id for v in recent_violations))
    user_emails = await get_user_emails_by_ids(user_ids) if user_ids else {}
    
    return templates.TemplateResponse(
        "admin/guardrails.html",
        {
            "request": request,
            "stats": aggregate_stats,
            "violations": recent_violations,
            "user_emails": user_emails,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/history", response_class=HTMLResponse)
async def chat_history(
    request: Request,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Chat history page listing all sessions in reverse chronological order.
    
    Displays:
    - All chat sessions with timestamps
    - User information for each session
    - Token usage and cost per session
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repositories
    repository = UsageRepository()
    cost_calculator = CostCalculator()
    runtime_repo = RuntimeUsageRepository()
    
    # Fetch usage records and per-session runtime costs concurrently.
    # Runtime costs come from a single range scan (was an N+1: one query
    # per session) so cost scales with table size, not session count.
    all_records, session_runtime_costs = await asyncio.gather(
        repository.get_all_records(start_dt, end_dt),
        runtime_repo.get_runtime_costs_in_range(start_dt, end_dt),
    )
    
    # Group records by session
    sessions: Dict[str, Dict[str, Any]] = {}
    for record in all_records:
        if record.session_id not in sessions:
            sessions[record.session_id] = {
                "session_id": record.session_id,
                "user_id": record.user_id,
                "total_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "token_cost": 0.0,
                "runtime_cost": 0.0,
                "total_cost": 0.0,
                "invocation_count": 0,
                "first_timestamp": record.timestamp,
                "last_timestamp": record.timestamp,
                "models_used": set(),
                "tools_used": set(),
            }
        
        session = sessions[record.session_id]
        session["total_tokens"] += record.total_tokens
        session["input_tokens"] += record.input_tokens
        session["output_tokens"] += record.output_tokens
        session["token_cost"] += cost_calculator.calculate_cost(
            record.input_tokens, record.output_tokens, record.model_id
        )
        session["invocation_count"] += 1
        session["models_used"].add(record.model_id)
        
        for tool_name in record.tool_usage.keys():
            session["tools_used"].add(tool_name)
        
        # Track time range
        if record.timestamp < session["first_timestamp"]:
            session["first_timestamp"] = record.timestamp
        if record.timestamp > session["last_timestamp"]:
            session["last_timestamp"] = record.timestamp
    
    # Add runtime costs to sessions (fetched above in a single range scan)
    for session_id, session in sessions.items():
        session["runtime_cost"] = float(session_runtime_costs.get(session_id, 0))
        session["total_cost"] = session["token_cost"] + session["runtime_cost"]
        # Convert sets to lists for template
        session["models_used"] = list(session["models_used"])
        session["tools_used"] = list(session["tools_used"])
    
    # Sort sessions by last activity (most recent first)
    sorted_sessions = sorted(
        sessions.values(),
        key=lambda s: s["last_timestamp"],
        reverse=True,
    )
    
    # Fetch user emails for all users
    user_ids = list(set(s["user_id"] for s in sorted_sessions))
    user_emails = await get_user_emails_by_ids(user_ids) if user_ids else {}
    
    # Calculate summary stats
    total_sessions = len(sorted_sessions)
    total_messages = sum(s["invocation_count"] for s in sorted_sessions)
    total_cost = sum(s["total_cost"] for s in sorted_sessions)
    
    return templates.TemplateResponse(
        "admin/history.html",
        {
            "request": request,
            "sessions": sorted_sessions,
            "user_emails": user_emails,
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_cost": total_cost,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/history/{session_id}", response_class=HTMLResponse)
async def chat_history_detail(
    request: Request,
    session_id: str,
):
    """Detailed view of a chat session from history.
    
    Shows the same session detail page but with breadcrumbs pointing
    back to Chat History instead of User Sessions.
    """
    # Initialize repository and cost calculator
    repository = UsageRepository()
    cost_calculator = CostCalculator()
    runtime_repo = RuntimeUsageRepository()
    
    # Fetch all records for this session using GSI
    records = await repository.get_session_records(session_id)
    
    # Fetch runtime stats for this session
    runtime_stats = await runtime_repo.get_session_runtime_stats(session_id)
    
    if not records:
        return templates.TemplateResponse(
            "admin/session_detail.html",
            {
                "request": request,
                "session_id": session_id,
                "session_stats": None,
                "records": [],
                "tool_usage": [],
                "runtime_stats": runtime_stats,
                "from_history": True,
            },
        )
    
    # Calculate session-level stats
    total_input = sum(r.input_tokens for r in records)
    total_output = sum(r.output_tokens for r in records)
    total_tokens = sum(r.total_tokens for r in records)
    total_latency = sum(r.latency_ms for r in records)
    
    # Get unique models and user
    models_used = list(set(r.model_id for r in records))
    user_id = records[0].user_id if records else ""
    
    # Calculate total token cost
    token_cost = sum(
        cost_calculator.calculate_cost(r.input_tokens, r.output_tokens, r.model_id)
        for r in records
    )
    
    # Calculate total cost (token + runtime)
    runtime_cost = float(runtime_stats.runtime_cost) if runtime_stats else 0.0
    total_cost = token_cost + runtime_cost
    
    # Aggregate tool usage across all records
    tool_data = {}
    for record in records:
        for tool_name, usage in record.tool_usage.items():
            if tool_name not in tool_data:
                tool_data[tool_name] = {
                    "call_count": 0,
                    "success_count": 0,
                    "error_count": 0,
                }
            tool_data[tool_name]["call_count"] += usage.call_count
            tool_data[tool_name]["success_count"] += usage.success_count
            tool_data[tool_name]["error_count"] += usage.error_count
    
    # Convert to list with calculated rates
    tool_usage = []
    for tool_name, data in tool_data.items():
        call_count = data["call_count"]
        success_rate = data["success_count"] / call_count if call_count > 0 else 0.0
        error_rate = data["error_count"] / call_count if call_count > 0 else 0.0
        
        tool_usage.append({
            "tool_name": tool_name,
            "call_count": call_count,
            "success_count": data["success_count"],
            "error_count": data["error_count"],
            "success_rate": success_rate,
            "error_rate": error_rate,
        })
    
    # Sort tools by call count
    tool_usage.sort(key=lambda x: x["call_count"], reverse=True)
    
    # Get time range from records
    timestamps = [r.timestamp for r in records]
    first_timestamp = min(timestamps)
    last_timestamp = max(timestamps)
    
    # Sort records by timestamp (most recent first)
    sorted_records = sorted(records, key=lambda r: r.timestamp, reverse=True)
    
    # Fetch user email from Cognito
    user_emails = await get_user_emails_by_ids([user_id]) if user_id else {}
    user_email = user_emails.get(user_id)
    
    session_stats = {
        "session_id": session_id,
        "user_id": user_id,
        "user_email": user_email,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_tokens,
        "token_cost": token_cost,
        "runtime_cost": runtime_cost,
        "total_cost": total_cost,
        "invocation_count": len(records),
        "avg_latency_ms": total_latency / len(records) if records else 0,
        "models_used": models_used,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
    }
    
    return templates.TemplateResponse(
        "admin/session_detail.html",
        {
            "request": request,
            "session_id": session_id,
            "session_stats": session_stats,
            "records": sorted_records,
            "tool_usage": tool_usage,
            "runtime_stats": runtime_stats,
            "from_history": True,
        },
    )

@router.get("/evaluations", response_class=HTMLResponse)
async def evaluations_analytics(
    request: Request,
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Evaluations analytics page.

    Displays:
    - Aggregate pass rates per evaluator
    - Failed evaluation count
    - Daily trends
    - Recent sessions
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)

    # Initialize repository
    repository = EvaluationRepository()

    # Fetch all data concurrently
    import asyncio
    stats_task = repository.get_aggregate_stats(start_dt.isoformat(), end_dt.isoformat())
    trends_task = repository.get_daily_trends(start_dt.isoformat(), end_dt.isoformat())
    recent_task = repository.get_recent_sessions(start_dt.isoformat(), end_dt.isoformat(), limit=10)

    stats, trends, recent_sessions = await asyncio.gather(
        stats_task, trends_task, recent_task
    )

    # Define evaluator display metadata
    evaluator_meta = EVALUATOR_META

    return templates.TemplateResponse(
        "admin/evaluations.html",
        {
            "request": request,
            "stats": stats,
            "trends": trends,
            "recent_sessions": recent_sessions,
            "evaluator_meta": evaluator_meta,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@router.get("/evaluations/session/{session_id}", response_class=HTMLResponse)
async def evaluation_session_detail(
    request: Request,
    session_id: str,
):
    """Per-session evaluation drill-down.

    Shows each conversation turn's evaluation results and a deep link to the
    full trace (including message content) in CloudWatch GenAI Observability.
    """
    from app.config import get_config
    from app.helpers.observability import cloudwatch_session_url

    repository = EvaluationRepository()
    turns = await repository.get_session_turns(session_id)

    region = get_config().aws_region
    cloudwatch_url = cloudwatch_session_url(region, session_id)

    evaluator_meta = EVALUATOR_META

    return templates.TemplateResponse(
        "admin/evaluation_session.html",
        {
            "request": request,
            "session_id": session_id,
            "turns": turns,
            "evaluator_meta": evaluator_meta,
            "cloudwatch_url": cloudwatch_url,
        },
    )

