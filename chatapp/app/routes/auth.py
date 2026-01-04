"""Authentication routes for HTMX ChatApp.

This module provides authentication endpoints using Cognito's direct
InitiateAuth API (no hosted UI required). Login only - no signup or password reset.
"""

import json
from typing import Optional
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse

from app.auth.cognito import CognitoAuth, AuthenticationError
from app.auth.middleware import SESSION_COOKIE_NAME
from app.templates_config import templates

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    """Render the login page.
    
    Args:
        request: Incoming request
        error: Optional error message to display
        
    Returns:
        HTML login page
    """
    error_messages = {
        "invalid_credentials": "Invalid email or password",
        "session_expired": "Your session has expired. Please log in again.",
        "invalid_session": "Invalid session. Please log in again.",
        "auth_failed": "Authentication failed. Please try again.",
    }
    
    error_message = error_messages.get(error, error) if error else None
    
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": error_message,
        }
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission.
    
    Args:
        request: Incoming request
        email: User's email address
        password: User's password
        
    Returns:
        Redirect to chat page on success, or back to login with error
    """
    try:
        cognito = CognitoAuth()
        token_response = await cognito.authenticate(email, password)
        
        # Extract validated username from the ID token (not raw user input)
        # This prevents cookie injection by ensuring the username comes from Cognito
        user_info = cognito.validate_token(
            token_response.access_token,
            verify_exp=True,
            id_token=token_response.id_token
        )
        validated_username = user_info.username or user_info.email or user_info.user_id
        
        # Create session data - split into two cookies to stay under 4KB limit
        # Main session cookie (access + id tokens)
        session_data = {
            "access_token": token_response.access_token,
            "id_token": token_response.id_token,
            "username": validated_username,  # Use validated username from token
        }
        
        # Redirect to chat page with session cookies
        # Note: secure=False for localhost development, should be True in production
        is_localhost = request.url.hostname in ("localhost", "127.0.0.1")
        cookie_value = json.dumps(session_data)
        
        response = RedirectResponse(url="/chat", status_code=302)
        
        # Set main session cookie
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie_value,
            httponly=True,
            secure=not is_localhost,
            samesite="lax",
            max_age=86400 * 30,  # 30 days
        )
        
        # Set refresh token in separate cookie
        if token_response.refresh_token:
            response.set_cookie(
                key=f"{SESSION_COOKIE_NAME}_refresh",
                value=token_response.refresh_token,
                httponly=True,
                secure=not is_localhost,
                samesite="lax",
                max_age=86400 * 30,  # 30 days
            )
        
        return response
        
    except AuthenticationError:
        return RedirectResponse(
            url="/auth/login?error=invalid_credentials",
            status_code=302,
        )


@router.post("/logout")
async def logout(request: Request):
    """Log out user by clearing session cookies.
    
    Args:
        request: Incoming request
        
    Returns:
        Redirect to login page
    """
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(f"{SESSION_COOKIE_NAME}_refresh")
    return response


@router.get("/logout")
async def logout_get(request: Request):
    """Log out user (GET method for convenience).
    
    Args:
        request: Incoming request
        
    Returns:
        Redirect to login page
    """
    return await logout(request)
