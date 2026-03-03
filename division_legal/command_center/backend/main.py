"""
Fortress Legal Command Center — Main FastAPI Application
Tracks attorneys, meetings, matters, and builds an ongoing legal record.
"""
import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.core.config import settings
from backend.core.database import init_db, close_db
from backend.api import attorneys, matters, meetings, timeline, documents

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting_legal_command_center", environment=settings.environment)
    try:
        await init_db()
    except Exception as e:
        logger.warning("database_init_skipped", error=str(e))
    yield
    await close_db()
    logger.info("legal_command_center_shutdown")


app = FastAPI(
    title="Fortress Legal Command Center",
    description="Attorney, meeting, and matter tracking for Fortress Prime legal operations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(attorneys.router, prefix="/api/attorneys", tags=["Attorneys"])
app.include_router(matters.router, prefix="/api/matters", tags=["Matters"])
app.include_router(meetings.router, prefix="/api/meetings", tags=["Meetings"])
app.include_router(timeline.router, prefix="/api/timeline", tags=["Timeline"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Fortress Legal Command Center",
        "version": "1.0.0",
    }


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    if (FRONTEND_DIR / "css").exists():
        app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
    if (FRONTEND_DIR / "js").exists():
        app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")


@app.get("/")
@app.get("/dashboard")
@app.get("/dashboard/{path:path}")
async def serve_dashboard(path: str = ""):
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"error": "Dashboard not found", "path": str(FRONTEND_DIR)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
