"""App settings routes for managing application configuration.

This module provides admin routes for managing app-wide settings like
title, subtitle, logo image, and theme colors.
"""

import logging
import base64
import re
from typing import Optional

from fastapi import APIRouter, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.storage.app_settings import AppSettingsStorageService
from app.templates_config import templates, init_template_globals
from app.helpers.settings import (
    COLOR_PRESETS,
    DEFAULT_APP_TITLE,
    DEFAULT_APP_SUBTITLE,
    DEFAULT_LOGO_URL,
    DEFAULT_CHAT_LOGO_URL,
    DEFAULT_WELCOME_MESSAGE,
    DEFAULT_PRIMARY_COLOR,
    DEFAULT_SECONDARY_COLOR,
)

logger = logging.getLogger(__name__)

# Admin router for settings management
admin_router = APIRouter(prefix="/admin", tags=["admin-settings"])

# API router for fetching settings
api_router = APIRouter(prefix="/api", tags=["settings"])


def is_valid_hex_color(color: str) -> bool:
    """Validate hex color format.
    
    Args:
        color: Color string to validate
        
    Returns:
        True if valid hex color, False otherwise
    """
    if not color:
        return False
    pattern = r'^#[0-9A-Fa-f]{6}$'
    return bool(re.match(pattern, color))


@admin_router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request):
    """Admin page for managing app settings.
    
    Displays:
    - App title and subtitle configuration
    - Logo image upload
    - Other extensible settings
    """
    from app.helpers import get_app_settings
    app_settings = await get_app_settings()
    
    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            **app_settings,
            # Header component context
            "breadcrumbs": [
                {"label": "Admin", "url": "/admin"},
                {"label": "Settings", "url": None},
            ],
            "primary_action": {"type": "back_to_chat"},
            "show_admin_btn": False,
        },
    )


@admin_router.post("/settings/update")
async def update_settings(
    request: Request,
    app_title: str = Form(...),
    app_subtitle: str = Form(...),
    welcome_message: str = Form(...),
    logo_file: Optional[UploadFile] = File(None),
    chat_logo_file: Optional[UploadFile] = File(None),
    reset_header_logo: str = Form("false"),
    reset_chat_logo: str = Form("false"),
    primary_color: str = Form(DEFAULT_PRIMARY_COLOR),
    secondary_color: str = Form(DEFAULT_SECONDARY_COLOR),
    reset_colors: str = Form("false"),
    active_tab: str = Form("branding"),
) -> RedirectResponse:
    """Update app settings.
    
    Args:
        request: Incoming request
        app_title: New app title
        app_subtitle: New app subtitle
        welcome_message: Welcome message shown in empty chat state
        logo_file: Optional logo image file
        chat_logo_file: Optional chat placeholder logo file
        reset_header_logo: Whether to reset header logo to default
        reset_chat_logo: Whether to reset chat logo to default
        primary_color: Primary theme color (hex)
        secondary_color: Secondary theme color (hex)
        reset_colors: Whether to reset colors to default
        active_tab: Current active tab to return to after save
        
    Returns:
        Redirect to admin settings page with active tab preserved
    """
    storage = AppSettingsStorageService()
    
    # Update title
    app_title = app_title.strip()
    if app_title:
        await storage.update_setting(
            setting_key="app_title",
            setting_value=app_title,
            setting_type="text",
            description="Application title displayed in header",
        )
        logger.info("Updated app title", extra={"value": app_title})
    
    # Update subtitle
    app_subtitle = app_subtitle.strip()
    if app_subtitle:
        await storage.update_setting(
            setting_key="app_subtitle",
            setting_value=app_subtitle,
            setting_type="text",
            description="Application subtitle displayed in header",
        )
        logger.info("Updated app subtitle", extra={"value": app_subtitle})
    
    # Update welcome message
    welcome_message = welcome_message.strip()
    if welcome_message:
        await storage.update_setting(
            setting_key="welcome_message",
            setting_value=welcome_message,
            setting_type="text",
            description="Welcome message shown in empty chat state",
        )
        logger.info("Updated welcome message", extra={"value": welcome_message})
    
    # Handle color reset
    if reset_colors == "true":
        await storage.update_setting(
            setting_key="primary_color",
            setting_value=DEFAULT_PRIMARY_COLOR,
            setting_type="color",
            description="Primary theme color",
        )
        await storage.update_setting(
            setting_key="secondary_color",
            setting_value=DEFAULT_SECONDARY_COLOR,
            setting_type="color",
            description="Secondary theme color",
        )
        logger.info("Reset theme colors to default")
    else:
        # Update primary color
        primary_color = primary_color.strip()
        if primary_color and is_valid_hex_color(primary_color):
            await storage.update_setting(
                setting_key="primary_color",
                setting_value=primary_color,
                setting_type="color",
                description="Primary theme color",
            )
            logger.info("Updated primary color", extra={"value": primary_color})
        
        # Update secondary color
        secondary_color = secondary_color.strip()
        if secondary_color and is_valid_hex_color(secondary_color):
            await storage.update_setting(
                setting_key="secondary_color",
                setting_value=secondary_color,
                setting_type="color",
                description="Secondary theme color",
            )
            logger.info("Updated secondary color", extra={"value": secondary_color})
    
    # Handle header logo reset
    if reset_header_logo == "true":
        await storage.update_setting(
            setting_key="logo_url",
            setting_value=DEFAULT_LOGO_URL,
            setting_type="image",
            description="Application logo displayed in header",
        )
        logger.info("Reset header logo to default")
    
    # Handle header logo upload
    if logo_file and logo_file.filename:
        try:
            # Validate file type
            allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "image/webp"]
            if logo_file.content_type not in allowed_types:
                logger.warning(
                    "Invalid logo file type",
                    extra={"content_type": logo_file.content_type, "filename": logo_file.filename},
                )
                return RedirectResponse(url="/admin/settings?error=invalid_type", status_code=303)
            
            # Read file content
            content = await logo_file.read()
            
            # Check file size (max 5MB)
            if len(content) > 5 * 1024 * 1024:
                logger.warning(
                    "Logo file too large",
                    extra={"filename": logo_file.filename, "size": len(content)},
                )
                return RedirectResponse(url="/admin/settings?error=file_too_large", status_code=303)
            
            # Encode as base64 data URL
            base64_content = base64.b64encode(content).decode("utf-8")
            data_url = f"data:{logo_file.content_type};base64,{base64_content}"
            
            await storage.update_setting(
                setting_key="logo_url",
                setting_value=data_url,
                setting_type="image",
                description="Application logo displayed in header",
            )
            logger.info(
                "Updated header logo image",
                extra={"filename": logo_file.filename, "size": len(content)},
            )
        except Exception as e:
            logger.error(
                "Failed to update header logo",
                extra={"filename": logo_file.filename, "error": str(e)},
                exc_info=True,
            )
            return RedirectResponse(url="/admin/settings?error=upload_failed", status_code=303)
    
    # Handle chat placeholder logo upload
    if chat_logo_file and chat_logo_file.filename:
        try:
            # Validate file type
            allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "image/webp"]
            if chat_logo_file.content_type not in allowed_types:
                logger.warning(
                    "Invalid chat logo file type",
                    extra={"content_type": chat_logo_file.content_type, "filename": chat_logo_file.filename},
                )
                return RedirectResponse(url="/admin/settings?error=invalid_type", status_code=303)
            
            # Read file content
            content = await chat_logo_file.read()
            
            # Check file size (max 5MB)
            if len(content) > 5 * 1024 * 1024:
                logger.warning(
                    "Chat logo file too large",
                    extra={"filename": chat_logo_file.filename, "size": len(content)},
                )
                return RedirectResponse(url="/admin/settings?error=file_too_large", status_code=303)
            
            # Encode as base64 data URL
            base64_content = base64.b64encode(content).decode("utf-8")
            data_url = f"data:{chat_logo_file.content_type};base64,{base64_content}"
            
            await storage.update_setting(
                setting_key="chat_logo_url",
                setting_value=data_url,
                setting_type="image",
                description="Chat placeholder logo displayed in empty chat screen",
            )
            logger.info(
                "Updated chat placeholder logo image",
                extra={"filename": chat_logo_file.filename, "size": len(content)},
            )
        except Exception as e:
            logger.error(
                "Failed to update chat logo",
                extra={"filename": chat_logo_file.filename, "error": str(e)},
                exc_info=True,
            )
            return RedirectResponse(url="/admin/settings?error=upload_failed", status_code=303)
    
    # Handle chat logo reset
    if reset_chat_logo == "true":
        await storage.update_setting(
            setting_key="chat_logo_url",
            setting_value=DEFAULT_CHAT_LOGO_URL,
            setting_type="image",
            description="Chat placeholder logo displayed in empty chat screen",
        )
        logger.info("Reset chat logo to default")
    
    # Refresh template globals with updated settings
    await init_template_globals()
    logger.info("Refreshed template globals after settings update")
    
    # Preserve active tab in redirect
    allowed_tabs = {"branding", "icons", "colors"}
    safe_active_tab = active_tab if active_tab in allowed_tabs else "branding"
    redirect_url = f"/admin/settings?tab={safe_active_tab}"
    return RedirectResponse(url=redirect_url, status_code=303)


@api_router.get("/settings")
async def get_settings() -> JSONResponse:
    """Get all app settings as JSON.
    
    Returns:
        JSON object with all settings
    """
    from app.helpers import get_app_settings
    app_settings = await get_app_settings()
    
    return JSONResponse(content=app_settings)
