# AlgoAnimate — Backend Implementation Plan

## Project Understanding

AlgoAnimate converts natural language prompts into rendered Manim animations.
The full pipeline is: User Prompt → LLM → Script Validation → Redis Queue → Celery Worker → Manim Renderer → Video Storage → Frontend.

### Current State (already done)
- FastAPI app with CORS
- `GET /api/v1/health` endpoint
- `POST /api/v1/prompt` endpoint (returns raw script string only, no persistence)
- OpenAI LLM service (`gpt-4o-mini`) that generates Manim Python scripts
- Pydantic schemas: `PromptRequest`, `PromptResponse`
- Basic `Settings` class loading `OPENAI_API_KEY`

### What Does NOT Exist Yet
- MongoDB connection, Scene model, repository layer
- Script validation (AST-based safety checks)
- Redis + Celery worker queue
- Manim rendering worker
- Video storage and serving
- Scene CRUD endpoints (`GET /scenes`, `GET /scenes/{id}`, `POST /scenes/{id}/regenerate`, `DELETE /scenes/{id}`)
- Rate limiting
- Docker / Docker Compose
- Full status state machine (pending → validating → queued → rendering → completed/failed)

---

## Architecture Recap

```
POST /api/v1/prompt
        |
        v
   LLM Service  ──────────────────────────────────────────────────────────────┐
        |                                                                      |
        v                                                                      |
 Script Validator  (AST parse, check imports, check allowed constructs)       |
        |                                                                      |
        v                                                                      |
 MongoDB Scene document created  (status = queued)                            |
        |                                                                      |
        v                                                                      |
 Redis Queue  (Celery task pushed)                                             |
        |                                                                      |
        v                                                                      |
 Celery Worker                                                                 |
        |                                                                      |
        v                                                                      |
 Manim Renderer  (subprocess: manim render script.py)                         |
        |                                                                      |
        v                                                                      |
 Video saved to /media/videos/{scene_id}/                                     |
        |                                                                      |
        v                                                                      |
 MongoDB Scene updated  (status = completed, video_url = ...)   <─────────────┘
        |
        v
 Frontend polls GET /api/v1/scenes/{scene_id}  →  video_url returned
```

---

## Phase 1 — Solidify Foundation (Refactor Existing Code)

**Goal:** Clean up the existing skeleton so it can support everything built on top.

### Tasks

1. **Upgrade `config.py`** — use Pydantic `BaseSettings` instead of bare class so env vars are typed, validated, and have defaults:
   ```python
   # backend/app/core/config.py
   from pydantic_settings import BaseSettings

   class Settings(BaseSettings):
       OPENAI_API_KEY: str
       MONGODB_URL: str = "mongodb://localhost:27017"
       MONGODB_DB_NAME: str = "algoanimate"
       REDIS_URL: str = "redis://localhost:6379/0"
       MEDIA_DIR: str = "media"
       APP_ENV: str = "development"

       class Config:
           env_file = ".env"

   settings = Settings()
   ```

2. **Add structured logging** — use Python `logging` with a formatter in `app/core/logging.py`. Log every request lifecycle event.

3. **Add global exception handler** — catch unhandled exceptions in `main.py` and return a consistent JSON error shape `{"detail": "...", "code": "..."}`.

4. **Update `PromptResponse` schema** — include `scene_id` and `status` in the response so the frontend can poll for the scene immediately after submission.

5. **Add `requirements.txt` entries** for the full stack:
   ```
   fastapi
   uvicorn[standard]
   pydantic-settings
   python-dotenv
   openai
   motor               # async MongoDB driver
   redis
   celery[redis]
   manim
   slowapi             # rate limiting
   ```

6. **Folder structure** — create all missing `__init__.py` files and stub modules:
   ```
   backend/app/
   ├── db/
   │   ├── __init__.py
   │   └── mongodb.py          # connection + db accessor
   ├── repository/
   │   ├── __init__.py
   │   └── scene_repository.py
   ├── workers/
   │   ├── __init__.py
   │   ├── celery_app.py
   │   └── render_task.py
   ├── utils/
   │   ├── __init__.py
   │   └── script_validator.py
   ```

**Milestone:** `uvicorn app.main:app` starts without errors, all routes return correct status codes, config loads from `.env`.

---

## Phase 2 — MongoDB Integration & Scene Model

**Goal:** Every prompt submission persists a `Scene` document. All scene data lives in MongoDB.

### Data Model

```python
# backend/app/schemas/scene_schema.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum

class SceneStatus(str, Enum):
    PENDING    = "pending"
    VALIDATING = "validating"
    QUEUED     = "queued"
    RENDERING  = "rendering"
    COMPLETED  = "completed"
    FAILED     = "failed"

class SceneDocument(BaseModel):
    id: str                           # MongoDB _id as string
    prompt: str
    generated_script: Optional[str]
    status: SceneStatus
    video_url: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
```

### Tasks

1. **`app/db/mongodb.py`** — async Motor client singleton:
   ```python
   from motor.motor_asyncio import AsyncIOMotorClient
   from app.core.config import settings

   _client: AsyncIOMotorClient = None

   async def connect_db():
       global _client
       _client = AsyncIOMotorClient(settings.MONGODB_URL)

   async def close_db():
       global _client
       if _client:
           _client.close()

   def get_db():
       return _client[settings.MONGODB_DB_NAME]
   ```

2. **Register lifecycle hooks in `main.py`**:
   ```python
   @app.on_event("startup")
   async def startup():
       await connect_db()

   @app.on_event("shutdown")
   async def shutdown():
       await close_db()
   ```

3. **`app/repository/scene_repository.py`** — all DB operations, no business logic here:
   - `create_scene(prompt: str) -> SceneDocument`
   - `get_scene_by_id(scene_id: str) -> Optional[SceneDocument]`
   - `list_scenes(limit: int, skip: int) -> list[SceneDocument]`
   - `update_scene_status(scene_id: str, status: SceneStatus, **kwargs)`
   - `delete_scene(scene_id: str) -> bool`
   - `update_scene_script(scene_id: str, script: str)`
   - `update_scene_video(scene_id: str, video_url: str)`

4. **Update `POST /api/v1/prompt`** — create a `Scene` document at the start (status=`pending`), pass `scene_id` to the LLM service, update document after LLM responds, return `scene_id` to frontend.

5. **Add `GET /api/v1/scenes` endpoint** (pagination: `?skip=0&limit=20`).

6. **Add `GET /api/v1/scenes/{scene_id}` endpoint** — returns full scene document.

7. **Add `DELETE /api/v1/scenes/{scene_id}` endpoint**.

**Milestone:** Submitting a prompt creates a MongoDB document, `/scenes` returns a list, `/scenes/{id}` returns the document. Verify with MongoDB Compass.

---

## Phase 3 — Script Validation Layer

**Goal:** Before a script is queued for rendering, it must pass safety validation. Prevents arbitrary code execution in the Manim worker.

### Validation Rules
- Script must be valid Python (parse with `ast.parse` — if it fails, reject immediately)
- No `import` statements beyond the Manim standard library (`from manim import *` only)
- Banned modules: `os`, `sys`, `subprocess`, `socket`, `requests`, `urllib`, `shutil`, `pathlib`, `importlib`, `builtins`, `__import__`, `eval`, `exec`, `open`
- Must contain exactly one class that inherits from `Scene`
- The `construct` method must exist on that class
- No `open()`, `exec()`, `eval()`, or `__import__()` calls anywhere in the AST

### Tasks

1. **`app/utils/script_validator.py`**:
   ```python
   import ast
   from dataclasses import dataclass

   BANNED_MODULES = {"os", "sys", "subprocess", "socket", "requests",
                     "urllib", "shutil", "pathlib", "importlib"}
   BANNED_BUILTINS = {"eval", "exec", "open", "__import__", "compile"}

   @dataclass
   class ValidationResult:
       is_valid: bool
       error: str = ""

   def validate_manim_script(script: str) -> ValidationResult:
       # 1. AST parse check
       # 2. Walk AST nodes - check imports, function calls
       # 3. Check for exactly one Scene subclass
       # 4. Check construct() exists
       ...
   ```

2. **Integrate into the prompt flow**:
   - After LLM generates script: update scene status → `validating`
   - Run `validate_manim_script(script)`
   - If invalid: update scene status → `failed`, store `error_message`, return 422
   - If valid: proceed to queue

3. **Add custom `HTTPException` shape** for validation failures:
   ```json
   { "detail": "Script validation failed: banned import 'os'", "code": "VALIDATION_ERROR" }
   ```

4. **Unit tests** — `tests/test_validator.py`:
   - Test valid script passes
   - Test script with `import os` fails
   - Test script without Scene class fails
   - Test script with `eval()` call fails
   - Test malformed Python fails

**Milestone:** A script with `import os` is rejected before reaching the queue. A clean Manim script passes. Tests pass.

---

## Phase 4 — Redis + Celery Worker Queue

**Goal:** Decouple rendering from the HTTP request. The API pushes a job to Redis; a Celery worker consumes it asynchronously.

### Tasks

1. **`app/workers/celery_app.py`** — Celery configuration:
   ```python
   from celery import Celery
   from app.core.config import settings

   celery_app = Celery(
       "algoanimate",
       broker=settings.REDIS_URL,
       backend=settings.REDIS_URL,
       include=["app.workers.render_task"],
   )

   celery_app.conf.update(
       task_serializer="json",
       result_serializer="json",
       accept_content=["json"],
       task_track_started=True,
   )
   ```

2. **`app/workers/render_task.py`** — the Celery task (stub for now, rendering in Phase 5):
   ```python
   from app.workers.celery_app import celery_app

   @celery_app.task(bind=True, name="render_scene")
   def render_scene(self, scene_id: str):
       # Phase 5 will fill this
       pass
   ```

3. **Update prompt flow to push to queue**:
   - After validation passes: update status → `queued`
   - Call `render_scene.delay(scene_id)`
   - Return `{ "scene_id": scene_id, "status": "queued" }` to frontend immediately

4. **`POST /api/v1/prompt` final shape after Phase 4:**
   ```
   Request:  { "prompt": "animate bubble sort" }
   Response: { "scene_id": "abc123", "status": "queued" }
   (HTTP 202 Accepted)
   ```

5. **Verify queue is working** — start Redis locally, start Celery worker with `celery -A app.workers.celery_app worker --loglevel=info`, submit a prompt, confirm task appears in Celery logs.

**Milestone:** Submitting a prompt returns `scene_id` + `queued` immediately. Celery worker picks up the task. Scene status in MongoDB reflects `queued`.

---

## Phase 5 — Manim Rendering Worker

**Goal:** The Celery worker actually renders the Manim script and saves the video file.

### Rendering Strategy
- Write the script to a temp file in `/tmp/scenes/{scene_id}/scene.py`
- Run Manim as a subprocess: `manim render /tmp/scenes/{scene_id}/scene.py -ql -o {scene_id}`
- Manim outputs video to its default media dir; move it to `settings.MEDIA_DIR/{scene_id}/`
- Update MongoDB with `video_url` and status `completed`
- On any failure: update status → `failed`, store stderr as `error_message`

### Tasks

1. **`app/workers/render_task.py`** — implement render logic:
   ```python
   import subprocess
   import os
   import shutil
   import tempfile
   from pathlib import Path
   from app.workers.celery_app import celery_app
   from app.repository.scene_repository import (
       get_scene_by_id, update_scene_status, update_scene_video
   )
   from app.schemas.scene_schema import SceneStatus

   @celery_app.task(bind=True, name="render_scene", max_retries=1)
   def render_scene(self, scene_id: str):
       update_scene_status(scene_id, SceneStatus.RENDERING)
       scene = get_scene_by_id(scene_id)

       scene_dir = Path(tempfile.mkdtemp()) / scene_id
       scene_dir.mkdir(parents=True, exist_ok=True)
       script_path = scene_dir / "scene.py"
       script_path.write_text(scene.generated_script)

       try:
           result = subprocess.run(
               ["manim", "render", str(script_path), "-ql", "--media_dir", str(scene_dir / "media")],
               capture_output=True, text=True, timeout=120
           )
           if result.returncode != 0:
               raise RuntimeError(result.stderr)

           # Find the .mp4 output
           video_files = list((scene_dir / "media").rglob("*.mp4"))
           if not video_files:
               raise RuntimeError("Manim produced no video output")

           # Move to persistent media dir
           dest_dir = Path(settings.MEDIA_DIR) / scene_id
           dest_dir.mkdir(parents=True, exist_ok=True)
           final_path = dest_dir / "output.mp4"
           shutil.move(str(video_files[0]), str(final_path))

           video_url = f"/media/{scene_id}/output.mp4"
           update_scene_video(scene_id, video_url)
           update_scene_status(scene_id, SceneStatus.COMPLETED)

       except Exception as e:
           update_scene_status(scene_id, SceneStatus.FAILED, error_message=str(e))
       finally:
           shutil.rmtree(str(scene_dir), ignore_errors=True)
   ```

2. **Note on sync vs async** — Celery tasks are synchronous. The repository calls in the worker must use `pymongo` (sync), not `motor` (async). Create a `app/db/sync_mongodb.py` with a sync PyMongo client for use inside workers only.

3. **Serve static video files** — in `main.py`:
   ```python
   from fastapi.staticfiles import StaticFiles
   app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")
   ```

4. **Handle rendering timeout** — Manim subprocess has `timeout=120`; if it exceeds this, mark as `failed`.

5. **Test end-to-end** locally (without Docker) — submit prompt, watch Celery logs, confirm video appears in `media/` folder.

**Milestone:** A valid prompt goes through the full pipeline. The final `GET /scenes/{scene_id}` response has `status: "completed"` and a working `video_url`.

---

## Phase 6 — Remaining Scene Endpoints

**Goal:** Complete the REST API surface so the frontend can display scene history and trigger regeneration.

### Tasks

1. **`POST /api/v1/scenes/{scene_id}/regenerate`**:
   - Fetch existing scene, copy `prompt`
   - Set status back to `pending`
   - Re-run LLM generation
   - Re-validate
   - Re-push to queue
   - Return `{ "scene_id": scene_id, "status": "queued" }`

2. **`GET /api/v1/scenes`** — paginated list:
   ```
   GET /api/v1/scenes?skip=0&limit=20
   Response: { "scenes": [...], "total": 42 }
   ```

3. **Finalize `GET /api/v1/scenes/{scene_id}`** — make sure all fields are present including `video_url` and `error_message`.

4. **`DELETE /api/v1/scenes/{scene_id}`**:
   - Delete MongoDB document
   - Delete video file from disk (`media/{scene_id}/`)
   - Return `204 No Content`

5. **Route wiring** — add all scene routes to `api_router.py` under prefix `/scenes`.

**Milestone:** All 6 planned endpoints work and return correct responses. Test with `httpie` or Postman.

---

## Phase 7 — Rate Limiting & Security Hardening

**Goal:** Prevent abuse and make the API safe for exposure.

### Tasks

1. **Rate limiting with `slowapi`**:
   ```python
   # 10 prompt submissions per minute per IP
   @router.post("/", ...)
   @limiter.limit("10/minute")
   async def generate_script(request: Request, body: PromptRequest):
       ...
   ```

2. **Prompt length validation** — add `max_length=2000` to `PromptRequest.prompt` via Pydantic `Field`.

3. **Tighten CORS** — in production, replace `allow_origins=["*"]` with explicit frontend origin from env var:
   ```python
   ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]
   ```

4. **Script validator hardening** — add checks for:
   - Script length > 10,000 characters (reject)
   - More than 1 Scene class (reject)
   - Nested function definitions beyond 3 levels (reject)

5. **Environment validation** — on startup, assert that `OPENAI_API_KEY` is set; log a warning if `APP_ENV=development`.

**Milestone:** Submitting more than 10 prompts/minute from the same IP returns `429 Too Many Requests`. Prompts over 2000 chars return `422`.

---

## Phase 8 — Dockerization

**Goal:** The entire backend stack runs with a single `docker-compose up`.

### Docker Compose Services
```yaml
services:
  backend:     # FastAPI + uvicorn
  worker:      # Celery worker (same image, different command)
  mongodb:     # mongo:7
  redis:       # redis:7-alpine
```

### Tasks

1. **`backend/Dockerfile`**:
   ```dockerfile
   FROM python:3.11-slim
   # Install system deps for Manim (Cairo, FFmpeg, LaTeX)
   RUN apt-get update && apt-get install -y \
       ffmpeg libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
       texlive texlive-latex-extra
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```

2. **`docker-compose.yml`** at project root:
   ```yaml
   version: "3.9"
   services:
     mongodb:
       image: mongo:7
       volumes:
         - mongo_data:/data/db
     redis:
       image: redis:7-alpine
     backend:
       build: ./backend
       ports: ["8000:8000"]
       env_file: ./backend/.env
       depends_on: [mongodb, redis]
       volumes:
         - ./media:/app/media
     worker:
       build: ./backend
       command: celery -A app.workers.celery_app worker --loglevel=info
       env_file: ./backend/.env
       depends_on: [mongodb, redis]
       volumes:
         - ./media:/app/media
   volumes:
     mongo_data:
   ```

3. **`.env.example`** — document all required env vars.

4. **Health check** — add Docker health check to backend service pointing at `/api/v1/health`.

**Milestone:** `docker-compose up` starts all 4 services. Full pipeline works inside Docker. `docker-compose logs worker` shows render tasks being processed.

---

## Phase 9 — Tests & Polish

**Goal:** Confidence that the system works correctly end-to-end.

### Tasks

1. **Unit tests** (`tests/unit/`):
   - `test_validator.py` — script validation rules (already planned in Phase 3)
   - `test_llm_service.py` — mock OpenAI client, test script cleaning logic
   - `test_scene_repository.py` — mock Motor, test CRUD operations

2. **Integration tests** (`tests/integration/`):
   - `test_prompt_endpoint.py` — POST /prompt with real MongoDB (test container), assert scene created
   - `test_scene_endpoints.py` — GET, DELETE, regenerate with seeded data

3. **Add `pytest.ini`** + `conftest.py` with test DB setup/teardown.

4. **OpenAPI docs cleanup** — add `summary`, `description`, and `response_model` to every route.

5. **Logging** — confirm all status transitions log at INFO level with `scene_id`.

**Milestone:** `pytest tests/unit/` passes with no mocks missing. Integration tests pass against a local MongoDB.

---

## Implementation Order Summary

| Phase | Focus | Key Output |
|-------|-------|-----------|
| 1 | Foundation refactor | Config, logging, folder structure |
| 2 | MongoDB + Scene model | Scene persisted, CRUD repo, basic endpoints |
| 3 | Script validation | AST safety checks, status transitions |
| 4 | Redis + Celery queue | Async job dispatch, 202 response |
| 5 | Manim rendering | End-to-end render, video file |
| 6 | Remaining endpoints | Regenerate, list, delete |
| 7 | Security + rate limiting | Rate limit, input validation |
| 8 | Docker | One-command startup |
| 9 | Tests + polish | Coverage, OpenAPI docs |

---

## Key File Map (End State)

```
backend/app/
├── main.py                          # FastAPI app, lifespan hooks, static files mount
├── core/
│   ├── config.py                    # Pydantic BaseSettings
│   └── logging.py                   # Logger factory
├── api/v1/
│   ├── api_router.py                # Includes all routers
│   └── routes/
│       ├── health.py                # GET /health
│       ├── prompt.py                # POST /prompt  → 202 + scene_id
│       └── scenes.py                # GET/DELETE /scenes, POST /regenerate
├── schemas/
│   ├── prompt_schema.py             # PromptRequest, PromptResponse
│   └── scene_schema.py              # SceneDocument, SceneStatus enum
├── services/
│   └── llm_service.py               # OpenAI client, generate_manim_script()
├── repository/
│   └── scene_repository.py          # Motor-based async CRUD
├── db/
│   ├── mongodb.py                   # Async Motor client (for API)
│   └── sync_mongodb.py              # Sync PyMongo client (for Celery worker)
├── workers/
│   ├── celery_app.py                # Celery instance
│   └── render_task.py               # render_scene Celery task
└── utils/
    └── script_validator.py          # AST-based Manim script validator
```
