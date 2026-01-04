"""Session manager for HTMX ChatApp.

This module provides session management functionality for chat sessions,
including session ID generation, storage in secure HTTP-only cookies,
and session lifecycle management.

Requirements: 3.1, 3.2
"""

import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, UTC
from typing import Optional

from fastapi import Request, Response


# Cookie name for chat session (separate from auth session)
CHAT_SESSION_COOKIE_NAME = "chatapp_chat_session"


@dataclass
class ChatSession:
    """Represents a chat session state.
    
    Attributes:
        session_id: Unique identifier for the chat session (UUID)
        created_at: ISO timestamp when session was created
        last_activity: ISO timestamp of last activity
    """
    session_id: str
    created_at: str
    last_activity: str
    
    def to_dict(self) -> dict:
        """Convert session to dictionary for serialization.
        
        Returns:
            Dictionary representation of session
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        """Create session from dictionary.
        
        Args:
            data: Dictionary with session data
            
        Returns:
            ChatSession instance
        """
        return cls(
            session_id=data["session_id"],
            created_at=data["created_at"],
            last_activity=data["last_activity"],
        )


class SessionManager:
    """Manages chat session lifecycle.
    
    This class handles:
    - Generating unique session IDs (UUIDs)
    - Storing session state in secure HTTP-only cookies
    - Retrieving and validating session data
    - Clearing sessions
    
    Attributes:
        cookie_max_age: Maximum age of session cookie in seconds (default: 7 days)
        cookie_secure: Whether to set Secure flag on cookie (default: True)
        cookie_samesite: SameSite policy for cookie (default: "lax")
    """
    
    def __init__(
        self,
        cookie_max_age: int = 86400 * 7,  # 7 days
        cookie_secure: bool = True,
        cookie_samesite: str = "lax",
    ):
        """Initialize SessionManager.
        
        Args:
            cookie_max_age: Maximum age of session cookie in seconds
            cookie_secure: Whether to set Secure flag on cookie
            cookie_samesite: SameSite policy for cookie
        """
        self.cookie_max_age = cookie_max_age
        self.cookie_secure = cookie_secure
        self.cookie_samesite = cookie_samesite
    
    def generate_session_id(self) -> str:
        """Generate a new unique session ID.
        
        Returns:
            UUID string for session identification
        """
        return str(uuid.uuid4())
    
    def create_session(self, response: Response) -> ChatSession:
        """Create a new chat session and set cookie.
        
        Args:
            response: FastAPI response to set cookie on
            
        Returns:
            Newly created ChatSession
        """
        now = datetime.now(UTC).isoformat()
        session = ChatSession(
            session_id=self.generate_session_id(),
            created_at=now,
            last_activity=now,
        )
        
        self._set_session_cookie(response, session)
        return session
    
    def get_session(self, request: Request) -> Optional[ChatSession]:
        """Get existing session from request cookie.
        
        Args:
            request: FastAPI request with cookies
            
        Returns:
            ChatSession if valid session exists, None otherwise
        """
        cookie_value = request.cookies.get(CHAT_SESSION_COOKIE_NAME)
        if not cookie_value:
            return None
        
        try:
            data = json.loads(cookie_value)
            return ChatSession.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
    
    def get_or_create_session(
        self, request: Request, response: Response
    ) -> ChatSession:
        """Get existing session or create new one.
        
        Args:
            request: FastAPI request with cookies
            response: FastAPI response to set cookie on if creating
            
        Returns:
            Existing or newly created ChatSession
        """
        session = self.get_session(request)
        if session:
            # Update last activity
            session.last_activity = datetime.now(UTC).isoformat()
            self._set_session_cookie(response, session)
            return session
        
        return self.create_session(response)
    
    def clear_session(self, response: Response) -> None:
        """Clear the chat session cookie.
        
        Args:
            response: FastAPI response to clear cookie on
        """
        response.delete_cookie(
            key=CHAT_SESSION_COOKIE_NAME,
            path="/",
        )
    
    def update_session(
        self, request: Request, response: Response
    ) -> Optional[ChatSession]:
        """Update session's last activity timestamp.
        
        Args:
            request: FastAPI request with cookies
            response: FastAPI response to update cookie on
            
        Returns:
            Updated ChatSession or None if no session exists
        """
        session = self.get_session(request)
        if not session:
            return None
        
        session.last_activity = datetime.now(UTC).isoformat()
        self._set_session_cookie(response, session)
        return session
    
    def _set_session_cookie(
        self, response: Response, session: ChatSession
    ) -> None:
        """Set session cookie on response.
        
        Args:
            response: FastAPI response to set cookie on
            session: ChatSession to store
        """
        response.set_cookie(
            key=CHAT_SESSION_COOKIE_NAME,
            value=json.dumps(session.to_dict()),
            httponly=True,
            secure=self.cookie_secure,
            samesite=self.cookie_samesite,
            max_age=self.cookie_max_age,
            path="/",
        )


# Default session manager instance
_default_manager = SessionManager()


def create_session(response: Response) -> ChatSession:
    """Create a new chat session using default manager.
    
    Args:
        response: FastAPI response to set cookie on
        
    Returns:
        Newly created ChatSession
    """
    return _default_manager.create_session(response)


def get_session(request: Request) -> Optional[ChatSession]:
    """Get existing session using default manager.
    
    Args:
        request: FastAPI request with cookies
        
    Returns:
        ChatSession if valid session exists, None otherwise
    """
    return _default_manager.get_session(request)


def clear_session(response: Response) -> None:
    """Clear the chat session using default manager.
    
    Args:
        response: FastAPI response to clear cookie on
    """
    _default_manager.clear_session(response)
