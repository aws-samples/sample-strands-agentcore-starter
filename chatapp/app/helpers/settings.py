"""Helper functions for loading app settings.

This module provides utilities for loading app settings from DynamoDB
with default fallbacks for use in templates.
"""

from typing import Dict, Any
from app.storage.app_settings import AppSettingsStorageService


# Default values
DEFAULT_APP_TITLE = "Chat Agent"
DEFAULT_APP_SUBTITLE = "Bedrock AgentCore + Strands Agents SDK"
DEFAULT_LOGO_URL = "/static/favicon.svg"
DEFAULT_CHAT_LOGO_URL = "/static/chat-placeholder.svg"


async def get_app_settings() -> Dict[str, Any]:
    """Load app settings from DynamoDB with defaults.
    
    Returns:
        Dictionary with app_title, app_subtitle, logo_url, and chat_logo_url
    """
    storage = AppSettingsStorageService()
    settings = await storage.get_all_settings()
    
    return {
        "app_title": settings.get("app_title").setting_value if "app_title" in settings else DEFAULT_APP_TITLE,
        "app_subtitle": settings.get("app_subtitle").setting_value if "app_subtitle" in settings else DEFAULT_APP_SUBTITLE,
        "logo_url": settings.get("logo_url").setting_value if "logo_url" in settings else DEFAULT_LOGO_URL,
        "chat_logo_url": settings.get("chat_logo_url").setting_value if "chat_logo_url" in settings else DEFAULT_CHAT_LOGO_URL,
    }
