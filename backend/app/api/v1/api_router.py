from fastapi import APIRouter
from app.api.v1.routes import health, prompt, scenes

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(prompt.router, prefix="/prompt", tags=["Prompts"])
api_router.include_router(scenes.router, prefix="/scenes", tags=["Scenes"])
