"""Prompt templates API routes for managing reusable prompts.

This module provides API endpoints for listing prompt templates (for chat UI)
and admin routes for CRUD operations on templates stored in DynamoDB.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.storage.prompt_template import PromptTemplateStorageService
from app.templates_config import templates

logger = logging.getLogger(__name__)

# API router for chat UI
router = APIRouter(prefix="/api", tags=["templates"])

# Admin router for template management
admin_router = APIRouter(prefix="/admin", tags=["admin-templates"])


# ============================================================================
# API Routes (for Chat UI)
# ============================================================================


@router.get("/templates")
async def list_templates() -> JSONResponse:
    """List all prompt templates for the chat UI.
    
    Returns all templates with their title, description, and prompt_detail
    for display in the templates dropdown.
    
    Returns:
        JSON array of template objects
        
    Requirements: 1.2
    """
    storage = PromptTemplateStorageService()
    templates_list = await storage.get_all_templates()
    
    # Convert to list of dicts for JSON response
    result = [t.to_dict() for t in templates_list]
    
    logger.info(
        "Listed templates for chat UI",
        extra={"count": len(result)},
    )
    
    return JSONResponse(content=result)


# ============================================================================
# Admin Routes (for Template Management)
# ============================================================================


@admin_router.get("/templates", response_class=HTMLResponse)
async def admin_templates_page(request: Request):
    """Admin page displaying all prompt templates.
    
    Displays:
    - Table with all templates (title, description, prompt_detail)
    - Create form for new templates
    - Edit/Delete actions per row
    
    Requirements: 2.1, 2.2
    """
    storage = PromptTemplateStorageService()
    templates_list = await storage.get_all_templates()
    
    # Sort by title for consistent display
    templates_list.sort(key=lambda t: t.title.lower())
    
    return templates.TemplateResponse(
        "admin/templates.html",
        {
            "request": request,
            "templates": templates_list,
        },
    )


@admin_router.post("/templates/create")
async def create_template(
    request: Request,
    title: str = Form(...),
    description: str = Form(...),
    prompt_detail: str = Form(...),
) -> RedirectResponse:
    """Create a new prompt template.
    
    Args:
        request: Incoming request
        title: Display title for the template
        description: Brief description
        prompt_detail: The actual prompt text
        
    Returns:
        Redirect to admin templates page
        
    Requirements: 2.3
    """
    # Validate inputs
    title = title.strip()
    description = description.strip()
    prompt_detail = prompt_detail.strip()
    
    if not title or not description or not prompt_detail:
        logger.warning("Create template failed: missing required fields")
        # Redirect back with error (could enhance with flash messages)
        return RedirectResponse(url="/admin/templates", status_code=303)
    
    storage = PromptTemplateStorageService()
    template = await storage.create_template(
        title=title,
        description=description,
        prompt_detail=prompt_detail,
    )
    
    if template:
        logger.info(
            "Admin created template",
            extra={"template_id": template.template_id, "title": title},
        )
    else:
        logger.error("Failed to create template", extra={"title": title})
    
    return RedirectResponse(url="/admin/templates", status_code=303)


@admin_router.post("/templates/{template_id}/edit")
async def edit_template(
    request: Request,
    template_id: str,
    title: str = Form(...),
    description: str = Form(...),
    prompt_detail: str = Form(...),
) -> RedirectResponse:
    """Update an existing prompt template.
    
    Args:
        request: Incoming request
        template_id: The template ID to update
        title: New display title
        description: New description
        prompt_detail: New prompt text
        
    Returns:
        Redirect to admin templates page
        
    Requirements: 2.4
    """
    # Validate inputs
    title = title.strip()
    description = description.strip()
    prompt_detail = prompt_detail.strip()
    
    if not title or not description or not prompt_detail:
        logger.warning(
            "Edit template failed: missing required fields",
            extra={"template_id": template_id},
        )
        return RedirectResponse(url="/admin/templates", status_code=303)
    
    storage = PromptTemplateStorageService()
    template = await storage.update_template(
        template_id=template_id,
        title=title,
        description=description,
        prompt_detail=prompt_detail,
    )
    
    if template:
        logger.info(
            "Admin updated template",
            extra={"template_id": template_id, "title": title},
        )
    else:
        logger.warning(
            "Template not found for update",
            extra={"template_id": template_id},
        )
    
    return RedirectResponse(url="/admin/templates", status_code=303)


@admin_router.post("/templates/{template_id}/delete")
async def delete_template(
    request: Request,
    template_id: str,
) -> RedirectResponse:
    """Delete a prompt template.
    
    Args:
        request: Incoming request
        template_id: The template ID to delete
        
    Returns:
        Redirect to admin templates page
        
    Requirements: 2.5
    """
    storage = PromptTemplateStorageService()
    success = await storage.delete_template(template_id)
    
    if success:
        logger.info(
            "Admin deleted template",
            extra={"template_id": template_id},
        )
    else:
        logger.warning(
            "Failed to delete template",
            extra={"template_id": template_id},
        )
    
    return RedirectResponse(url="/admin/templates", status_code=303)
