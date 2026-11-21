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
- `backend/requirements/` — exact pins: `base.txt` (API image), `worker.txt` (+ manim, worker image), `dev.txt` (+ test tools, local venv).
- `backend/Dockerfile.api` (slim, no Manim) and `backend/Dockerfile.worker` (Manim, LaTeX, ffmpeg).
- `frontend/` — React + Vite + TypeScript.
- `docker-compose.yml` — `redis`, `backend` (8000), `worker`, `beat` (Postgres is the native host install).
- `backend/app/pipeline/` — the state machine (stages, transitions, runner); Celery entry points in `backend/app/workers/`.

## Local services

- **Python 3.11** — venv at `backend/venv` (gitignored). Never install packages globally.
- **Postgres** — local native install, port **5434**, database and role `code_motion` (managed in pgAdmin).
- **Redis** — the `redis` service in `docker-compose.yml` (named volume, published on `127.0.0.1:6379`). Local dev: `docker compose up -d --build redis worker beat`, then uvicorn from the venv. Rebuild (`--build`) after every backend code change — code is baked into the images.
- `backend/.env` holds secrets and uses `localhost`. Containers additionally load `backend/.env.docker`, which overrides `DATABASE_URL` with `host.docker.internal`; compose sets `REDIS_URL` to the `redis` service (see the comment in `docker-compose.yml`). Both env files are gitignored.

## Commands

Backend (run from `backend/`):

```
py -3.11 -m venv venv              # once
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt    # = requirements/dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker --loglevel=info --concurrency=2   # Windows: add -P solo (or use the Docker worker)
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

Containers: `docker compose up -d --build` from the repo root starts redis, backend, worker and beat as one `code-motion` group (needs local Postgres and `backend/.env.docker`).
