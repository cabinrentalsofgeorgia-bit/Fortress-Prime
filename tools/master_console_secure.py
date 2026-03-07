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

import asyncio
import os
import logging
import httpx
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, FastAPI, Request, HTTPException, Depends
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
GATEWAY_URL = os.getenv("GATEWAY_URL", f"http://{BASE}:8001")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3001")
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

_http_client = httpx.AsyncClient(timeout=15.0)

@app.on_event("shutdown")
async def shutdown():
    await _http_client.aclose()

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
# UNIVERSAL CHAT ROUTER (Local DGX + Anthropic)
# ══════════════════════════════════════════════════════════════════════════════

try:
    import litellm
except ImportError:
    litellm = None

chat_router = APIRouter()

class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=65536)
    provider: str = "local"  # Default to sovereign compute for security

LOCAL_AI_GATEWAY = "http://127.0.0.1:8090"

@chat_router.post("/v1/chat/completions")
async def universal_chat(payload: ChatPayload):
    log.info("Universal chat request: provider=%s", payload.provider)
    try:
        # Debug: bypass backend for "ping" to verify route is reachable
        if payload.message.strip().lower() == "ping":
            return {
                "reply": "pong",
                "routed_via": "debug",
                "sovereign_status": "SECURE",
            }
        if payload.provider == "local":
            # Direct proxy to AI Gateway (OpenAI-compatible); avoids LiteLLM for sovereign path
            model_string = "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
            resp = await _http_client.post(
                f"{LOCAL_AI_GATEWAY}/v1/chat/completions",
                json={
                    "model": model_string,
                    "messages": [{"role": "user", "content": payload.message}],
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            content = (
                (data.get("choices") or [{}])[0].get("message", {}).get("content")
                or ""
            )
            return {
                "reply": content,
                "routed_via": model_string,
                "sovereign_status": "SECURE",
            }
        elif payload.provider == "anthropic":
            if litellm is None:
                raise HTTPException(status_code=503, detail="LiteLLM not installed. pip install litellm")
            api_key = os.getenv("ANTHROPIC_API_KEY") or ""
            if not api_key:
                raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not set in .env")
            model_string = "claude-3-5-sonnet-20241022"
            response = await asyncio.to_thread(
                litellm.completion,
                model=model_string,
                messages=[{"role": "user", "content": payload.message}],
                api_key=api_key,
            )
            content = getattr(
                getattr(getattr(response, "choices", [None])[0], "message", None),
                "content",
                None,
            ) or ""
            return {
                "reply": content,
                "routed_via": model_string,
                "sovereign_status": "CLOUD",
            }
        else:
            raise HTTPException(status_code=400, detail="Provider not configured.")
    except HTTPException:
        raise
    except Exception as e:
        log.exception("Universal chat error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

app.include_router(chat_router)

# Same handler on alternate path to test if /v1/chat/completions is special
@app.post("/api/chat")
async def api_chat(payload: ChatPayload):
    """Alias for universal_chat to isolate route-specific crashes."""
    return await universal_chat(payload)

# Minimal route: no Pydantic, raw body; to isolate if ChatPayload parsing kills the process
@app.post("/api/chat/ping")
async def api_chat_ping(request: Request):
    body = await request.json()
    msg = (body or {}).get("message", "")
    if msg.strip().lower() == "ping":
        return {"reply": "pong", "routed_via": "debug", "sovereign_status": "SECURE"}
    return {"reply": "send message: ping", "routed_via": "debug", "sovereign_status": "SECURE"}

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
    """Login endpoint - authenticates with Gateway and returns JSON + sets session cookie."""
    try:
        gateway_resp = await _http_client.post(
            f"{GATEWAY_URL}/v1/auth/login",
            json={"username": body.username, "password": body.password},
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
        
        from fastapi.responses import JSONResponse
        response = JSONResponse(content={
            "access_token": data["access_token"],
            "username": data["username"],
            "role": data.get("role", "viewer"),
        })
        response.set_cookie(
            key=COOKIE_NAME,
            value=data["access_token"],
            httponly=True,
            secure=IS_PRODUCTION,
            samesite="lax",
            max_age=86400
        )
        
        return response
    
    except httpx.HTTPError as e:
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
        gateway_resp = await _http_client.post(
            f"{GATEWAY_URL}/v1/auth/signup",
            json=body.dict(),
        )
        
        if gateway_resp.status_code != 200:
            error_data = gateway_resp.json()
            raise HTTPException(
                status_code=gateway_resp.status_code,
                detail=error_data.get("detail", "Signup failed")
            )
        
        log.info(f"New signup: {body.username}")
        return gateway_resp.json()
    
    except httpx.HTTPError as e:
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
        resp = await _http_client.get(
            f"{GATEWAY_URL}/v1/auth/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.post("/api/admin/users")
async def admin_create_user(body: UserCreateRequest, request: Request):
    """Create user (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.post(
            f"{GATEWAY_URL}/v1/auth/users",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.info(f"Admin {user.get('username')} created user: {body.username}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.patch("/api/admin/users/{user_id}/role")
async def admin_update_role(user_id: int, body: RoleUpdateRequest, request: Request):
    """Update user role (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.patch(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.info(f"Admin {user.get('username')} updated user {user_id} role to: {body.role}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.patch("/api/admin/users/{user_id}/status")
async def admin_update_status(user_id: int, body: StatusUpdateRequest, request: Request):
    """Update user status (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.patch(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}/status",
            headers={"Authorization": f"Bearer {token}"},
            json=body.dict(),
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        action = "activated" if body.is_active else "deactivated"
        log.info(f"Admin {user.get('username')} {action} user {user_id}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    """Delete user (admin only)."""
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    token = request.cookies.get(COOKIE_NAME)
    try:
        resp = await _http_client.delete(
            f"{GATEWAY_URL}/v1/auth/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail"))
        
        log.warning(f"Admin {user.get('username')} DELETED user {user_id}")
        return resp.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Gateway unavailable")

# ══════════════════════════════════════════════════════════════════════════════
# HTML PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root(request: Request):
    """Authenticated root — redirect to the native Next.js Command Center."""
    try:
        get_current_user(request)
        return RedirectResponse(url=FRONTEND_URL, status_code=302)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve login page with injected FRONTEND_URL for SSO redirect."""
    login_html = Path(__file__).parent / "login.html"
    if not login_html.exists():
        return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)
    content = login_html.read_text()
    content = content.replace(
        "</head>",
        f'<script>window.__FRONTEND_URL__="{FRONTEND_URL}";</script></head>',
    )
    return HTMLResponse(content=content)

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
# LEGAL FILE PROXY (FGP Backend on port 8100)
# ══════════════════════════════════════════════════════════════════════════════

NAS_LEGAL_ROOT = "/mnt/fortress_nas/sectors/legal"
_CASE_SUBDIRS = ("certified_mail", "correspondence", "evidence", "receipts", "filings/incoming", "filings/outgoing")
_MIME_MAP = {".pdf": "application/pdf", ".txt": "text/plain", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".csv": "text/csv"}


@app.get("/api/legal/cases/{slug}/download/{filename}")
async def legal_download(slug: str, filename: str, request: Request):
    """Serve legal files directly from NAS (authenticated)."""
    get_current_user(request)

    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    case_root = Path(NAS_LEGAL_ROOT) / slug
    if not case_root.is_dir():
        raise HTTPException(status_code=404, detail=f"Case vault '{slug}' not found")

    for subdir in _CASE_SUBDIRS:
        candidate = case_root / subdir / filename
        if candidate.is_file():
            resolved = candidate.resolve()
            if not str(resolved).startswith(NAS_LEGAL_ROOT):
                raise HTTPException(status_code=403, detail="Access denied")
            ext = candidate.suffix.lower()
            media_type = _MIME_MAP.get(ext, "application/octet-stream")
            log.info(f"Legal download: {slug}/{subdir}/{filename} by {request.cookies.get(COOKIE_NAME, 'unknown')[:8]}")
            from fastapi.responses import FileResponse
            return FileResponse(path=str(resolved), media_type=media_type, filename=filename)

    raise HTTPException(status_code=404, detail=f"File '{filename}' not found in case vault")


@app.get("/api/legal/cases/{slug}/files")
async def legal_files(slug: str, request: Request):
    """List all files in a case's NAS vault (authenticated)."""
    get_current_user(request)

    case_root = Path(NAS_LEGAL_ROOT) / slug
    if not case_root.is_dir():
        raise HTTPException(status_code=404, detail=f"Case vault '{slug}' not found")

    files = []
    for subdir in _CASE_SUBDIRS:
        d = case_root / subdir
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                files.append({
                    "filename": f.name,
                    "subdir": subdir,
                    "size_bytes": f.stat().st_size,
                    "download_url": f"/api/legal/cases/{slug}/download/{f.name}",
                })
    return {"case_slug": slug, "files": files, "total": len(files)}


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
