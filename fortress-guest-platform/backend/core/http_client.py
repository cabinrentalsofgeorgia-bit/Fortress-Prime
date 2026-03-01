"""
Shared httpx.AsyncClient singleton for outbound HTTP calls.

Prevents TCP connection exhaustion from per-request client instantiation.
Import `shared_client` wherever you need to make async HTTP requests instead
of creating `async with httpx.AsyncClient() as c:` in each handler.

Lifecycle is managed by the FastAPI lifespan — call `close_shared_client()`
during shutdown.
"""

import httpx

shared_client: httpx.AsyncClient = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=100),
    follow_redirects=True,
)


async def close_shared_client() -> None:
    """Gracefully close the shared client. Call from FastAPI shutdown."""
    await shared_client.aclose()
