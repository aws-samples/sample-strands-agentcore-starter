"""Shared Jinja2 templates configuration.

This module provides a centralized templates instance with app settings
injected as global variables, ensuring consistent branding across all pages.
"""

import asyncio
from pathlib import Path
from fastapi.templating import Jinja2Templates

# Set up templates directory
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

# Create shared templates instance
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def init_template_globals():
    """Initialize template global variables with app settings.
    
    This should be called once at application startup to load settings
    into the Jinja2 environment globals.
    """
    from app.helpers import get_app_settings
    
    try:
        # Load settings asynchronously at startup
        settings = await get_app_settings()
        templates.env.globals.update(settings)
        print(f"✓ Loaded app settings into templates: {settings.get('app_title')}")
    except Exception as e:
        print(f"Warning: Could not load app settings: {e}")
        # Set defaults
        templates.env.globals.update({
            "app_title": "Chat Agent",
            "app_subtitle": "Bedrock AgentCore + Strands Agents SDK",
            "logo_url": "/static/favicon.svg",
            "chat_logo_url": "/static/chat-placeholder.svg",
        })
