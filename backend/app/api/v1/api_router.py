from fastapi import APIRouter
from app.api.v1.routes import health, videos

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(videos.router, prefix="/videos", tags=["Videos"])
