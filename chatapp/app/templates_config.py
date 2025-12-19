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

# Default color settings
DEFAULT_PRIMARY_COLOR = "#7c3aed"
DEFAULT_SECONDARY_COLOR = "#6b21a8"
DEFAULT_PRIMARY_RGB = "124, 58, 237"
DEFAULT_SECONDARY_RGB = "107, 33, 168"
DEFAULT_PRIMARY_PALETTE = {
    "50": "#f5f3ff", "100": "#ede9fe", "200": "#ddd6fe", "300": "#c4b5fd",
    "400": "#a78bfa", "500": "#8b5cf6", "600": "#7c3aed", "700": "#6d28d9",
    "800": "#5b21b6", "900": "#4c1d95"
}


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
        print(f"✓ Loaded app settings into templates: {settings.get('app_title')}, primary_color: {settings.get('primary_color')}")
    except Exception as e:
        print(f"Warning: Could not load app settings: {e}")
        # Set defaults including color settings
        templates.env.globals.update({
            "app_title": "Chat Agent",
            "app_subtitle": "Bedrock AgentCore + Strands Agents SDK",
            "logo_url": "/static/favicon.svg",
            "chat_logo_url": "/static/chat-placeholder.svg",
            "primary_color": DEFAULT_PRIMARY_COLOR,
            "secondary_color": DEFAULT_SECONDARY_COLOR,
            "primary_rgb": DEFAULT_PRIMARY_RGB,
            "secondary_rgb": DEFAULT_SECONDARY_RGB,
            "primary_palette": DEFAULT_PRIMARY_PALETTE,
            "secondary_palette": DEFAULT_PRIMARY_PALETTE,
            "color_presets": {},
        })
