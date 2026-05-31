from pydantic import BaseModel, Field
from typing import Optional


class PromptRequest(BaseModel):
    prompt: str = Field(..., max_length=2000)


class PromptResponse(BaseModel):
    scene_id: Optional[str] = None
    script: Optional[str] = None
    status: str
