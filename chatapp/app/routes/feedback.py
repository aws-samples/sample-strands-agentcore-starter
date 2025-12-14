"""Feedback API routes for user feedback on assistant responses.

This module provides the API endpoint for submitting user feedback
on assistant responses. Feedback is stored in DynamoDB for analysis.
It also provides admin routes for viewing and filtering feedback records.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, field_validator
from pathlib import Path

from app.models.feedback import FeedbackRecord, FeedbackSubmission, FeedbackStats
from app.storage.feedback import FeedbackStorageService
from app.admin.feedback_repository import FeedbackRepository
from app.auth.cognito import get_user_emails_by_ids

logger = logging.getLogger(__name__)

# Set up templates
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/api", tags=["feedback"])

# Create a separate router for admin routes (no prefix)
admin_router = APIRouter(tags=["admin-feedback"])


class FeedbackRequest(BaseModel):
    """Request body for feedback submission endpoint.
    
    Attributes:
        message_id: Unique identifier for the rated message
        session_id: Conversation session identifier
        user_message: The user's original message/prompt
        assistant_response: The assistant's response that was rated
        tools_used: List of tool names used in the response
        sentiment: 'positive' or 'negative'
        user_comment: Optional comment explaining the rating
    """
    message_id: str = Field(..., min_length=1, description="Message ID")
    session_id: str = Field(..., min_length=1, description="Session ID")
    user_message: str = Field(..., min_length=1, description="User message")
    assistant_response: str = Field(..., min_length=1, description="Assistant response")
    tools_used: list[str] = Field(default_factory=list, description="Tools used")
    sentiment: str = Field(..., description="Sentiment: 'positive' or 'negative'")
    user_comment: Optional[str] = Field(default=None, description="Optional comment")
    
    @field_validator("sentiment")
    @classmethod
    def validate_sentiment(cls, v: str) -> str:
        """Validate sentiment is 'positive' or 'negative'.
        
        Args:
            v: Sentiment value to validate
            
        Returns:
            Validated sentiment value
            
        Raises:
            ValueError: If sentiment is not 'positive' or 'negative'
        """
        if v not in ("positive", "negative"):
            raise ValueError("sentiment must be 'positive' or 'negative'")
        return v


@router.post("/feedback")
async def submit_feedback(request: Request, body: FeedbackRequest) -> JSONResponse:
    """Submit user feedback for an assistant message.
    
    Extracts user_id from the authenticated request, validates the sentiment,
    and stores the feedback record in DynamoDB.
    
    Args:
        request: Incoming request with authenticated user
        body: Feedback submission data
        
    Returns:
        JSON response indicating success
        
    Raises:
        HTTPException: If user is not authenticated or validation fails
    """
    # Extract user_id from authenticated request
    user = getattr(request.state, "user", None)
    if not user or not hasattr(user, "user_id"):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    user_id = user.user_id
    
    # Create timestamp
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Create feedback record
    record = FeedbackRecord(
        user_id=user_id,
        timestamp=timestamp,
        session_id=body.session_id,
        message_id=body.message_id,
        user_message=body.user_message,
        assistant_response=body.assistant_response,
        tools_used=body.tools_used,
        sentiment=body.sentiment,
        user_comment=body.user_comment,
    )
    
    # Store feedback (fire-and-forget pattern)
    storage_service = FeedbackStorageService()
    await storage_service.store_feedback(record)
    
    logger.info(
        "Feedback submitted",
        extra={
            "user_id": user_id,
            "session_id": body.session_id,
            "message_id": body.message_id,
            "sentiment": body.sentiment,
        },
    )
    
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": "Feedback recorded",
            "message_id": body.message_id,
            "sentiment": body.sentiment,
        },
    )


# ============================================================================
# Admin Routes for Feedback
# ============================================================================


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
        end_time: ISO format end time string
        
    Returns:
        Tuple of (start_time, end_time) as datetime objects
    """
    if start_time and end_time:
        try:
            def parse_iso(s: str) -> datetime:
                # Remove Z suffix
                s = s.replace('Z', '')
                # Remove timezone offset if present
                if '+' in s:
                    s = s.split('+')[0]
                elif s.count('-') > 2:
                    parts = s.rsplit('-', 1)
                    if ':' in parts[-1]:
                        s = parts[0]
                return datetime.fromisoformat(s)
            
            return (parse_iso(start_time), parse_iso(end_time))
        except ValueError as e:
            logger.warning(f"Failed to parse time range: {e}")
    
    return _get_default_time_range()


@admin_router.get("/admin/feedback", response_class=HTMLResponse)
async def feedback_page(
    request: Request,
    sentiment: Optional[str] = Query(None, description="Filter by sentiment (positive/negative)"),
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
):
    """Admin page displaying feedback records.
    
    Displays:
    - Summary statistics (total, positive, negative, percentage)
    - Feedback records table with filtering
    - Expandable rows for full message content
    
    Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.2
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Validate sentiment filter
    sentiment_filter = None
    if sentiment and sentiment in ("positive", "negative"):
        sentiment_filter = sentiment
    
    # Initialize repository
    repository = FeedbackRepository()
    
    # Fetch feedback records with optional sentiment filter
    records = await repository.get_all_feedback(start_dt, end_dt, sentiment=sentiment_filter)
    
    # Fetch statistics (always unfiltered by sentiment for summary)
    stats = await repository.get_feedback_stats(start_dt, end_dt)
    
    # Fetch user emails for all unique user_ids
    user_ids = list(set(r.user_id for r in records))
    user_emails = await get_user_emails_by_ids(user_ids) if user_ids else {}
    
    return templates.TemplateResponse(
        "admin/feedback.html",
        {
            "request": request,
            "records": records,
            "stats": stats,
            "user_emails": user_emails,
            "sentiment_filter": sentiment_filter or "all",
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "days_in_period": days_in_period,
        },
    )


@admin_router.get("/admin/api/feedback")
async def api_feedback(
    sentiment: Optional[str] = Query(None, description="Filter by sentiment (positive/negative)"),
    start_time: Optional[str] = Query(None, description="Start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="End time (ISO format)"),
) -> Dict[str, Any]:
    """JSON API endpoint for feedback data.
    
    Returns feedback records and statistics as JSON for client-side updates.
    
    Requirements: 5.1, 5.3, 5.4, 6.1, 6.2
    """
    # Parse time range
    start_dt, end_dt = _parse_time_range(start_time, end_time)
    days_in_period = max(1, (end_dt - start_dt).days)
    
    # Validate sentiment filter
    sentiment_filter = None
    if sentiment and sentiment in ("positive", "negative"):
        sentiment_filter = sentiment
    
    # Initialize repository
    repository = FeedbackRepository()
    
    # Fetch feedback records
    records = await repository.get_all_feedback(start_dt, end_dt, sentiment=sentiment_filter)
    
    # Fetch statistics
    stats = await repository.get_feedback_stats(start_dt, end_dt)
    
    # Fetch user emails
    user_ids = list(set(r.user_id for r in records))
    user_emails = await get_user_emails_by_ids(user_ids) if user_ids else {}
    
    # Convert records to dictionaries with user emails
    records_data = []
    for record in records:
        record_dict = record.to_dict()
        record_dict["user_email"] = user_emails.get(record.user_id)
        records_data.append(record_dict)
    
    return {
        "records": records_data,
        "stats": stats.to_dict(),
        "sentiment_filter": sentiment_filter or "all",
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "days_in_period": days_in_period,
    }
