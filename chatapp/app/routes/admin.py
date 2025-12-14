"""Admin routes for usage analytics dashboard.

This module provides routes for the admin dashboard that displays
usage statistics, cost analysis, and projections.
"""

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
from app.auth.cognito import get_user_emails_by_ids

logger = logging.getLogger(__name__)

# Set up templates
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])


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
    - Cost summary
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repositories
    repository = UsageRepository()
    guardrail_repo = GuardrailRepository()
    feedback_repo = FeedbackRepository()
    
    # Fetch aggregate stats
    aggregate_stats = await repository.get_aggregate_stats(start_dt, end_dt)
    
    # Fetch top users (limit to 5)
    user_stats = await repository.get_stats_by_user(start_dt, end_dt)
    top_users = user_stats[:5]
    
    # Fetch user emails for top users
    user_ids = [user.user_id for user in top_users]
    user_emails = await get_user_emails_by_ids(user_ids)
    
    # Fetch tool analytics (limit to 5)
    tool_stats = await repository.get_tool_analytics(start_dt, end_dt)
    top_tools = tool_stats[:5]
    
    # Fetch model breakdown
    model_stats = await repository.get_stats_by_model(start_dt, end_dt)
    sorted_models = sorted(
        model_stats.values(),
        key=lambda m: m.cost,
        reverse=True,
    )[:5]  # Top 5 models
    
    # Fetch guardrails stats
    guardrail_stats = await guardrail_repo.get_aggregate_stats(start_dt, end_dt)
    
    # Fetch feedback stats
    feedback_stats = await feedback_repo.get_feedback_stats(start_dt, end_dt)
    
    # Get current user ID from request state (set by auth middleware)
    current_user = getattr(request.state, "user", None)
    current_user_id = current_user.user_id if current_user else None
    
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "stats": aggregate_stats,
            "top_users": top_users,
            "user_emails": user_emails,
            "top_tools": top_tools,
            "top_models": sorted_models,
            "guardrail_stats": guardrail_stats,
            "feedback_stats": feedback_stats,
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
    
    # Fetch aggregate stats
    aggregate_stats = await repository.get_aggregate_stats(start_dt, end_dt)
    
    # Fetch model breakdown
    model_stats = await repository.get_stats_by_model(start_dt, end_dt)
    
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
    - Search functionality for filtering users
    - Users sorted by total tokens descending
    
    Requirements: 4.1, 4.3, 4.4
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository
    repository = UsageRepository()
    
    # Fetch user stats (with optional search)
    if search and search.strip():
        user_stats = await repository.search_users(search.strip(), start_dt, end_dt)
    else:
        user_stats = await repository.get_stats_by_user(start_dt, end_dt)
    
    # Fetch user emails from Cognito
    user_ids = [user.user_id for user in user_stats]
    user_emails = await get_user_emails_by_ids(user_ids)
    
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
    
    Requirements: 4.2
    """
    # Initialize repository and cost calculator
    repository = UsageRepository()
    cost_calculator = CostCalculator()
    
    # Fetch all records for this session using GSI
    records = await repository.get_session_records(session_id)
    
    if not records:
        return templates.TemplateResponse(
            "admin/session_detail.html",
            {
                "request": request,
                "session_id": session_id,
                "session_stats": None,
                "records": [],
                "tool_usage": [],
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
    
    # Calculate total cost
    total_cost = sum(
        cost_calculator.calculate_cost(r.input_tokens, r.output_tokens, r.model_id)
        for r in records
    )
    
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
    - Cost breakdown
    - Invocation history
    
    Requirements: 4.1, 4.2
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Initialize repository and cost calculator
    repository = UsageRepository()
    cost_calculator = CostCalculator()
    
    # Fetch user stats
    user_stats = await repository.get_user_detail(user_id, start_dt, end_dt)
    
    # Fetch all records for this user to get session details
    all_records = await repository.get_all_records(start_dt, end_dt)
    user_records = [r for r in all_records if r.user_id == user_id]
    
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
        session["total_cost"] += cost_calculator.calculate_cost(
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
    
    return templates.TemplateResponse(
        "admin/user_detail.html",
        {
            "request": request,
            "user_id": user_id,
            "user_email": user_email,
            "user_stats": user_stats,
            "sessions": sorted_sessions,
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
