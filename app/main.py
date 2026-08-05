import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import activities, budget, itinerary
from app.services.mcp_client import close_mcp_client, init_mcp_client

logger = logging.getLogger("vancouver_explorer")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Upper bound on the MCP STDIO handshake during warm-up. The warm-up runs in the
# background, so this only bounds how long the stray task lives, not startup.
MCP_STARTUP_TIMEOUT_SECONDS = float(os.environ.get("MCP_STARTUP_TIMEOUT", "10"))

# The frontend is normally served from this same origin, so CORS only matters
# when index.html is opened from a separate dev server. Allow local origins
# only — a "*" wildcard alongside allow_credentials is both unsafe and invalid.
DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def allowed_origins() -> list[str]:
    configured = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not configured:
        return DEFAULT_ALLOWED_ORIGINS
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


async def prewarm_mcp_client() -> None:
    """Best-effort MCP warm-up.

    Spawning the STDIO server is a subprocess handshake that can stall (slow
    interpreter start, a server that never writes to stdout, no network). It must
    never gate startup, so failures here are logged and dropped: request handlers
    start the client lazily on first use anyway.
    """
    try:
        await asyncio.wait_for(init_mcp_client(), timeout=MCP_STARTUP_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        logger.warning(
            "MCP client warm-up timed out after %ss; weather tools will connect on first request.",
            MCP_STARTUP_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("MCP client warm-up failed (%r); will retry on first request.", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Fire-and-forget: startup completes immediately, uvicorn binds the port.
    warmup = asyncio.create_task(prewarm_mcp_client(), name="mcp-prewarm")
    try:
        yield
    finally:
        warmup.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await warmup
        with suppress(Exception):
            await close_mcp_client()


app = FastAPI(
    title="Vancouver Summer Explorer",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(activities.router)
app.include_router(itinerary.router)
app.include_router(budget.router)


@app.get("/health")
def health():
    return {"status": "ok"}


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
