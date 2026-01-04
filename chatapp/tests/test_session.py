"""Unit tests for session management."""

import json
import pytest
from unittest.mock import MagicMock
from app.session.manager import (
    SessionManager,
    ChatSession,
    CHAT_SESSION_COOKIE_NAME,
)


class TestChatSession:
    """Tests for ChatSession dataclass."""

    def test_to_dict(self):
        """Test serialization to dictionary."""
        session = ChatSession(
            session_id="sess-123",
            created_at="2025-01-03T10:00:00",
            last_activity="2025-01-03T11:00:00",
        )
        
        result = session.to_dict()
        
        assert result["session_id"] == "sess-123"
        assert result["created_at"] == "2025-01-03T10:00:00"
        assert result["last_activity"] == "2025-01-03T11:00:00"

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "session_id": "sess-456",
            "created_at": "2025-01-03T12:00:00",
            "last_activity": "2025-01-03T13:00:00",
        }
        
        session = ChatSession.from_dict(data)
        
        assert session.session_id == "sess-456"
        assert session.created_at == "2025-01-03T12:00:00"


class TestSessionManager:
    """Tests for SessionManager class."""

    def test_generate_session_id_is_uuid(self):
        """Test that generated session IDs are valid UUIDs."""
        manager = SessionManager()
        
        session_id = manager.generate_session_id()
        
        # UUID format: 8-4-4-4-12 hex chars
        parts = session_id.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8

    def test_generate_session_id_is_unique(self):
        """Test that generated session IDs are unique."""
        manager = SessionManager()
        
        ids = [manager.generate_session_id() for _ in range(100)]
        
        assert len(set(ids)) == 100

    def test_create_session_sets_cookie(self):
        """Test that create_session sets the session cookie."""
        manager = SessionManager()
        response = MagicMock()
        
        session = manager.create_session(response)
        
        response.set_cookie.assert_called_once()
        call_kwargs = response.set_cookie.call_args.kwargs
        assert call_kwargs["key"] == CHAT_SESSION_COOKIE_NAME
        assert call_kwargs["httponly"] is True

    def test_get_session_returns_none_without_cookie(self):
        """Test that get_session returns None when no cookie exists."""
        manager = SessionManager()
        request = MagicMock()
        request.cookies.get.return_value = None
        
        session = manager.get_session(request)
        
        assert session is None

    def test_get_session_parses_valid_cookie(self):
        """Test that get_session parses a valid session cookie."""
        manager = SessionManager()
        request = MagicMock()
        
        cookie_data = {
            "session_id": "sess-from-cookie",
            "created_at": "2025-01-03T10:00:00",
            "last_activity": "2025-01-03T11:00:00",
        }
        request.cookies.get.return_value = json.dumps(cookie_data)
        
        session = manager.get_session(request)
        
        assert session is not None
        assert session.session_id == "sess-from-cookie"

    def test_get_session_returns_none_for_invalid_json(self):
        """Test that get_session returns None for invalid JSON."""
        manager = SessionManager()
        request = MagicMock()
        request.cookies.get.return_value = "not-valid-json"
        
        session = manager.get_session(request)
        
        assert session is None

    def test_clear_session_deletes_cookie(self):
        """Test that clear_session deletes the cookie."""
        manager = SessionManager()
        response = MagicMock()
        
        manager.clear_session(response)
        
        response.delete_cookie.assert_called_once()
        call_kwargs = response.delete_cookie.call_args.kwargs
        assert call_kwargs["key"] == CHAT_SESSION_COOKIE_NAME
