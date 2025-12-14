"""Routes module for HTMX ChatApp.

This module contains all API route handlers organized by functionality.
"""

from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.memory import router as memory_router

__all__ = ["auth_router", "chat_router", "memory_router"]
