"""Knowledge Base Explorer routes.

A browser over the documents the agent's Bedrock Knowledge Base is built from:

* **Documents** — a flat list of every source document (no scopes). Browse the
  list, read text-based files inline, and upload new documents.
* **Semantic search** — run the same retrieval the agent uses to validate what
  it will see for a given question.

The page (``/admin/kb``) is admin-gated by ``AuthMiddleware`` (ADMIN_PREFIXES).
The JSON API (``/api/kb/*``) requires authentication; the upload endpoint
additionally requires admin. The page renders a shell; documents and search
results load lazily through the JSON API so a slow call never blocks the page.
"""

import logging

from fastapi import APIRouter, Request, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse

from app.templates_config import templates
from app.storage import knowledge_base as kb

logger = logging.getLogger(__name__)

# Admin router for the page (admin-gated via middleware ADMIN_PREFIXES).
admin_router = APIRouter(prefix="/admin", tags=["knowledge-base"])

# API router for lazy data loading (JSON 401 handling via middleware).
api_router = APIRouter(prefix="/api/kb", tags=["knowledge-base-api"])


# ── Page ──────────────────────────────────────────────────────────────────────
@admin_router.get("/kb", response_class=HTMLResponse)
async def knowledge_base_page(request: Request):
    """Render the Knowledge Base Explorer shell."""
    user = getattr(request.state, "user", None)
    user_email = user.email if user else None
    is_admin = getattr(request.state, "is_admin", False)

    from app.helpers import get_app_settings
    app_settings = await get_app_settings()

    return templates.TemplateResponse(
        "admin/knowledge_base.html",
        {
            "request": request,
            "user_email": user_email,
            "is_admin": is_admin,
            "kb_configured": kb.is_configured(),
            "breadcrumbs": [
                {"label": "Admin", "url": "/admin"},
                {"label": "Knowledge Base"},
            ],
            "primary_action": {"type": "back_to_chat"},
            **app_settings,
        },
    )


# ── JSON API ────────────────────────────────────────────────────────────────────
@api_router.get("/documents")
async def api_documents() -> JSONResponse:
    """List KB source documents (flat, no scope)."""
    return JSONResponse(await kb.list_documents())


@api_router.get("/document")
async def api_document(key: str = Query(..., min_length=1)) -> JSONResponse:
    """Read one KB source document's contents (when text-based)."""
    return JSONResponse(await kb.get_document(key))


@api_router.get("/search")
async def api_search(q: str = Query("", alias="q")) -> JSONResponse:
    """Semantic retrieval against the vector Knowledge Base."""
    return JSONResponse(await kb.search(q))


@api_router.post("/upload")
async def api_upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a new document into the Knowledge Base and start ingestion.

    Admin-only: the JSON API prefix is not admin-gated by the middleware, so the
    check is enforced here.
    """
    if not getattr(request.state, "is_admin", False):
        return JSONResponse(
            content={"error": "You must be an administrator to upload documents."},
            status_code=403,
        )

    data = await file.read()
    result = await kb.upload_document(
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type or "",
    )
    status = 400 if result.get("error") else 200
    return JSONResponse(content=result, status_code=status)
