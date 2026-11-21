# Code-Motion — New Plan

Prompt → 3Blue1Brown-style narrated explainer video (target: 5 minutes), built on ManimCE.

This document replaces `PRODUCTION_PLAN.md`, `PHASE_0_PLAN.md`, `.claude/BACKEND_PLAN.md` and `.claude/FRONTEND_PLAN.md`. It records every decision made and every change to be applied to the existing repo. Changes are to be implemented **one step at a time**, not all at once.

---

## 1. Decisions (locked)

| Topic | Decision |
|---|---|
| Language / API | Python + FastAPI (existing). React + Vite frontend (existing template, to be built). |
| Animation engine | **ManimCE**, pinned to `0.19.x` (same as Code2Video). Not `manimgl`. |
| Audio sync | `manim-voiceover` (`VoiceoverScene`, `with self.voiceover(text=...)`, bookmarks `<bookmark mark='x'/>` + `self.wait_until_bookmark("x")`). |
| Orchestration | **Plain Python state machine.** No LangChain, no LangGraph. Each stage is a function `artifact_in → artifact_out`. |
| MCP | Not part of the core. Optional extra interface later (expose `create_video`, `get_status` as MCP tools). |
| LLM provider | **OpenRouter** (replaces Groq). **Free models only** (`:free` suffix). No paid model calls, ever. |
| Models | NVIDIA Nemotron 3 Ultra (free), Nemotron 3.5 Super VL (free), Nemotron 3.5 Lightning (free) — routed per stage (Section 4). |
| Storyboard approval | Optional, **default ON** (`review_mode=true`). Pipeline pauses in `AWAITING_APPROVAL`. Auto-approve path for API/batch. |
| TTS | **Kokoro-82M** (local, free, CPU-capable) by default, behind a `TTSProvider` interface. Paid providers pluggable later. |
| v1 scope | **Algorithms only, arrays + trees first** (sorting, searching, heaps, BST). Expansion order later: graphs → DP tables → math (SymPy grounding) → free-form. |
| Ground truth | The LLM **never invents algorithm steps.** A real Python implementation produces a trace; the LLM narrates and animates that trace. |
| Unit of work | The **scene**: generated, checked, rendered, cached and re-runnable independently. |
| Timing | Audio drives timing, not the other way round. |

---

## 2. Reference research (new sources — use these, not the old plan's)

| Source | What we take from it |
|---|---|
| TheoremExplainAgent (TIGER-AI-Lab, ACL 2025, MIT) — https://tiger-ai-lab.github.io/TheoremExplainAgent , paper https://arxiv.org/abs/2502.19400 | Planner agent + coding agent split; RAG over Manim docs; Kokoro TTS; long-form (>5 min) videos. Main failure classes: **Manim API hallucination, LaTeX errors, general code errors** — our fix loop is designed around these three. |
| Code2Video (NUS Show Lab, `showlab/Code2Video`) — https://arxiv.org/html/2510.01174v1 | Planner → Coder → Critic. Critic is a vision-language model that fixes layout. **Visual anchor grid** for controlled placement (our layout zones). ~40% better than direct code generation. Uses ManimCE v0.19.0. |
| manim-generator (makefinks) | Writer + reviewer loop fed by execution logs. |
| Manimator — https://arxiv.org/html/2507.14306v1 | Two-stage: structured scene description first, then code. Confirms storyboard-before-code. |
| Generative Manim — https://github.com/360macky/generative-manim | Simple prompt → Manim code API; fine-tuned models for Manim. |
| Manimate backend (nitindavegit) | Minimal FastAPI + LLM + Manim service shape. |
| AnimAI (pushpitkamboj) | LLM agent + RAG index → Manim. |
| manim-voiceover — https://github.com/sueskind/manim-voiceover | In-code voiceover, per-word timing via Whisper, pluggable TTS. |
| `3b1b/videos`, `3b1b/manim` | How a real video is split into scenes. Style reference only. |

**IP rule:** borrow the visual style only. Do not copy Pi creatures, 3Blue1Brown logo, branding or music.

---

## 3. The flow

```
[0] Intake ──► [1] Spec ──► [2] Ground truth ──► [3] Outline ──► [4] Storyboard
                                                                      │
                                                            ◄── user approve/edit (cheap: text only)
                                                                      ▼
[9] Deliver ◄── [8] Assemble ◄── [7] TTS + Final render ◄── [6] QA loop ◄── [5] Scene codegen
                                                       (static → preview render → geometry → visual critic → trace check)
```

Every stage persists a **versioned artifact** (JSON or files) → resumable jobs, scene-level re-runs, per-stage debugging.

### Worked example used throughout: Heap Sort, 5 minutes

Prompt: *"Explain heap sort for CS students, 5 minutes."*

### [0] Intake
- Input: raw prompt + options (length, audience, voice, language, `review_mode`).
- Clarifier (LLM, Lightning): asks at most 2–3 questions only if the prompt is ambiguous (e.g. "Include build-heap O(n) proof?").
- Output: `Request` row.
- **No LLM call inside the HTTP request.** The request creates the job and returns 202; workers do the rest.

### [1] Spec (LLM, Lightning, structured JSON validated by Pydantic)
```json
{ "topic": "Heap Sort", "domain": "algorithm", "audience": "CS undergrad",
  "duration_s": 300, "words_budget": 750, "style": "dark-3b1b-like",
  "learning_goals": ["max-heap property","array↔tree mapping","sift-down","build-heap","sort phase","O(n log n), in-place, unstable"] }
```
- Word budget: ~150 words/minute → 5 min ≈ 750 words. Drives every later stage.
- Spec and Outline may be merged into one call to save requests.

### [2] Ground truth (deterministic, no LLM)
- `domain=algorithm` → run the real instrumented Python implementation.
- Input array: `[4, 10, 3, 5, 1, 8, 7, 2]` (8 elements fits on screen; 16 is too dense).
- Output `trace.json`:
```json
[{"phase":"build","op":"compare","i":3,"j":7}, {"op":"swap","i":3,"j":7}, ... ,
 {"phase":"sort","op":"swap","i":0,"j":7}, {"op":"shrink","heap_size":7}, ...]
```
- Future domains: math → SymPy-verified steps; physics → simulation; other → LLM + RAG.

### [3] Outline (LLM, Ultra)
Structure: hook → intuition → mechanism → worked example → why it works → recap.

| # | Scene | Time | Content |
|---|---|---|---|
| S1 | Hook | 0:00–0:25 | Unsorted bars. "Guaranteed n log n, no extra memory?" |
| S2 | What is a max-heap | 0:25–1:10 | Tree; parent ≥ children; root = max |
| S3 | Array ↔ tree | 1:10–1:50 | Same data, two views; children of `i` are `2i+1`, `2i+2`; link lines |
| S4 | Sift-down | 1:50–2:35 | One node sinks; each swap shown in both views at once |
| S5 | Build heap | 2:35–3:15 | Bottom-up from index `n/2-1`; first slow, then sped up |
| S6 | Sort phase | 3:15–4:15 | Swap root with last, shrink heap, sift down; sorted green region grows |
| S7 | Cost | 4:15–4:45 | Tree height = log n; O(n) build, O(n log n) total; in-place, unstable |
| S8 | Recap | 4:45–5:00 | Both views collapse into the sorted array |

### [4] Storyboard (LLM, Ultra) — the most important artifact
```json
{ "id":"S4", "duration_s":45,
  "start_state": "array top, tree bottom, values from trace step 0",
  "end_state":   "node 4 settled at index 3",
  "beats":[
    {"narration":"Suppose the root breaks the rule. <bookmark mark='cmp'/>Compare it with both children…",
     "visual":"highlight root yellow; at 'cmp' pulse children",
     "trace_ref":[12,13]},
    {"narration":"Swap with the larger one…", "visual":"swap animation in tree AND array simultaneously"}
  ],
  "layout": {"array":"TOP_ZONE","tree":"CENTER_ZONE","caption":"BOTTOM_ZONE"} }
```
- Narration and visuals written together, beat by beat; bookmarks mark the word where an animation fires.
- `start_state` / `end_state` keep hand-offs between scenes continuous.
- Layout uses named zones (Code2Video anchor idea), not free coordinates.
- Automatic checks (code, no LLM): total words within ±10% of budget; per-scene words match the time budget; every `trace_ref` exists; zones valid; end/start states line up. Lightning used only to fix word counts.
- **User checkpoint** (`AWAITING_APPROVAL`) when `review_mode=true`: view/edit/approve. Editing text is cheap; re-rendering is expensive.

### [5] Scene codegen (LLM, Ultra) — per scene, in parallel (within rate limit)
LLM input: the scene's storyboard + its trace slice + component library API + ManimCE 0.19 cheat sheet + 2–3 working example scenes (RAG/few-shot).

The LLM composes high-level helpers from our **component library** (`ArrayBars`, `HeapTree`, `Zones`, `Theme`, …) — ~40 lines instead of ~300 lines of raw Manim. Fewer hallucinations, consistent look.

Output: one `SceneS4.py` per scene, using `VoiceoverScene`.

### [6] QA loop (per scene, cheapest check first)
1. **Static check**: AST parse; import allowlist (`manim`, `manim_voiceover`, `motion_lib`, `numpy`); every Manim name exists in the pinned version; block dangerous builtins and dunder access; pre-compile all LaTeX.
2. **Preview render**: `-ql` (480p15) inside the sandbox (no network, CPU/memory/time limits, write only to output folder, no secrets).
3. **On error**: classify (API / LaTeX / logic — Lightning or rules) → traceback + code back to Ultra → max **3 fixes** → then **1 regenerate** from storyboard → then a **simplified fallback scene**.
4. **Geometry check** (deterministic): a hook inside the render records bounding boxes of on-screen objects at each bookmark → flags off-screen or overlapping objects.
5. **Visual critic** (Super VL): frames at each bookmark → "Does the frame match this beat? Readable? Cluttered?" → feedback to [5]. Max **2 rounds**. Runs on every new/changed scene (affordable at 1000 req/day). If VL is unavailable, skip and record a warning.
6. **Trace check**: after each swap, on-screen state (from component `.state()`) must equal the trace.

### [7] Audio + final render
- TTS **before** render, cached by `hash(text + voice)`. manim-voiceover then times animations to audio automatically.
- Kokoro default (local, free). Word timestamps from the provider, or Whisper alignment (supported by manim-voiceover).
- Final render `-qh` (1080p60), scenes in parallel.

### [8] Assemble (ffmpeg, deterministic)
- Join scenes in order; short crossfades only where `end_state` ≠ next `start_state`.
- Background music bed with sidechain ducking under the voice; loudness normalized to **-14 LUFS**.
- Subtitles `.srt` from narration + word timestamps.
- Thumbnail from a key frame.
- Final QA: total duration within 300 s ±5%, no black/silent gaps, audio and video streams same length.

### [9] Deliver
- Upload to storage (local disk now; S3/MinIO later behind the same interface) → link to the user (presigned URL with S3).
- Progress over SSE for the whole job, e.g. `storyboard ready` → `S4 rendering 2/8` → `done`.
- Edits after delivery: "make S5 slower" → re-run storyboard S5 → codegen → QA → render S5 → reassemble. Only possible because every stage is saved separately.

### Flow rules (summary)
1. Trace is ground truth.
2. Storyboard is the contract between "what to say" and "what to show", and the user's edit point.
3. Component library over raw Manim.
4. QA from cheap to expensive: static → 480p → geometry → vision critic → 1080p.
5. Scenes are the unit of work: parallel, cached, re-runnable.
6. Audio drives timing.
7. Orchestration is a plain state machine.

---

## 4. LLM strategy — OpenRouter, free NVIDIA models

### Stage → model routing

| Stage | Model | Why |
|---|---|---|
| `spec`, `clarify`, `classify_error`, `word_fix` | **Nemotron 3.5 Lightning (free)** — 30B MoE, 3B active, fast | Mechanical, cheap |
| `outline`, `storyboard`, `codegen`, `code_fix` | **Nemotron 3 Ultra (free)** — `nvidia/nemotron-3-ultra-550b-a55b:free`, 550B MoE, 55B active, 1M context, 64K output | Quality-critical reasoning and code |
| `visual_critic` (images) | **Nemotron 3.5 Super VL (free)** — `nvidia/nemotron-3.5-super-vl:free`, 120B MoE, 12B active, multimodal | Only one of the three that takes images |

- Verify the exact Lightning model ID on OpenRouter before wiring it.
- **Fallback chain for text:** Ultra → Super VL → Lightning, via OpenRouter's `models: [...]` parameter.
- Vision critic has no fallback; if VL is down, skip critic and record a warning.
- Model IDs live in config only, never in code (free models can disappear or change).

### Limits (verified on our key via `GET https://openrouter.ai/api/v1/key`)
- `is_free_tier: false` → `free_model_daily_requests.limit = 1000` per day (account-wide, shared with any other app using the account).
- **20 requests/minute** on `:free` models — this is the binding limit.
- Failed attempts count toward the daily cap.
- Daily reset assumed 00:00 UTC.

### Budget per 5-minute video (8 scenes)

| Stage | Calls |
|---|---|
| Spec + outline (merged) | 1–2 |
| Storyboard | 1–2 |
| Codegen (one per scene) | 8 |
| Fixes (~1 per scene average) | 6–10 |
| Vision critic (1–2 per scene) | 8–16 |
| **Total** | **~25–40** |

→ ~25–40 videos/day. One video's LLM work takes ~2–3 minutes at 18 req/min.

### Rules
- **Hard guard:** refuse any model ID not ending in `:free` — checked at startup (fail boot) and on every call. Any non-`:free` ID bills real credits.
- Use a **dedicated OpenRouter key for this project** with a **$1 credit limit**. The current key is shared with another app and has paid spend on it.
- `OPENROUTER_API_KEY` only in `backend/.env` (never committed).
- One **Redis-backed** rate limiter shared by API + all workers, ~18 req/min (not per-process `aiolimiter`).
- Daily budget: read `free_model_daily_requests.remaining` from `/api/v1/key` (cache ~60 s). Below `LLM_DAILY_RESERVE` → raise `QuotaExhausted` → job moves to `WAITING_QUOTA` and resumes after reset.
- Structured output: request JSON, validate with Pydantic, retry once with the validation error. Do not rely on provider-side schema enforcement.
- Cost reducers kept even at 1000/day (they protect speed and RPM headroom): deterministic checks before LLM calls; cache by content hash (same beat never generates code twice); critic only on new/changed scenes; storyboard checks in code.
- Privacy: free endpoints may log/train on prompts. Fine for algorithm content; never send user personal data.

---

## 5. Changes to the existing repo

Current state: single-shot pipeline — `POST /prompt` → LLM writes one 20–35 s script → AST check → Celery → `manim -qm` → one mp4. Infra (FastAPI, Postgres + Alembic, Celery + Redis, 4-table schema) is solid. Only part of stage [5] exists. Frontend is the untouched Vite template. Groq / LangChain / old flat scene model are referenced in 20 files.

### A. Groq → OpenRouter

| File | Change |
|---|---|
| `backend/requirements.txt` | Remove `langchain`, `langchain-groq`, `langgraph`. Add `openai` (OpenRouter is OpenAI-compatible). |
| `backend/app/core/config.py` | `GROQ_API_KEY` → `OPENROUTER_API_KEY`. Add `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`, `LLM_RPM=18`, `LLM_DAILY_RESERVE`, the three model IDs (`MODEL_ULTRA`, `MODEL_VL`, `MODEL_LIGHTNING`). Raise `LLM_TIMEOUT` 30 s → ~120 s (Ultra on long codegen is slow). |
| `backend/.env.example` | Same keys. Note: use a dedicated project key with a $1 limit. |
| `backend/app/main.py` | Startup log `"Groq API key loaded"` → OpenRouter. Startup check: every configured model ID ends in `:free`, else fail boot. |
| `backend/app/core/model_router.py` | Rewrite (see B). |
| `docker-compose.yml` | Comment mentioning `GROQ_API_KEY` → `OPENROUTER_API_KEY`. |
| `backend/app/services/llm_service.py` | Groq-specific comments (gpt-oss, `reasoning_effort`) go away with the file (see G). |

### B. New LLM layer (`backend/app/core/model_router.py`)
- Stage → model map:
  ```
  spec, clarify, classify_error, word_fix   → nemotron-3.5-lightning:free
  outline, storyboard, codegen, code_fix    → nemotron-3-ultra-550b-a55b:free
  visual_critic (images)                    → nemotron-3.5-super-vl:free
  ```
- Fallback chain Ultra → Super VL → Lightning via `models: [...]`. No fallback for vision critic.
- Two call types: `call_text(stage, system, user, schema=None)` and `call_vision(stage, prompt, images[])`.
- Structured output: JSON mode → Pydantic validation → one retry with the validation error.
- Redis-backed shared rate limiter (18 req/min) replacing per-process `aiolimiter`.
- Daily budget via `/api/v1/key` → `free_model_daily_requests.remaining` (cached ~60 s); below `LLM_DAILY_RESERVE` → `QuotaExhausted`.
- Retries: keep `tenacity` for 429/5xx; daily-cap 429 is treated as quota exhaustion (no retry).
- Hard `:free` guard on every call.
- Every call writes a `PipelineEvent` row (`model_used`, tokens, latency, status). Table already exists; nothing writes to it today.

### C. Orchestration: LangGraph → plain state machine
- **Delete** `backend/app/graphs/` (`video_graph.py`, `__init__.py`) and `backend/app/services/scene_service.py`.
- **New** `backend/app/pipeline/runner.py`: status → stage map; runs one stage, saves its artifact, advances status, enqueues the next Celery task; resumes from any status.
- Video statuses:
  ```
  CREATED → SPEC → TRACE → OUTLINE → STORYBOARD → AWAITING_APPROVAL
  → CODEGEN → QA → TTS → FINAL_RENDER → ASSEMBLE → COMPLETED
  (+ FAILED, WAITING_QUOTA)
  ```
- Scene statuses (separate): `PENDING → CODEGEN → STATIC_CHECK → PREVIEW → CRITIC → APPROVED → RENDERED / FAILED`.
- Retry limits: 3 code fixes → 1 regenerate → fallback scene. Critic max 2 rounds.

### D. Data model

| File | Change |
|---|---|
| `backend/app/db/models.py` | `Video`: add `spec`, `outline`, `storyboard_version`, `review_mode` (default true), `approved_at`, `current_stage`. Replace unused `script` with `outline`; keep `verified_trace`, `style_guide`. `Scene`: add `storyboard` (JSONB: beats, bookmarks, `start_state`, `end_state`, layout zones), `preview_url`, `qa_report`, `audio_hash`, `code_hash`. `SceneAttempt`: add `stage`, `error_class`, `critic_feedback`. |
| `backend/alembic/versions/0002_new_flow.py` | New migration for the columns above. |
| `backend/app/schemas/` | Replace `SceneDocument`, `QueuedResponse`, `PromptRequest/PromptResponse`. New: `Spec`, `TraceEvent`, `Outline`, `SceneBeat`, `Storyboard`, `QAReport`, `VideoOut`, `SceneOut`, `ProgressEvent`. |
| `backend/app/repository/scene_repository.py` + `sync_scene_repository.py` | Split into `video_repository` and `scene_repository` (async + sync). **Fix:** `update_scene_status` currently also overwrites `video.status` (1:1 coupling) — separate them. |

### E. New stage modules (`backend/app/stages/` and friends)

| Stage | Module | Model |
|---|---|---|
| [0]–[1] | `stages/spec.py` — prompt → `Spec`, word budget at 150 wpm, optional clarifying questions | Lightning |
| [2] | `app/ground_truth/` — `heap_sort.py`, `quick_sort.py`, `merge_sort.py`, `trace.py` (event schema), registry `spec.topic → function` | none |
| [3] | `stages/outline.py` | Ultra |
| [4] | `stages/storyboard.py` + `stages/storyboard_checks.py` (word budget ±10%, `trace_ref` exists, zones valid, start/end states line up); Lightning only for word-count fixes | Ultra |
| [5] | `stages/codegen.py` + `prompts/codegen/` (ManimCE 0.19 cheat sheet, 2–3 example scenes, component library API) | Ultra |
| [6] | `qa/static.py`, `qa/preview.py`, `qa/error_classifier.py`, `qa/geometry.py`, `qa/frames.py`, `qa/critic.py`, `qa/trace_check.py` | Ultra (fixes), VL (critic), Lightning (classification) |
| [7] | `tts/base.py` (`TTSProvider`), `tts/kokoro.py`, `tts/cache.py` | none |
| [8] | `assemble.py` — ffmpeg join, music ducking, -14 LUFS, `.srt`, thumbnail, final checks | none |
| [9] | `storage/` (`LocalStorage` now, S3/MinIO later, same interface) + SSE events | none |

Media layout:
```
media/{video_id}/scenes/{scene_id}_preview.mp4
media/{video_id}/scenes/{scene_id}.mp4
media/{video_id}/audio/{audio_hash}.wav
media/{video_id}/final.mp4
media/{video_id}/final.srt
media/{video_id}/thumbnail.png
```

### F. Component library (new package `backend/motion_lib/`)
- `theme.py` — colors, fonts.
- `zones.py` — TOP, CENTER, BOTTOM, LEFT, RIGHT screen areas.
- `array_bars.py` (`ArrayBars(values)`: `.swap(i, j)`, `.highlight(i)`, `.mark_sorted(i)`).
- `binary_tree.py` / `heap_tree.py` (`HeapTree(values)`: `.swap(i, j)`, `.link_to(array)`, `.shrink(n)`).
- `pointer.py`, `caption.py`.
- Every component exposes `.state()` (for trace check) and `.bbox()` (for geometry check).
- Tested by rendering each component on its own.
- This is the biggest engineering investment and the main quality lever.

### G. Existing code to rework

| File | Change |
|---|---|
| `backend/app/utils/script_validator.py` | Allow imports from `manim`, `manim_voiceover`, `motion_lib` (and `numpy`). Accept `VoiceoverScene`, `MovingCameraScene` (and other Scene subclasses) as bases. Check every Manim name exists in ManimCE 0.19. Block `getattr`, `__subclasses__`, `__globals__`, dunder access. Moves to `qa/static.py`. As written today it **rejects every scene the new flow produces**. |
| `backend/app/services/llm_service.py` | Delete. Prompts move into stage modules. The 20–35 s "Flash everything / Done!" prompt is dropped. `_clean_script` fence-stripping logic can be reused in codegen. |
| `backend/app/workers/render_task.py` | Split into Celery tasks: `run_stage`, `render_preview` (`-ql`), `render_final` (`-qh`), `synthesize_audio`, `assemble_video`. Per-scene timeouts (current single 120 s `-qm` cannot handle 8 scenes). |
| `backend/app/workers/celery_app.py` | Two queues: `llm` (concurrency 1–2, respects rate limit) and `render` (CPU-bound, concurrency = cores). |

### H. API

| File | Change |
|---|---|
| `backend/app/api/v1/routes/prompt.py` | → `POST /videos`: create job, return 202 immediately. **No LLM call inside the HTTP request** (today it calls the LLM synchronously inside the request). |
| `backend/app/api/v1/routes/scenes.py` | → `routes/videos.py`: `GET /videos`, `GET /videos/{id}`, `GET`/`PUT /videos/{id}/storyboard`, `POST /videos/{id}/approve`, `POST /videos/{id}/scenes/{sid}/regenerate`, `GET /videos/{id}/events` (SSE), `DELETE /videos/{id}`. Remove stale MongoDB references in docstrings. |
| `backend/app/api/v1/routes/health.py` | Add `/health/quota` — remaining OpenRouter requests. |
| `backend/app/api/v1/api_router.py` | Register the new routers. |

### I. Infrastructure and security

| File | Change |
|---|---|
| `backend/Dockerfile` | Split into `Dockerfile.api` (slim, no texlive) and `Dockerfile.worker` (texlive, ffmpeg, Cairo/Pango, Kokoro weights, `motion_lib`). |
| New sandbox | Render in a separate container: `--network none`, read-only filesystem except an output folder, CPU/memory/time limits, **no env secrets**. Worker passes code in, gets mp4 out. **Security gap today:** LLM-written code runs in the worker with `DATABASE_URL` and the API key in its environment; the AST check alone can be bypassed (e.g. `getattr`, `__subclasses__`). |
| `docker-compose.yml` | Services: `api`, `worker-llm`, `worker-render`, `sandbox` image, `postgres`, `redis`; `minio` later. |
| `backend/requirements.txt` | **Pin all versions.** `manim==0.19.*`, `manim-voiceover`, `kokoro`, `openai`, `redis`, `celery`, `pydantic`, etc. (Manim is unpinned today — its API can drift under the LLM.) |

### J. Tests

| File | Change |
|---|---|
| `backend/tests/unit/test_llm_service.py` | Rewrite → `test_model_router.py`: mock OpenRouter HTTP; test fallback chain, `:free` guard, quota exhaustion, JSON retry. |
| `backend/tests/integration/test_prompt_endpoint.py`, `test_scene_endpoints.py`, `conftest.py` | Rewrite for the `/videos` API. |
| `backend/tests/unit/test_scene_repository.py` | Rewrite for split video/scene repositories and decoupled statuses. |
| `backend/tests/test_validator.py` | Keep and extend (new allowlist, new base classes, blocked dunders). |
| New | Full coverage for `ground_truth/` (sorting correctness + exact trace events), `storyboard_checks`, `motion_lib`, `assemble`, runner status transitions. |

Do not delete old tests without replacements.

### K. Docs

- Delete `PRODUCTION_PLAN.md`, `PHASE_0_PLAN.md`, `.claude/BACKEND_PLAN.md`, `.claude/FRONTEND_PLAN.md` (all built around Groq/LangGraph). This file replaces them.
- New `docs/ARCHITECTURE.md` (flow, stages, models, quota rules).
- New `CLAUDE.md` with project rules: `:free` models only, no LangChain/LangGraph, ManimCE pinned, no LLM calls in HTTP requests, LLM code runs only in the sandbox.

### L. Frontend (`frontend/`) — build from scratch (currently Vite template)
- Prompt form (prompt + duration + audience + `review_mode`).
- Live progress over SSE.
- Storyboard review and editing (approve / edit beats).
- Scene preview grid with per-scene regenerate.
- Final player and download (mp4 + srt).
- Quota indicator (`/health/quota`).

### M. Unchanged
- `backend/app/core/logging.py`, `backend/app/core/limiter.py`
- `backend/app/db/base.py`, `backend/app/db/session.py`, `backend/app/db/sync_session.py`
- Alembic setup and `0001_initial_schema.py` migration
- Postgres and Redis containers
- `PipelineEvent` and `SceneAttempt` models (extended, not replaced)

---

## 6. Proposed implementation order (one step at a time)

Each step ends with something runnable/testable. Do not start a step until the previous one is verified.

1. **Docs + rules** — add `CLAUDE.md`, remove old plan docs (K).
2. **OpenRouter switch** — config, `.env.example`, `model_router.py` rewrite with `:free` guard, Redis rate limiter, quota check, `PipelineEvent` logging; remove LangChain/LangGraph deps (A, B). Keep the old single-shot flow working on OpenRouter as a smoke test.
3. **Pin dependencies + split Docker images** (I, partial).
4. **Data model** — migration `0002`, new schemas, split repositories, decouple statuses (D).
5. **State machine runner** — replace `graphs/` + `scene_service.py`; `POST /videos` returns 202, no LLM in request (C, H partial).
6. **Ground truth** — `ground_truth/` with heap/quick/merge sort traces + tests (E [2]).
7. **Spec + Outline + Storyboard + checks + approval pause** (E [1], [3], [4]; H storyboard/approve endpoints).
8. **Component library** `motion_lib/` (F).
9. **Codegen + static QA** (new validator) (E [5], G validator).
10. **Sandbox + preview render + error fix loop** (I sandbox, E [6] steps 2–3, G render tasks, Celery queues).
11. **Geometry + vision critic + trace check** (E [6] steps 4–6).
12. **TTS (Kokoro) + final render** (E [7]).
13. **Assemble + deliver + SSE** (E [8], [9]).
14. **Scene-level regenerate + quota endpoint** (H remaining).
15. **Frontend** (L).
16. **Test suite completion** (J).

---

## 7. Open items to verify during build
- Exact OpenRouter model ID for Nemotron 3.5 Lightning (free).
- Which of the three models reliably support JSON mode on OpenRouter.
- Kokoro CPU speed for ~750 words on the target machine.
- `manim-voiceover` compatibility with ManimCE 0.19.x and the Kokoro adapter.
