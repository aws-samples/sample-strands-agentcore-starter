"""Session management module for HTMX ChatApp.

This module provides session management functionality including
session ID generation, storage, and retrieval using secure HTTP-only cookies.
"""

from app.session.manager import (
    SessionManager,
    ChatSession,
    CHAT_SESSION_COOKIE_NAME,
    create_session,
    get_session,
    clear_session,
)

__all__ = [
    "SessionManager",
    "ChatSession",
    "CHAT_SESSION_COOKIE_NAME",
    "create_session",
    "get_session",
    "clear_session",
]
