from fastapi import APIRouter
from typing import Any

router = APIRouter()


@router.get(
    "/health",
    summary="Health check",
    description="Returns `{status: ok}` when the API process is running. Used by Docker and load balancers.",
    response_model=dict[str, Any],
)
def health_check():
    return {"status": "ok"}
