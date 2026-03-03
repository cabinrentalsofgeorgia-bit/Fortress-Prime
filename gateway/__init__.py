"""
Fortress Prime — Enterprise API Gateway
==========================================
Unified entry point for all Fortress services.

Modules:
    db          Shared PostgreSQL connection pool
    schema      Auth table creation and seeding
    auth        JWT + API key authentication
    middleware  Rate limiting and request logging
    users       User management endpoints (/v1/auth/*)
    app         The FastAPI application (main entrypoint)

Run:
    uvicorn gateway.app:app --host 0.0.0.0 --port 8000
"""
