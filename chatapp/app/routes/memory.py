"""Memory API routes for HTMX ChatApp.

This module provides endpoints for fetching event and semantic memory
from AgentCore Memory service.
"""

import json
from dataclasses import asdict
from typing import List
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse

from app.auth.cognito import extract_user_id, TokenValidationError
from app.auth.middleware import SESSION_COOKIE_NAME
from app.agentcore.memory import MemoryClient, MemoryEvent, SemanticFact


router = APIRouter(prefix="/api/memory", tags=["memory"])


def _get_user_id_from_session(request: Request) -> str:
    """Extract user ID from session cookie or dev mode.
    
    Args:
        request: Incoming request with session cookie
        
    Returns:
        User ID extracted from JWT token or dev mode config
        
    Raises:
        HTTPException: If session is invalid or user ID cannot be extracted
    """
    # Check for dev mode user from middleware
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "user_id"):
        return user.user_id
    
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
        return extract_user_id(id_token)
    except TokenValidationError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


@router.get("/events")
async def get_event_memory(
    request: Request,
    session_id: str = Query(..., description="Session ID for the conversation"),
):
    """Get event memory (conversation history) for a session.
    
    Fetches the conversation history from AgentCore Memory for the specified
    session. Returns messages with role, content, and timestamp.
    
    Args:
        request: Incoming request with session cookie
        session_id: Session ID for the conversation
        
    Returns:
        JSON response with messages array
    """
    # Extract user ID from session
    user_id = _get_user_id_from_session(request)
    
    # Validate session_id
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    
    # Fetch event memory
    client = MemoryClient()
    events: List[MemoryEvent] = await client.get_events(
        session_id=session_id,
        user_id=user_id,
    )
    
    # Convert to response format
    messages = [
        {
            "role": event.role,
            "content": event.content,
            "timestamp": event.timestamp,
        }
        for event in events
    ]
    
    return JSONResponse(
        content={
            "messages": messages,
            "sessionId": session_id,
            "totalCount": len(messages),
        }
    )


@router.get("/semantic")
async def get_semantic_memory(
    request: Request,
    session_id: str = Query(..., description="Session ID for the conversation"),
    type: str = Query("facts", description="Type of semantic memory: facts, summaries, or preferences"),
):
    """Get semantic memory (facts/summaries/preferences) for a session.
    
    Fetches semantic memory records from AgentCore Memory for the specified
    session and type. Returns items with content and timestamp.
    
    Args:
        request: Incoming request with session cookie
        session_id: Session ID for the conversation
        type: Type of semantic memory (facts, summaries, preferences)
        
    Returns:
        JSON response with items array for the requested type
    """
    # Extract user ID from session
    user_id = _get_user_id_from_session(request)
    
    # Validate session_id
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")
    
    # Validate and normalize type
    valid_types = {"facts", "summaries", "preferences"}
    memory_type = type.lower() if type else "facts"
    if memory_type not in valid_types:
        memory_type = "facts"
    
    # Fetch semantic memory for the specified type
    client = MemoryClient()
    items: List[SemanticFact] = await client.get_semantic(
        session_id=session_id,
        user_id=user_id,
        memory_type=memory_type,
    )
    
    # Convert to response format
    item_list = [
        {
            "id": item.fact_id,
            "content": item.content,
            "confidence": item.confidence,
            "createdAt": item.timestamp,
        }
        for item in items
    ]
    
    # Return with the appropriate key based on type
    # Include the items under both the type-specific key and a generic key for frontend compatibility
    return JSONResponse(
        content={
            memory_type: item_list,
            "items": item_list,  # Generic key for frontend
            "sessionId": session_id,
            "type": memory_type,
            "count": len(item_list),
        }
    )


@router.get("/debug")
async def debug_memory(
    request: Request,
    session_id: str = Query(..., description="Session ID for the conversation"),
):
    """Debug endpoint to inspect memory namespaces and contents.
    
    Tries multiple namespace formats to find where semantic data is stored.
    
    Args:
        request: Incoming request with session cookie
        session_id: Session ID for the conversation
        
    Returns:
        JSON response with debug information about memory contents
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Extract user ID from session
    user_id = _get_user_id_from_session(request)
    
    client = MemoryClient()
    results = {}
    
    # Try various namespace formats to find where data is stored
    namespace_formats = {
        # Current format (matching frontend)
        "facts_v1": f"/users/{user_id}/facts",
        "summaries_v1": f"/summaries/{user_id}/{session_id}",
        "preferences_v1": f"/users/{user_id}/preferences",
        # Alternative formats
        "facts_v2": f"users/{user_id}/facts",
        "summaries_v2": f"summaries/{user_id}/{session_id}",
        "preferences_v2": f"users/{user_id}/preferences",
        # Session-scoped formats
        "facts_session": f"/sessions/{session_id}/facts",
        "summaries_session": f"/sessions/{session_id}/summaries",
        "preferences_session": f"/sessions/{session_id}/preferences",
        # User-only formats
        "facts_user": f"/{user_id}/facts",
        "summaries_user": f"/{user_id}/summaries",
        "preferences_user": f"/{user_id}/preferences",
        # Root namespace
        "root": "/",
    }
    
    for name, namespace in namespace_formats.items():
        try:
            response = client._client.list_memory_records(
                memoryId=client.memory_id,
                namespace=namespace,
                maxResults=10,
            )
            record_count = len(response.get('memoryRecordSummaries', []))
            records = []
            for record in response.get('memoryRecordSummaries', [])[:3]:
                content = record.get('content', {}).get('text', '')[:100]
                records.append({
                    "id": record.get('memoryRecordId', '')[:20],
                    "content_preview": content,
                })
            results[name] = {
                "namespace": namespace,
                "count": record_count,
                "sample_records": records,
            }
        except Exception as e:
            results[name] = {
                "namespace": namespace,
                "error": str(e)[:100],
            }
    
    return JSONResponse(
        content={
            "user_id": user_id,
            "session_id": session_id,
            "memory_id": client.memory_id,
            "namespaces": results,
        }
    )


@router.options("/events")
async def events_options():
    """CORS preflight handler for events endpoint.
    
    Returns:
        Empty response with CORS headers
    """
    return JSONResponse(
        content=None,
        status_code=204,
        headers={
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
    )


@router.options("/semantic")
async def semantic_options():
    """CORS preflight handler for semantic endpoint.
    
    Returns:
        Empty response with CORS headers
    """
    return JSONResponse(
        content=None,
        status_code=204,
        headers={
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
    )
