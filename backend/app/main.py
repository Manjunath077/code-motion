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
from app.core.config import settings
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.db.mongodb import connect_db, close_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.APP_ENV == "development":
        logger.warning("Running in DEVELOPMENT mode — do not use in production")
    logger.info("LLM model: %s | API key loaded: %s", settings.LLM_MODEL, "yes" if settings.LLM_API_KEY else "NO")
    await connect_db()
    logger.info("MongoDB connected")
    yield
    await close_db()
    logger.info("MongoDB disconnected")


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
