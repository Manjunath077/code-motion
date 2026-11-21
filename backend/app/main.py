import asyncio
import contextlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import os

from app.api.v1.api_router import api_router
from app.core import activity_console
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.db.session import connect_db, close_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV == "development":
        logger.warning("Running in DEVELOPMENT mode — do not use in production")
    logger.info("OpenRouter API key loaded: %s", "yes" if settings.OPENROUTER_API_KEY else "NO")
    # Settings already refused to load if any of these lacks ':free'.
    logger.info(
        "LLM models (free only): ultra=%s vl=%s lightning=%s",
        settings.MODEL_ULTRA, settings.MODEL_VL, settings.MODEL_LIGHTNING,
    )
    await connect_db()
    logger.info("PostgreSQL connected")
    console = None
    if settings.ACTIVITY_CONSOLE_ENABLED:
        # Prints worker / LLM / render events in this log (activity_console.py).
        console = asyncio.create_task(activity_console.run())
        logger.info("Activity console on — pipeline events from all processes print here")
    yield
    if console is not None:
        console.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await console
    await close_db()
    logger.info("PostgreSQL disconnected")


app = FastAPI(title="Code-Motion Backend", version="1.0.0", lifespan=lifespan)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

os.makedirs(settings.MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR"},
    )


@app.get("/", summary="Root")
def root():
    return {"message": "API is running"}
