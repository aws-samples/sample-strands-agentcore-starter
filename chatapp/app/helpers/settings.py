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

# Default theme colors (purple theme)
DEFAULT_PRIMARY_COLOR = "#7c3aed"  # Purple 600
DEFAULT_SECONDARY_COLOR = "#6b21a8"  # Purple 800

# Preset color themes
COLOR_PRESETS = {
    # Monochromatic themes
    "purple": {"primary": "#7c3aed", "secondary": "#6b21a8", "name": "Purple (Default)"},
    "blue": {"primary": "#2563eb", "secondary": "#1e40af", "name": "Blue"},
    "green": {"primary": "#16a34a", "secondary": "#166534", "name": "Green"},
    "red": {"primary": "#dc2626", "secondary": "#991b1b", "name": "Red"},
    "orange": {"primary": "#ea580c", "secondary": "#c2410c", "name": "Orange"},
    "teal": {"primary": "#0d9488", "secondary": "#0f766e", "name": "Teal"},
    "pink": {"primary": "#db2777", "secondary": "#be185d", "name": "Pink"},
    "indigo": {"primary": "#4f46e5", "secondary": "#3730a3", "name": "Indigo"},
    # Complementary color combos
    "ocean_sunset": {"primary": "#0ea5e9", "secondary": "#f97316", "name": "Ocean Sunset"},
    "forest_berry": {"primary": "#22c55e", "secondary": "#e11d48", "name": "Forest Berry"},
    "royal_gold": {"primary": "#6366f1", "secondary": "#eab308", "name": "Royal Gold"},
    "coral_teal": {"primary": "#f43f5e", "secondary": "#14b8a6", "name": "Coral Teal"},
    # Split-complementary combos
    "twilight": {"primary": "#8b5cf6", "secondary": "#06b6d4", "name": "Twilight"},
    "autumn": {"primary": "#f59e0b", "secondary": "#7c3aed", "name": "Autumn"},
    "spring": {"primary": "#84cc16", "secondary": "#ec4899", "name": "Spring"},
    # Analogous (harmonious neighbors)
    "sunset_glow": {"primary": "#f97316", "secondary": "#ec4899", "name": "Sunset Glow"},
    "ocean_breeze": {"primary": "#06b6d4", "secondary": "#3b82f6", "name": "Ocean Breeze"},
    "mint_lime": {"primary": "#10b981", "secondary": "#84cc16", "name": "Mint Lime"},
}


def hex_to_rgb(hex_color: str) -> str:
    """Convert hex color to RGB values string.
    
    Args:
        hex_color: Hex color string (e.g., '#7c3aed')
        
    Returns:
        RGB values as comma-separated string (e.g., '124, 58, 237')
    """
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"{r}, {g}, {b}"


def generate_color_palette(hex_color: str) -> Dict[str, str]:
    """Generate a Tailwind-style color palette from a base color.
    
    Creates shades from 50 (lightest) to 900 (darkest) based on the input color.
    The input color is used as the 600 shade.
    
    Args:
        hex_color: Base hex color (used as 600 shade)
        
    Returns:
        Dictionary with shade keys (50, 100, ..., 900) and hex values
    """
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    
    # Generate palette by adjusting lightness
    palette = {}
    
    # Lighter shades (mix with white)
    light_factors = {
        50: 0.95,
        100: 0.9,
        200: 0.8,
        300: 0.6,
        400: 0.4,
        500: 0.2,
    }
    
    for shade, factor in light_factors.items():
        new_r = int(r + (255 - r) * factor)
        new_g = int(g + (255 - g) * factor)
        new_b = int(b + (255 - b) * factor)
        palette[str(shade)] = f"#{new_r:02x}{new_g:02x}{new_b:02x}"
    
    # Base color as 600
    palette["600"] = f"#{hex_color}"
    
    # Darker shades (mix with black)
    dark_factors = {
        700: 0.2,
        800: 0.35,
        900: 0.5,
    }
    
    for shade, factor in dark_factors.items():
        new_r = int(r * (1 - factor))
        new_g = int(g * (1 - factor))
        new_b = int(b * (1 - factor))
        palette[str(shade)] = f"#{new_r:02x}{new_g:02x}{new_b:02x}"
    
    return palette


async def get_app_settings() -> Dict[str, Any]:
    """Load app settings from DynamoDB with defaults.
    
    Returns:
        Dictionary with app_title, app_subtitle, logo_url, chat_logo_url,
        and theme color settings with generated palettes
    """
    storage = AppSettingsStorageService()
    settings = await storage.get_all_settings()
    
    # Get base colors
    primary_color = settings.get("primary_color").setting_value if "primary_color" in settings else DEFAULT_PRIMARY_COLOR
    secondary_color = settings.get("secondary_color").setting_value if "secondary_color" in settings else DEFAULT_SECONDARY_COLOR
    
    # Generate color palettes
    primary_palette = generate_color_palette(primary_color)
    secondary_palette = generate_color_palette(secondary_color)
    
    return {
        "app_title": settings.get("app_title").setting_value if "app_title" in settings else DEFAULT_APP_TITLE,
        "app_subtitle": settings.get("app_subtitle").setting_value if "app_subtitle" in settings else DEFAULT_APP_SUBTITLE,
        "logo_url": settings.get("logo_url").setting_value if "logo_url" in settings else DEFAULT_LOGO_URL,
        "chat_logo_url": settings.get("chat_logo_url").setting_value if "chat_logo_url" in settings else DEFAULT_CHAT_LOGO_URL,
        # Theme colors
        "primary_color": primary_color,
        "secondary_color": secondary_color,
        "primary_rgb": hex_to_rgb(primary_color),
        "secondary_rgb": hex_to_rgb(secondary_color),
        "primary_palette": primary_palette,
        "secondary_palette": secondary_palette,
        "color_presets": COLOR_PRESETS,
    }
