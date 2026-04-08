from fastapi import APIRouter

from app.api.v1.routes import health

api_router = APIRouter()

# Include all route modules here

api_router.include_router(health.router)
