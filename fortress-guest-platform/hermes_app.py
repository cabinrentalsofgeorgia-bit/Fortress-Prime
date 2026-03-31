from fastapi import FastAPI

from backend.api import paperclip_bridge

app = FastAPI(
    title="Fortress Hermes Bridge",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(paperclip_bridge.router, prefix="/api/agent", tags=["Paperclip Bridge"])
app.include_router(paperclip_bridge.router, prefix="/api/paperclip", tags=["Paperclip Bridge"])


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
