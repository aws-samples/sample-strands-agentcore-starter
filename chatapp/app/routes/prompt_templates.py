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
    
    # Sort by sort_order so the chat UI reflects the admin-defined ordering
    templates_list.sort(key=lambda t: t.sort_order)
    
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
    
    # Sort by sort_order for consistent, drag-and-drop-defined display
    templates_list.sort(key=lambda t: t.sort_order)
    
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
):
    """Create a new prompt template.
    
    Args:
        request: Incoming request
        title: Display title for the template
        description: Brief description
        prompt_detail: The actual prompt text
        
    Returns:
        JSON response with template data when called via AJAX
        (X-Requested-With: XMLHttpRequest), otherwise a redirect to the
        admin templates page.
        
    Requirements: 2.3
    """
    # Validate inputs
    title = title.strip()
    description = description.strip()
    prompt_detail = prompt_detail.strip()
    
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    
    if not title or not description or not prompt_detail:
        logger.warning("Create template failed: missing required fields")
        if is_ajax:
            return JSONResponse(
                content={"success": False, "error": "Missing required fields"},
                status_code=400,
            )
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
        if is_ajax:
            return JSONResponse(
                content={"success": True, "template": template.to_dict()}
            )
    else:
        logger.error("Failed to create template", extra={"title": title})
        if is_ajax:
            return JSONResponse(
                content={"success": False, "error": "Failed to create template"},
                status_code=500,
            )
    
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


@admin_router.post("/templates/reorder")
async def reorder_templates(request: Request) -> JSONResponse:
    """Update sort_order for all templates based on drag-and-drop order.
    
    Expects JSON body: { "order": ["template_id_1", "template_id_2", ...] }
    where the array index becomes each template's new sort_order.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"success": False, "error": "Invalid JSON"}, status_code=400
        )

    order = body.get("order", [])  # list of template_id strings in new order
    if not isinstance(order, list) or not order:
        return JSONResponse(
            content={"success": False, "error": "No order provided"}, status_code=400
        )

    storage = PromptTemplateStorageService()
    for idx, template_id in enumerate(order):
        await storage.update_sort_order(str(template_id), idx)

    logger.info("Admin reordered templates", extra={"count": len(order)})
    return JSONResponse(content={"success": True, "count": len(order)})


@admin_router.post("/templates/bulk-delete")
async def bulk_delete_templates(request: Request) -> JSONResponse:
    """Delete multiple templates at once.
    
    Expects JSON body: { "template_ids": ["id1", "id2", ...] }
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"success": False, "error": "Invalid JSON"}, status_code=400
        )

    ids = body.get("template_ids")
    if not isinstance(ids, list) or not ids:
        return JSONResponse(
            content={
                "success": False,
                "error": "Expected non-empty 'template_ids' array",
            },
            status_code=400,
        )

    storage = PromptTemplateStorageService()
    deleted = 0
    for tid in ids:
        if await storage.delete_template(str(tid)):
            deleted += 1

    logger.info(
        "Bulk deleted templates",
        extra={"requested": len(ids), "deleted": deleted},
    )
    return JSONResponse(content={"success": True, "deleted": deleted})


@admin_router.post("/templates/bulk-upload")
async def bulk_upload_templates(request: Request) -> JSONResponse:
    """Bulk upload prompt templates from a JSON array.

    Expects JSON body: { "templates": [ { "template_id": "...", "title": "...",
    "description": "...", "prompt_detail": "..." }, ... ] }

    Each item must have template_id, title, description, and prompt_detail.
    New templates are appended after any existing ones (sort_order continues
    from the current maximum).
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"success": False, "error": "Invalid JSON payload"},
            status_code=400,
        )

    templates_data = body.get("templates")
    if not isinstance(templates_data, list) or len(templates_data) == 0:
        return JSONResponse(
            content={
                "success": False,
                "error": "Expected a non-empty 'templates' array",
            },
            status_code=400,
        )

    required_keys = {"template_id", "title", "description", "prompt_detail"}
    errors = []
    for idx, item in enumerate(templates_data):
        if not isinstance(item, dict):
            errors.append(f"Item {idx}: not a dictionary")
            continue
        missing = required_keys - set(item.keys())
        if missing:
            errors.append(f"Item {idx}: missing keys {', '.join(sorted(missing))}")
        for key in required_keys:
            val = item.get(key, "")
            if isinstance(val, str) and not val.strip():
                errors.append(f"Item {idx}: '{key}' is empty")

    if errors:
        return JSONResponse(
            content={
                "success": False,
                "error": "Validation failed",
                "details": errors,
            },
            status_code=400,
        )

    storage = PromptTemplateStorageService()
    existing = await storage.get_all_templates()
    max_order = max((t.sort_order for t in existing), default=-1)

    created = []
    for idx, item in enumerate(templates_data):
        template = await storage.create_template_with_id(
            template_id=item["template_id"].strip(),
            title=item["title"].strip(),
            description=item["description"].strip(),
            prompt_detail=item["prompt_detail"].strip(),
            sort_order=max_order + 1 + idx,
        )
        if template:
            created.append(template.to_dict())

    logger.info("Bulk uploaded templates", extra={"count": len(created)})
    return JSONResponse(
        content={"success": True, "created": len(created), "templates": created}
    )


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
