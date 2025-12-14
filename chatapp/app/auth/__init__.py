"""Authentication module for HTMX ChatApp.

This module provides Cognito OAuth integration, JWT validation,
and authentication middleware for the application.
"""

from app.auth.cognito import (
    CognitoAuth,
    TokenResponse,
    UserInfo,
    AuthenticationError,
    TokenExpiredError,
    TokenValidationError,
    extract_user_id,
)
from app.auth.middleware import (
    AuthMiddleware,
    SESSION_COOKIE_NAME,
    get_current_user,
    get_session_data,
)

__all__ = [
    "CognitoAuth",
    "TokenResponse",
    "UserInfo",
    "AuthenticationError",
    "TokenExpiredError",
    "TokenValidationError",
    "extract_user_id",
    "AuthMiddleware",
    "SESSION_COOKIE_NAME",
    "get_current_user",
    "get_session_data",
]
