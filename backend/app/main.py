from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.api_router import api_router

app = FastAPI(
title="Prompt-to-Animation Backend",
version="1.0.0"
)

# CORS configuration
app.add_middleware(
CORSMiddleware,
allow_origins=["*"], 
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

# Include versioned API routes
app.include_router(api_router, prefix="/api/v1")

# test route
@app.get("/", summary="Root")
def root():
    return {"message": "API is running"}
