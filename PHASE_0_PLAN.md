# Phase 0 — Platform Foundations: Detailed Scope

Companion to `PRODUCTION_PLAN.md` (Section 6, Phase 0). This breaks that phase into ordered, independently-verifiable steps against the actual current codebase, so it can be implemented and checked off incrementally rather than as one big rewrite.

**Phase 0 does not change any user-visible behavior.** By the end of it, `POST /api/v1/prompt`, `GET /api/v1/scenes`, `GET /api/v1/scenes/{id}`, `DELETE /api/v1/scenes/{id}` all work exactly as they do today — same request/response shapes. What changes underneath: MongoDB → PostgreSQL, the LiteLLM call → the Groq model router, and the generation logic now runs inside a (currently one-node) LangGraph graph instead of a plain function call. Phases 1–9 build real new behavior on top of this; Phase 0 is purely the foundation swap.

---

## Key scoping decisions (read before starting)

1. **One Scene per Video, for now.** `PRODUCTION_PLAN.md`'s `videos`/`scenes` split is designed for the future (Phase 3+) where one video has many scenes. Phase 0 doesn't build the storyboard step yet, so `create_scene()` will insert **one `videos` row and exactly one child `scenes` row together**, and reads/updates operate on that pair. This keeps the existing flat `SceneDocument` API response (prompt, generated_script, status, video_url, error_message — all in one object) working with zero changes to `app/schemas/scene_schema.py` or the route handlers. This 1:1 invariant is expected to end in Phase 3, not before.
2. **Status values stay as today's `SceneStatus` enum** (`pending / validating / queued / rendering / completed / failed`) on both the `videos` and `scenes` tables. The richer pipeline-stage status (`planning → scripting → storyboarding → ...`) described in `PRODUCTION_PLAN.md` Section 5 only becomes meaningful once those stages actually exist — introducing it now would just be unused values. It gets extended in Phase 2/3.
3. **No data migration from the existing MongoDB.** This starts the Postgres database empty. If there's dev data in Mongo you actually want to keep, flag it before I touch this — otherwise I'll assume it's disposable local/dev data.
4. **Testing stays fully mocked**, matching how the current suite already works (`pytest.ini` literally says "Integration tests — external services are mocked" — confirmed by reading the actual test files; nothing hits a real Mongo today). No test containers or real Postgres-in-CI needed for Phase 0 — repository unit tests mock the SQLAlchemy session the same way they currently mock the Motor collection.
5. **`GROQ_API_KEY` replaces `LLM_API_KEY`**, and `LLM_BASE_URL` goes away — the app is Groq-only now, no more "any LiteLLM-supported provider" flexibility. This is a deliberate narrowing, not an oversight.

---

## File manifest

**New files:**
- `backend/app/db/base.py` — SQLAlchemy declarative `Base`
- `backend/app/db/models.py` — ORM classes: `Video`, `Scene`, `SceneAttempt`, `PipelineEvent`
- `backend/app/db/session.py` — async engine + `AsyncSessionLocal` + `get_db()` FastAPI dependency
- `backend/app/db/sync_session.py` — sync engine + `SessionLocal` (for Celery)
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial_schema.py`
- `backend/app/core/model_router.py` — Groq model-per-node mapping, `ChatGroq` clients, rate limiting, retry
- `backend/app/graphs/__init__.py`, `backend/app/graphs/video_graph.py` — the LangGraph skeleton
- `backend/.env.example` — documents the required env vars (doesn't exist today)

**Deleted files:**
- `backend/app/db/mongodb.py`
- `backend/app/db/sync_mongodb.py`

**Modified files:**
- `backend/app/core/config.py` — `MONGODB_URL`/`MONGODB_DB_NAME` → `DATABASE_URL`; `LLM_API_KEY` → `GROQ_API_KEY`; drop `LLM_BASE_URL`
- `backend/app/main.py` — lifespan hooks use the new engine instead of `connect_db`/`close_db`
- `backend/app/repository/scene_repository.py` — rewritten on `AsyncSession`, same function signatures
- `backend/app/repository/sync_scene_repository.py` — rewritten on sync `Session`, same function signatures
- `backend/app/services/llm_service.py` — `litellm.acompletion` calls replaced by `model_router.call_llm(...)`
- `backend/app/services/scene_service.py` — `generate_and_queue` now invokes `video_graph.ainvoke(...)`
- `backend/requirements.txt` — remove `motor`, `pymongo`, `litellm`; add `sqlalchemy`, `asyncpg`, `psycopg[binary]`, `alembic`, `langgraph`, `langchain`, `langchain-groq`, `tenacity`, `aiolimiter`
- `docker-compose.yml` — `mongodb` service → `postgres:16` service
- `backend/tests/conftest.py`, `backend/tests/integration/conftest.py` — patch targets updated to the new DB startup functions; `ObjectId()` → `uuid4()` in test helpers
- `backend/tests/unit/test_scene_repository.py` — mocks rewritten for `AsyncSession` instead of a Motor collection

**Untouched (this is the point — proves the migration is behavior-preserving):**
- `backend/app/api/v1/routes/prompt.py`, `scenes.py`, `health.py`
- `backend/app/schemas/scene_schema.py`, `prompt_schema.py`
- `backend/app/utils/script_validator.py`
- `backend/app/workers/celery_app.py`, `render_task.py` (only the repository functions they import change underneath them)
- `backend/app/core/limiter.py`, `logging.py`

---

## Ordered steps

### 0.1 — Stand up Postgres (infra only, no app code yet)
- `docker-compose.yml`: replace the `mongodb` service with `postgres:16` (env `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`; volume `postgres_data:/var/lib/postgresql/data`; healthcheck via `pg_isready`). Update the `backend`/`worker` services' `environment:` block to set `DATABASE_URL` pointing at the `postgres` hostname instead of the old `MONGODB_URL` override.
- `app/core/config.py`: replace `MONGODB_URL`/`MONGODB_DB_NAME` with `DATABASE_URL: str`.
- `requirements.txt`: remove `motor`, `pymongo`; add `sqlalchemy>=2.0`, `asyncpg`, `psycopg[binary]`, `alembic`.
- **Exit check:** `docker-compose up postgres` starts and reports healthy; a throwaway `asyncpg.connect(DATABASE_URL)` script can connect.

### 0.2 — Schema + migration
- `app/db/base.py` + `app/db/models.py`: define `Video`, `Scene`, `SceneAttempt`, `PipelineEvent` exactly per `PRODUCTION_PLAN.md` Section 5 — UUID primary keys (`sqlalchemy.dialects.postgresql.UUID`, `default=uuid4`), `JSONB` columns for `script`/`verified_trace`/`style_guide`/`validation_result`/`reviewer_feedback`/`input_summary`/`output_summary`, FKs with `ondelete="CASCADE"`, index on `(video_id, order)` in `scenes`. `status` columns are plain strings validated against the existing `SceneStatus` enum (decision #2 above).
- Initialize Alembic in `backend/`; wire `alembic/env.py` to import `Base.metadata` and read `DATABASE_URL` (via the sync `psycopg` driver string, since Alembic runs synchronously) from `app.core.config.settings`.
- Write `versions/0001_initial_schema.py` creating all four tables.
- **Exit check:** `alembic upgrade head` against the dockerized Postgres creates all four tables with the right columns/FKs/indexes (verify with `\d videos`, `\d scenes` etc.); `alembic downgrade base` cleanly drops them.

### 0.3 — Async repository rewrite (API side)
- `app/db/session.py`: `create_async_engine(DATABASE_URL)`, `AsyncSessionLocal`, `get_db()` dependency yielding an `AsyncSession`.
- Delete `app/db/mongodb.py`.
- Rewrite `app/repository/scene_repository.py`, keeping the exact same public functions (`create_scene`, `get_scene_by_id`, `list_scenes`, `update_scene_status`, `delete_scene`, `update_scene_script`, `update_scene_video`) — internally: `create_scene` inserts one `Video` row + one child `Scene` row in one transaction; the rest join/query that pair and map back to the unchanged `SceneDocument` Pydantic shape.
- **Exit check:** `tests/unit/test_scene_repository.py` (mocks rewritten for `AsyncSession`) passes.

### 0.4 — Sync repository rewrite (Celery worker side)
- `app/db/sync_session.py`: sync engine + `SessionLocal`.
- Delete `app/db/sync_mongodb.py`.
- Rewrite `app/repository/sync_scene_repository.py`, keeping `get_scene_by_id_sync`, `update_scene_status_sync`, `update_scene_video_sync` with identical signatures.
- **Exit check:** `app/workers/render_task.py` needs **zero** line changes — proves the abstraction held.

### 0.5 — Wire `main.py`, finish config cleanup
- `main.py` lifespan: swap `connect_db()`/`close_db()` for creating/disposing the async engine.
- `config.py`: finalize — remove Mongo fields, `LLM_API_KEY` → `GROQ_API_KEY`, drop `LLM_BASE_URL`.
- `tests/conftest.py`: update the autouse fixture to patch the new startup/shutdown instead of `connect_db`/`close_db`.
- **Exit check:** `uvicorn app.main:app` boots against the dockerized Postgres; `GET /api/v1/health` → `200 ok`.

### 0.6 — Route the existing LLM call through Groq
- `app/core/model_router.py`: a `NODE_MODEL_MAP` dict (only `"scene_codegen": "openai/gpt-oss-20b"` populated for now — Phase 2+ add `"scriptwriter"`, `"storyboard"`, `"critic"` entries later), a `ChatGroq` client per model (`langchain-groq`), an `aiolimiter.AsyncLimiter` per model, and a `tenacity`-wrapped `call_llm(node_name, messages) -> str`.
- `app/services/llm_service.py`: `generate_manim_script`/`fix_manim_script` call `model_router.call_llm("scene_codegen", ...)` instead of `litellm.acompletion` — function signatures unchanged, so `scene_service.py` doesn't need to change here.
- **Exit check:** a real manual prompt submission produces a script via Groq's `gpt-oss-20b`, observably going through the rate limiter (e.g. log line per call).

### 0.7 — LangGraph skeleton
- `app/graphs/video_graph.py`: a `StateGraph` with one node, `generate_scene_code`, wrapping the existing generate → AST-validate → repair-loop logic **moved from** `scene_service.generate_and_queue`, unchanged in behavior. Define a `GraphState` (prompt, scene_id, script, validation_result, attempt_count) now so later phases extend it instead of reshaping it.
- `scene_service.generate_and_queue`: builds the initial state, calls `video_graph.ainvoke(state)`, then dispatches to Celery using the result — exceptions raised and status transitions written stay identical to today.
- **Exit check:** full prompt → script → validate → queue → render flow still behaves identically end-to-end, now executing through a one-node graph.

### 0.8 — Test suite + cleanup
- Update `tests/integration/conftest.py`'s `make_scene()` helper (`ObjectId()` → `uuid4()`), and confirm `test_prompt_endpoint.py`/`test_scene_endpoints.py` still pass (they mock at the route/service level, so should need minimal changes).
- Remove dead imports (`bson`, `motor`, `pymongo`, `litellm` if nothing else uses it).
- Add `backend/.env.example` documenting `DATABASE_URL`, `GROQ_API_KEY`, `REDIS_URL`, `MEDIA_DIR`, `ALLOWED_ORIGINS`.
- **Exit check (Phase 0 overall milestone):** `pytest` fully green; submitting a prompt via the live API still works exactly as it does today from the outside, but is now backed end-to-end by Postgres, routes its LLM call through Groq via the rate-limited router, and runs the generation logic through a LangGraph graph — ready for Phase 1 to add the voice step.

---

## Before I start implementing

One thing I want you to confirm rather than assume: **is there any data in the current MongoDB you need kept** (test prompts you care about, anything demoed to someone)? If not, I'll treat the Postgres database as starting empty, per decision #3 above.
