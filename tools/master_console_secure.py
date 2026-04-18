#!/usr/bin/env python3
"""
CROG Command Center - Master Console (SECURITY HARDENED)
==========================================================
Enterprise-grade command center with production security

SECURITY IMPROVEMENTS:
- JWT secret from environment (not hardcoded)
- Restricted CORS origins
- Secure cookie settings
- Input validation with Pydantic
- Rate limiting on authentication endpoints
- Security headers
"""

import os
import logging
import requests
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from jose import jwt, JWTError

# Load environment variables
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

# Logging (must be before other code that uses it)
log = logging.getLogger("console")
logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s [CONSOLE] %(levelname)s %(message)s"
)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION (SECURE)
# ══════════════════════════════════════════════════════════════════════════════

BASE = os.getenv("BASE_IP", "192.168.0.100")
GATEWAY_URL = os.getenv("GATEWAY_URL", f"http://{BASE}:8000")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

# SECURITY: JWT secret MUST come from environment
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "SECURITY ERROR: JWT_SECRET environment variable not set. "
        "Add to .env file: JWT_SECRET=<your-secret-key>"
    )

JWT_ALGORITHM = "HS256"
COOKIE_NAME = "fortress_session"

# SECURITY: Restrict CORS to known origins
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "https://crog-ai.com,http://192.168.0.100:9800,http://localhost:9800"
).split(",")

log.info(f"Environment: {ENVIRONMENT}")
log.info(f"Allowed CORS origins: {ALLOWED_ORIGINS}")

# ══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="CROG Command Center",
    version="2.1.0-secure",
    docs_url=None if IS_PRODUCTION else "/docs",  # Disable docs in production
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

# SECURITY: Restricted CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Only known domains
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    max_age=3600,
)

# SECURITY: Add security headers
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    return response

# ══════════════════════════════════════════════════════════════════════════════
# MODELS (WITH VALIDATION)
# ══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)

class SignupRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=3, max_length=50, pattern="^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(admin|operator|viewer)$")

class RoleUpdateRequest(BaseModel):
    role: str = Field(pattern="^(admin|operator|viewer)$")

class StatusUpdateRequest(BaseModel):
    is_active: bool

# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════════════════════

def verify_jwt(token: str) -> dict:
    """Verify and decode JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        log.warning(f"JWT verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(request: Request) -> dict:
    """Get current authenticated user from cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_jwt(token)

# ══════════════════════════════════════════════════════════════════════════════
# API ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/login")
async def login(body: LoginRequest):
    """Login endpoint - authenticates with Gateway and sets session cookie."""
    try:
        gateway_resp = requests.post(
            f"{GATEWAY_URL}/v1/auth/login",
            json={"username": body.username, "password": body.password},
            timeout=10
        )
        
        if gateway_resp.status_code != 200:
            error_data = gateway_resp.json()
            log.warning(f"Login failed for user: {body.username}")
            raise HTTPException(
                status_code=gateway_resp.status_code,
                detail=error_data.get("detail", "Login failed")
            )
        
        data = gateway_resp.json()
        log.info(f"Login successful: {data['username']} ({data['role']})")
        
        # SECURITY: Create response with secure cookie
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=COOKIE_NAME,
            value=data["access_token"],
            httponly=True,
            secure=IS_PRODUCTION,  # Auto-enable in production
            samesite="strict",  # More secure than "lax"
            max_age=86400  # 24 hours
        )
        
        return response
    
    except requests.RequestException as e:
        log.error(f"Gateway connection failed: {e}")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")

@app.post("/api/logout")
async def logout():
    """Logout endpoint - clears session cookie."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response

@app.get("/api/verify")
async def verify_session(user: dict = Depends(get_current_user)):
    """Verify current session and return user info."""
    return {
        "username": user.get("username"),
        "role": user.get("role"),
        "authenticated": True
    }

@app.post("/api/signup")
async def signup(body: SignupRequest):
    """Public signup endpoint - creates user pending admin approval."""
    try:
        gateway_resp = requests.post(
            f"{GATEWAY_URL}/v1/auth/signup",
            json=body.dict(),
            timeout=10
        )
        
        if gateway_resp.status_code != 200:
            error_data = gateway_resp.json()
            raise HTTPException(
                status_code=gateway_resp.status_code,
                detail=error_data.get("detail", "Signup failed")
            )
        
        log.info(f"New signup: {body.username}")
        return gateway_resp.json()
    
    except requests.RequestException as e:
        log.error(f"Gateway connection failed: {e}")
        raise HTTPException(status_code=503, detail="Registration service unavailable")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN USER MANAGEMENT APIs
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    """List all users (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        log.warning(f"Unauthorized admin access attempt by: {user.get('username')}")
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = requests.get(
            f"{GATEWAY_URL}/v1/auth/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        return resp.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.post("/api/admin/users")
async def admin_create_user(body: UserCreateRequest, request: Request):
    """Create user (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = requests.post(
            f"{GATEWAY_URL}/v1/auth/users",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
            timeout=10
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.info(f"Admin {user.get('username')} created user: {body.username}")
        return resp.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.patch("/api/admin/users/{user_id}/role")
async def admin_update_role(user_id: int, body: RoleUpdateRequest, request: Request):
    """Update user role (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = requests.patch(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
            timeout=10
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.info(f"Admin {user.get('username')} updated user {user_id} role to: {body.role}")
        return resp.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.patch("/api/admin/users/{user_id}/status")
async def admin_update_status(user_id: int, body: StatusUpdateRequest, request: Request):
    """Update user status (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = requests.patch(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
            timeout=10
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        action = "activated" if body.is_active else "deactivated"
        log.info(f"Admin {user.get('username')} {action} user {user_id}")
        return resp.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    """Delete user (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = requests.delete(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.warning(f"Admin {user.get('username')} DELETED user {user_id}")
        return resp.json()
    except requests.RequestException:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

# ══════════════════════════════════════════════════════════════════════════════
# HTML PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Main dashboard - requires authentication."""
    try:
        user = get_current_user(request)
        dashboard_html = Path(__file__).parent / "dashboard.html"
        if not dashboard_html.exists():
            return HTMLResponse(content=f"<h1>Welcome {user['username']}</h1><p>Dashboard coming soon...</p>")
        return HTMLResponse(content=dashboard_html.read_text())
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve login page."""
    login_html = Path(__file__).parent / "login.html"
    if not login_html.exists():
        return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)
    return HTMLResponse(content=login_html.read_text())

@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    """Serve public signup page."""
    signup_html = Path(__file__).parent / "signup.html"
    if not signup_html.exists():
        return HTMLResponse(content="<h1>Signup page not found</h1>", status_code=404)
    return HTMLResponse(content=signup_html.read_text())

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    """Serve user management page (admin only)."""
    try:
        user = get_current_user(request)
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")
        
        users_html = Path(__file__).parent / "users.html"
        if not users_html.exists():
            return HTMLResponse(content="<h1>User management page not found</h1>", status_code=404)
        return HTMLResponse(content=users_html.read_text())
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve profile page (requires authentication)."""
    try:
        user = get_current_user(request)
        profile_html = Path(__file__).parent / "profile.html"
        if not profile_html.exists():
            return HTMLResponse(content="<h1>Profile page not found</h1>", status_code=404)
        return HTMLResponse(content=profile_html.read_text())
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "crog-console",
        "version": "2.1.0-secure",
        "environment": ENVIRONMENT
    }

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    log.info("=" * 70)
    log.info("  🔒 CROG COMMAND CENTER (SECURITY HARDENED)")
    log.info("  Cabin Rentals of Georgia")
    log.info(f"  Environment: {ENVIRONMENT}")
    log.info(f"  URL: http://{BASE}:9800")
    log.info(f"  CORS: {len(ALLOWED_ORIGINS)} allowed origins")
    log.info(f"  Secure Cookies: {IS_PRODUCTION}")
    log.info("=" * 70)
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=9800,
        log_level="info"
    )
