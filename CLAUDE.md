# Code-Motion

Prompt → 3Blue1Brown-style narrated explainer video (target: 5 minutes), built on ManimCE.

`NEW_PLAN.md` is the source of truth for decisions, flow and implementation order. Changes are implemented **one step at a time** (Section 6 of the plan). Do not start a step until the previous one is verified.

## Hard rules

1. **Free models only.** All LLM calls go through OpenRouter using model IDs ending in `:free`. Never call a paid model. Any non-`:free` ID bills real credits.
2. **Model IDs live in config only**, never hard-coded in code.
3. **No LangChain, no LangGraph.** Orchestration is a plain Python state machine; each stage is a function `artifact_in → artifact_out`.
4. **ManimCE pinned to `0.19.x`.** Not `manimgl`.
5. **No LLM calls inside an HTTP request.** The API creates the job and returns 202; Celery workers do the rest.
6. **LLM-generated code runs only in the sandbox** (no network, no secrets, CPU/memory/time limits).
7. **Trace is ground truth.** The LLM never invents algorithm steps; a real Python implementation produces the trace, the LLM narrates and animates it.
8. **Secrets:** `OPENROUTER_API_KEY` only in `backend/.env`, never committed.
9. **Privacy:** free endpoints may log/train on prompts. Never send user personal data to them.
10. **Tests:** do not delete old tests without replacements.
11. **IP:** borrow the 3Blue1Brown visual style only. No Pi creatures, logo, branding or music.

## Repo layout

- `backend/` — FastAPI app (`app/`), Celery workers (`app/workers/`), Postgres + Alembic (`alembic/`), tests (`tests/`).
- `frontend/` — React + Vite + TypeScript.
- `docker-compose.yml` — `postgres` (host port 5433), `redis` (6379), `backend` (8000), `worker`.

## Commands

Backend (run from `backend/`):

```
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
pytest                 # all tests
pytest -m unit         # unit tests only
pytest -m integration  # integration tests (external services mocked)
```

Frontend (run from `frontend/`):

```
npm install
npm run dev
npm run build
npm run lint
```

Full stack: `docker compose up --build` from the repo root.
