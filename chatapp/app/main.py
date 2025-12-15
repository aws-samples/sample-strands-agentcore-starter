"""Main FastAPI application entry point for HTMX ChatApp."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from pathlib import Path
from dotenv import load_dotenv
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Load environment variables from .env file
load_dotenv()

from app.config import get_config, ConfigurationError
from app.auth.middleware import AuthMiddleware
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.memory import router as memory_router
from app.routes.admin import router as admin_router
from app.routes.feedback import router as feedback_router, admin_router as feedback_admin_router
from app.routes.prompt_templates import router as templates_router, admin_router as templates_admin_router

# Set up paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# Check if we're in development mode (reload enabled)
DEV_MODE = os.environ.get("DEV_RELOAD", "false").lower() == "true"

# Live reload setup for development
hot_reload = None
if DEV_MODE:
    try:
        import arel
        hot_reload = arel.HotReload(paths=[
            arel.Path(str(TEMPLATES_DIR)),
            arel.Path(str(STATIC_DIR)),
        ])
        print("[DEV] Hot reload enabled - watching templates and static files")
    except ImportError:
        print("[DEV] arel not installed, hot reload disabled. Run: pip install arel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    try:
        config = get_config()
        mode = "DEV MODE" if config.dev_mode else "PRODUCTION"
        print(f"[{mode}] Configuration loaded for region: {config.aws_region}")
        if config.dev_mode:
            print(f"[DEV MODE] Auth bypassed, using user ID: {config.dev_user_id}")
    except ConfigurationError as e:
        print(f"Configuration error: {e}")
        raise
    
    # Start hot reload if enabled
    if hot_reload:
        await hot_reload.startup()
    
    yield
    
    # Shutdown
    if hot_reload:
        await hot_reload.shutdown()


# Initialize FastAPI app
app = FastAPI(
    title="Agentic Chat App",
    description="HTMX-based chat application with AgentCore backend",
    version="0.1.0",
    lifespan=lifespan,
)

# Initialize templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Inject hot reload script into templates if enabled
if hot_reload:
    templates.env.globals["hot_reload"] = hot_reload

# Add proxy headers middleware (for ALB/reverse proxy HTTPS handling)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

# Add authentication middleware
app.add_middleware(AuthMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(admin_router)
app.include_router(feedback_router)
app.include_router(feedback_admin_router)
app.include_router(templates_router)
app.include_router(templates_admin_router)

# Add hot reload route if enabled
if hot_reload:
    app.add_websocket_route("/hot-reload", hot_reload, name="hot-reload")

# Mount static files if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health_check():
    """Health check endpoint for ECS."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def root():
    """Root endpoint - redirects to chat or login."""
    return RedirectResponse(url="/chat", status_code=302)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Chat page - requires authentication (handled by middleware).
    
    Renders the main chat interface with HTMX.
    """
    # Get user info from request state (set by auth middleware)
    user = getattr(request.state, "user", None)
    user_email = user.email if user else None
    is_admin = getattr(request.state, "is_admin", False)
    
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "user_email": user_email, "is_admin": is_admin}
    )
