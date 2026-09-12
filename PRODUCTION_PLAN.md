# Code-Motion — Production-Grade Rebuild Plan (Backend First)

**Goal:** Produce videos from a text prompt that approach 3Blue1Brown-level polish — narrated, well-paced, visually consistent, self-reviewed — using only **free, open-source tooling** for everything (TTS, orchestration libraries) and **Groq's free-tier hosted models only** for every AI/LLM call. No paid APIs anywhere.

Frontend work is deliberately out of scope until this backend is solid. This document only covers the backend.

---

## 0. Guiding Principles

1. **Nothing paid, ever.** Every library is open-source and self-hostable. Every AI call goes through Groq's free tier. No OpenAI/Anthropic/ElevenLabs/paid-cloud-TTS calls anywhere in this plan.
2. **Don't trust the LLM with facts it doesn't need to invent.** Anywhere the "correct answer" can be computed deterministically (e.g. what bubble sort actually does to `[5,3,8,1]`), we compute it in plain Python and hand the LLM the verified result. The LLM's job is explaining and animating, never inventing algorithm mechanics.
3. **Every stage produces a structured, validated object** (Pydantic schema), never free-form text passed blindly to the next stage.
4. **Nothing is silently overwritten.** Every attempt (script draft, code draft, review verdict) is stored, not just the final one — needed for debugging and for the self-repair loop to work at all.
5. **Free-tier Groq rate limits are a real constraint, not a footnote.** One video will trigger many LLM calls (plan → script → per-scene code → review → repairs). The system must actively manage this (queueing, multi-model spreading, backoff), not hope it doesn't get rate-limited.
6. **Build in phases that each work end-to-end on their own.** Every phase below has its own milestone that can be demoed before starting the next.

---

## 1. Tech Stack Additions (on top of what already exists)

The current stack (FastAPI, Celery + Redis, Manim, LiteLLM) stays. **MongoDB is being replaced with PostgreSQL** (see Section 5 for why and the full schema) — everything else below is additive. Every item is free and open-source; licenses are noted because they matter for a "free-tier only, no paid" product.

| Purpose | Library | License | Why this one |
|---|---|---|---|
| Primary database | **PostgreSQL 16+** (replaces MongoDB) | PostgreSQL License | Our schema is relational (videos → scenes → attempts → events, all foreign-keyed), not document-shaped — Postgres fits it better, plus gives real transactions and `JSONB` for the genuinely flexible fields. See Section 5. |
| Async DB driver + ORM (FastAPI side) | `SQLAlchemy` (2.0, async engine) + `asyncpg` | MIT / Apache-2.0 | Current recommended combo for async FastAPI ↔ Postgres; replaces Motor |
| Sync DB driver (Celery worker side) | `SQLAlchemy` (sync engine) + `psycopg` (v3) | MIT / LGPL | Workers don't need async; a plain sync session is simpler and just as fast for the render task's DB updates; replaces PyMongo |
| Schema migrations | `Alembic` | MIT | Versioned, reviewable schema changes — the discipline Postgres wants in exchange for the structure it gives us |
| Agent orchestration (the "team of workers" graph) | `langgraph` | MIT | Purpose-built for exactly this: multi-step AI workflows with loops, retries, and state tracking |
| LLM call plumbing / structured output | `langchain`, `langchain-groq` | MIT | Official first-party Groq integration; built-in Pydantic-validated structured output so every stage returns a typed object, not raw text |
| Retry/backoff on LLM calls | `tenacity` | Apache-2.0 | Handles Groq free-tier 429s gracefully instead of failing the whole job |
| Client-side rate limiting | `aiolimiter` | MIT | Keeps our own call rate under Groq's free-tier RPM/TPM caps proactively, instead of just reacting to errors |
| Voiceover framework for Manim | `manim-voiceover` | MIT | Official Manim Community plugin. Gives a `with self.voiceover(text=...)` pattern that auto-times animations to narration length — this is the single most important library for closing the "no voice" gap |
| Open-source TTS engine | **Kokoro-82M** via `kokoro-manim-voiceover` | Apache-2.0 | See research below — best free/open TTS for this use case |
| Word-level narration↔animation alignment (optional, later) | `openai-whisper` (run locally, offline) | MIT | Used internally by manim-voiceover for precise word-timed triggers; runs fully offline, no API cost |
| Audio/video stitching, mixing narration + music | `ffmpeg` (already required by Manim) | LGPL/GPL (tool, not linked into our code) | No new dependency — reuse what Manim already needs |
| Optional future: grounding non-algorithmic explanations | `chromadb` + `sentence-transformers` | Apache-2.0 | Only if/when we support open-ended concepts beyond concrete algorithms (see Phase 2 note) — not needed for the core algorithm-visualization use case because of principle #2 |

---

## 2. AI Model Strategy — Groq Free Tier Only

Groq's free tier (checked live, Sept 2026) gives access to several models with no credit card, each with its own separate rate-limit bucket. Note: `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` were deprecated by Groq in June 2026 — the plan below uses their recommended replacements.

| Model (Groq id) | Free-tier limits (approx.) | Role in our pipeline |
|---|---|---|
| `openai/gpt-oss-120b` | 30 req/min, 1,000 req/day, 8,000 tokens/min, 200,000 tokens/day | The "senior" model — used for the steps that need real judgment: **scriptwriting/narrative**, **quality review/critique** |
| `openai/gpt-oss-20b` | Same bucket shape as above, separate quota from 120b | The "workhorse" model — used for **high-volume, more mechanical** steps: per-scene Manim code generation, first-pass repairs |
| `qwen/qwen3.6-27b` | Separate quota again | Third lane, used for **storyboard breakdown** and as an overflow lane when gpt-oss buckets are near their cap |
| `whisper-large-v3` / `-turbo` (Groq-hosted) | Separate audio quota | **Not used** — we run Whisper locally/offline instead (see Phase 1) so narration alignment never competes with our text-generation quota |

**Why spread across three models instead of one:** a single video needs roughly: 1 scriptwriting call + 1 storyboard call + N scene-code calls (N = number of scenes, e.g. 4–8) + up to N review calls + occasional repair calls. At 30 requests/minute on one model, that's tight. Splitting mechanical/high-volume work onto `gpt-oss-20b` and `qwen3.6-27b`, and reserving `gpt-oss-120b` only for the two steps that truly need it, roughly triples the effective free throughput.

**How we enforce this in practice:**
- A small internal **"model router"** picks the model per pipeline node (not a new library — just a config mapping of `node_name → groq_model_id`, easy to change later).
- `aiolimiter` throttles our own outgoing request rate per model so we approach but don't exceed the documented RPM/TPM, rather than firing and hoping.
- `tenacity` retries with exponential backoff on any 429 that slips through, before Celery ever sees a failure.
- Celery is still what queues the actual jobs, so if free-tier limits are genuinely maxed out, a video's generation just waits its turn instead of failing.

---

## 3. Voice Strategy (closing the biggest gap — no narration today)

**Chosen stack:** `manim-voiceover` (the sync framework, official Manim plugin) + **Kokoro-82M** (the actual voice model) wired together via the existing `kokoro-manim-voiceover` adapter package.

Why Kokoro specifically, based on current comparisons of open-source TTS models:
- **Apache-2.0** — fully free for commercial use, no "contact us" licensing gate (unlike Coqui XTTS v2, which is CPML-licensed and requires contacting Coqui for commercial use; and unlike F5-TTS, which is non-commercial-only).
- Tiny footprint (82M parameters, runs on CPU or a small GPU, 2–3GB) — cheap to self-host, no paid cloud GPU required.
- 54 voices across 8 languages, natural-sounding, faster than real-time generation.
- Already has a ready-made integration (`kokoro-manim-voiceover`) that plugs straight into `manim-voiceover`'s `set_speech_service()` pattern — minimal glue code needed.

How it changes the render pipeline: instead of the Manim script calling `self.wait(0.6)` on fixed timers, scenes are written using `with self.voiceover(text="...") as tracker:` blocks. Kokoro generates the audio for that line, `manim-voiceover` measures its real duration, and the animation inside that block automatically stretches or waits to match — this is exactly the "visuals follow the voice" principle 3Blue1Brown videos are built on, not the reverse.

**Word-level alignment (nice-to-have, later):** `manim-voiceover` can optionally use offline Whisper to figure out exactly when each word is spoken, so an animation can trigger on a specific word instead of just "at the start of this sentence." We run this locally (`openai-whisper`, MIT-licensed) — not through Groq — since it's a one-off local computation, not something that needs a hosted model, and it keeps this feature free and independent of our LLM rate-limit budget.

---

## 4. Script Accuracy Strategy (making generation "very strong and accurate")

This is the most important architectural decision in this whole plan, and it's not really a library — it's a design principle:

> **For anything we can compute exactly, compute it. Only ask the LLM to explain and animate a verified answer — never to invent the answer.**

Concretely: for algorithm/data-structure prompts (which is the app's core use case), we build a small internal **"reference trace" module** — plain, well-tested Python implementations of the actual algorithms (bubble sort, merge sort, quicksort, binary search, BFS/DFS, stack/queue/linked-list/tree operations, Dijkstra, etc.), instrumented to record every intermediate state as structured data (e.g. `[{"array": [5,3,8,1], "comparing": [0,1], "action": "compare"}, ...]`).

This is **not a pip package** — it's project code we own and unit-test, because correctness here is the whole point and we want full control over it. It sits alongside the existing AST validator as a second, equally important safety net — one guarantees the code is *safe to run*, this one guarantees the content is *factually correct*.

The pipeline then becomes:
1. User prompt → figure out which algorithm/operation is being asked for.
2. Run the real Python implementation → get a **verified, exact trace** of what actually happens.
3. Hand that verified trace to the LLM and ask it to write the narration script and storyboard *around it* — the LLM is telling the story of real data, not guessing what bubble sort does.
4. Later, at code-generation time, the LLM turns each storyboard beat + its slice of the verified trace into Manim code — again, translating known-correct data into visuals, not inventing the sequence of events.

On top of that ground-truth layer, every stage's output is still schema-validated:
- **Structured output everywhere:** `langchain-groq`'s built-in Pydantic structured-output support means the scriptwriter node must return a real `ScriptOutput` object (hook, sections, full narration text), the storyboard node must return a real `list[SceneBeat]`, etc. — never "usually valid JSON," always schema-checked or rejected outright.
- **Prompt templating:** a lightweight `Jinja2`-based template per node keeps prompts consistent and easy to iterate on without string-concatenation spaghetti.
- **The critique loop (Phase 5)** is the second layer of accuracy — after generation, a reviewer step checks the *script* against the verified trace (did the narration describe something that didn't actually happen?) in addition to checking pacing/clarity.

*Future-only, not needed yet:* if the product later expands beyond concrete algorithms into open-ended concept explanations (e.g. "explain eigenvalues" — something with no single deterministic trace), that's when a small local RAG layer (`chromadb` + a local open-source embedding model via `sentence-transformers`, both free/offline) would make sense, to ground the script in a curated reference text instead of pure LLM memory. Not part of the current phases.

---

## 5. Data Storage Architecture

**PostgreSQL replaces MongoDB.** The reasoning: a video is now made of *many* independently-generated, independently-rendered scenes, plus a growing amount of pipeline metadata that must be kept, not overwritten — that's a clean parent/child relational shape (`videos` 1→N `scenes` 1→N `scene_attempts`, plus `pipeline_events` referencing both), not a pile of loosely-shaped documents. Postgres gives us foreign keys and real transactions for that structure, while `JSONB` columns still give us schema-flexibility exactly where we want it (the style guide, the verified trace, event summaries) — so we're not giving up anything Mongo offered, just adding the guarantees Mongo didn't.

Primary keys are UUIDs throughout (generated in application code, not auto-incrementing integers) — this matters because scene IDs get referenced across the API, Celery task payloads, and file paths, and we want them globally unique without a DB round-trip to mint one.

### `videos` table (one row per user request — the "project")
| Column | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `user_prompt` | text | the raw input, never modified |
| `title` | text | derived short title for history/browsing |
| `status` | enum/text | `planning → scripting → storyboarding → generating_scenes → rendering → stitching → completed / failed` |
| `script` | `JSONB` | `{ hook, sections[], full_text }` — the finalized narration |
| `verified_trace` | `JSONB`, nullable | the deterministic ground-truth data from Section 4 (only present for algorithm-type prompts) |
| `style_guide` | `JSONB` | `{ color_map: {concept → color}, recurring_visual_motifs: [...] }` — shared visual language every scene must follow, so colors/motifs stay consistent across the *whole* video |
| `final_video_url`, `final_audio_url` | text, nullable | |
| `duration_seconds` | numeric, nullable | |
| `error_message` | text, nullable | |
| `created_at`, `updated_at` | timestamptz | |

### `scenes` table (one row per storyboard beat, FK to its parent video)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `video_id` | UUID, **FK → videos.id**, `ON DELETE CASCADE` | deleting a video cleans up its scenes automatically |
| `order` | integer | position in the video |
| `narration_text` | text | this scene's slice of the script |
| `narration_audio_url` | text, nullable | |
| `narration_duration_seconds` | numeric, nullable | |
| `visual_description` | text | what the storyboard says should be on screen |
| `generated_script` | text, nullable | the current/selected Manim code for just this scene |
| `status` | enum/text | its own state machine: `pending → generating_code → validating → rendering → completed / failed` |
| `rendered_segment_url` | text, nullable | this scene's individual rendered clip, before stitching |
| `error_message` | text, nullable | |
| `created_at`, `updated_at` | timestamptz | |

Index on `(video_id, order)` — this is the query used constantly (fetch a video's scenes in order).

### `scene_attempts` table (full version history — nothing gets silently thrown away)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `scene_id` | UUID, **FK → scenes.id**, `ON DELETE CASCADE` | |
| `attempt_number` | integer | |
| `generated_script` | text | |
| `validation_result` | `JSONB` | |
| `reviewer_feedback` | `JSONB`, nullable | |
| `is_selected` | boolean | whether this attempt is the one actually used |
| `created_at` | timestamptz | |

### `pipeline_events` table (observability — every AI decision, queryable)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID, PK | |
| `video_id` | UUID, **FK → videos.id** | |
| `scene_id` | UUID, **FK → scenes.id**, nullable | |
| `node_name` | text | e.g. `scriptwriter`, `storyboard`, `scene_codegen`, `critic` |
| `model_used` | text | |
| `tokens_in`, `tokens_out`, `latency_ms` | integer | |
| `status` | text | ok / error |
| `input_summary`, `output_summary` | `JSONB` | |
| `created_at` | timestamptz | |

This gives a permanent, inspectable log of *why* a given video turned out the way it did — which model wrote which line, what the reviewer said, how many repairs happened — queryable with plain SQL, without paying for a third-party observability SaaS.

**Migrations:** every schema change (new column, new table, new enum value) goes through an `Alembic` migration file, checked into the repo. This is the one real discipline cost of leaving Mongo, and it's a worthwhile trade for not being able to accidentally write an inconsistent document.

### Media files (unchanged storage location, better organization)
Keep the existing local-disk `MEDIA_DIR` (already a Docker volume — free, self-hosted), just organized more deliberately:
```
media/{video_id}/scenes/{scene_id}.mp4      ← per-scene rendered clip
media/{video_id}/audio/{scene_id}.wav       ← per-scene narration audio
media/{video_id}/final.mp4                  ← stitched, final output
```
If/when this ever needs to scale beyond one host, the natural next step is **MinIO** (open-source, S3-compatible, self-hostable) — noted here as a future option, not part of the current phases.

---

## 6. Phase-by-Phase Plan (Backend Only)

### Phase 0 — Platform Foundations (prerequisite for everything below)
**Goal:** Get the new plumbing in place before any new AI behavior is built on top of it.
- Swap MongoDB for **PostgreSQL** in `docker-compose.yml` (replace the `mongodb` service with `postgres:16`); add `sqlalchemy`, `asyncpg`, `psycopg`, `alembic`, `langgraph`, `langchain`, `langchain-groq`, `tenacity`, `aiolimiter` to `requirements.txt`.
- Write the initial `Alembic` migration creating the `videos`, `scenes`, `scene_attempts`, `pipeline_events` tables (Section 5), and rewrite `app/db/` and `app/repository/` (currently Motor/PyMongo-based) as SQLAlchemy async (API) and sync (Celery worker) equivalents.
- Build the **model router** (Groq model per pipeline node + rate limiting/backoff, Section 2).
- Migrate the existing single-table scene model's data/logic into the new `videos` / `scenes` split. Existing simple prompt→script→render flow keeps working during this — it just now writes into the new tables.
- Stand up the empty LangGraph skeleton (a graph with one pass-through node) wired into `scene_service.py` so later phases only ever add nodes, never restructure the graph.
- **Milestone:** submitting a prompt still works exactly as it does today, but now runs against Postgres via `videos` + `scenes` rows, and every LLM call is going through the new router/rate-limiter.

### Phase 1 — Give It a Voice
**Goal:** Every rendered scene has real narration, and the animation timing follows the narration, not a fixed timer.
- Add `manim-voiceover`, `kokoro-manim-voiceover`, Kokoro model weights to the render worker image.
- Update the Manim code-generation prompt so the LLM writes scenes using `with self.voiceover(text=...)` blocks instead of raw `self.wait()` calls.
- Update the render task to generate the narration audio (Kokoro) as part of rendering each scene, store it via `narration_audio_url`.
- **Milestone:** a generated video has an actual spoken voice, and pausing/pacing visibly follows the narration length instead of fixed waits.

### Phase 2 — Teach It to Write a Story, Not a List of Steps
**Goal:** A dedicated scriptwriting stage produces a real narrated explanation with a hook → build-up → payoff arc, grounded in the verified algorithm trace.
- Build the deterministic **reference-trace module** (Section 4) for the initial set of supported algorithms/structures.
- Add a `scriptwriter` LangGraph node (model: `gpt-oss-120b`) that takes the user prompt + verified trace and returns a structured `ScriptOutput` (Pydantic schema: hook, sections, full narration text).
- This script is what gets stored in `videos.script` and is the single source of truth everything downstream uses.
- **Milestone:** given the same algorithm, the system produces a coherent narrated explanation with an opening hook and a clear payoff, and the facts in it always match the verified trace.

### Phase 3 — Teach It to Plan the Shots Before Drawing Them
**Goal:** Break the finished script into a timed storyboard of scene beats before any code is written.
- Add a `storyboard` LangGraph node (model: `qwen/qwen3.6-27b`) that splits `script.sections` into an ordered `list[SceneBeat]` (narration slice + visual description per beat), persisted as `scenes` documents (status `pending`).
- Scene code-generation now runs **per scene**, using that scene's beat + its slice of the verified trace — not the whole video in one giant prompt.
- **Milestone:** a single prompt produces multiple scene documents, each with its own narration slice and visual description, in the correct order.

### Phase 4 — Fix the Animation Style Itself
**Goal:** Visuals feel like continuous, deliberate motion with a consistent visual language, not blocks flashing in and out.
- Rewrite the Manim system prompt to favor `Transform`/`ReplacementTransform`-based morphing and camera `MovingCameraScene` pans/zooms over the current Flash/Indicate/FadeOut style.
- Generate a `style_guide` (color map + recurring visual motifs) once per video (during Phase 3's storyboard step or right after), store it on the `videos` document, and inject it into **every** scene's code-generation prompt so a concept keeps the same color for the entire video, not just within one scene.
- **Milestone:** side-by-side, a generated video visibly reads as one consistent piece rather than disconnected clips — same colors, smoother motion, camera that moves with intent.

### Phase 5 — Add a Real Quality Reviewer
**Goal:** A dedicated critique step checks pacing, clarity, and factual match to the verified trace — and sends specific feedback back for a bounded number of repairs, exactly the LangGraph loop pattern from the earlier orchestration plan.
- Add a `critic` LangGraph node (model: `gpt-oss-120b`) that scores each generated scene (and, at a higher level, the whole script) against a checklist: matches the verified trace, matches the storyboard's intent, isn't rushed, isn't confusing.
- On failure, feedback routes back to the relevant node (scriptwriter or scene-codegen) with the specific issue; capped at 2 repair attempts, matching the existing validator's repair-loop pattern.
- Every attempt (pass or fail) is written to `scene_attempts`, never overwritten.
- **Milestone:** a deliberately bad or confusing scene gets caught and rewritten automatically, with the full before/after trail visible in `scene_attempts`.

### Phase 6 — Add Music and Sound
**Goal:** Videos no longer feel silent/sterile.
- Curate a small library of royalty-free / CC0 ambient background tracks (sourced, not generated — this is asset curation, not a code library).
- Extend the final assembly step (Phase 9) to mix a background bed under the narration using `ffmpeg`'s audio filters, ducked lower during speech.
- **Milestone:** final videos have a subtle, appropriately-timed music bed that doesn't compete with narration.

### Phase 7 — Build a Personal Toolbox of Visual Building Blocks
**Goal:** Stop having the LLM invent every shape/layout from scratch — the biggest lever for consistent visual polish, mirroring how 3Blue1Brown reuses his own custom Mobject classes.
- Build an internal Python library of well-designed, tested Manim components matching the visualization patterns already described in the current system prompt (stacks, queues, sorting bars, linked lists, trees/graphs) — but as real reusable classes, not re-described in every prompt.
- Update code-generation prompts to *compose* from this library (e.g. `AlgoBar`, `StackBlock`, `TreeNode` components) instead of drawing raw `Rectangle`/`Circle` primitives every time.
- **Milestone:** two different videos using "sorting bars" look visually identical in style/quality, because they're built from the same underlying component, not two independent LLM guesses.

### Phase 8 — Let a Person Weigh In Before the Expensive Part Happens
**Goal:** Expose the script/storyboard for review/editing before committing to full rendering (still backend-only — just the API surface; a UI comes later with the frontend phase).
- Add endpoints to fetch a video's current `script` and `scenes` (beats) mid-pipeline, and to edit/approve them, pausing the graph at a checkpoint until approval is given.
- **Milestone:** the pipeline can be told to stop after storyboarding and wait for an explicit "approved" signal via API before scene rendering begins.

### Phase 9 — Multi-Scene Stitching & Long-Form Output
**Goal:** Combine independently rendered scenes into one continuous final video, supporting genuinely longer videos instead of one short clip.
- Add a final Celery task that concatenates all `rendered_segment_url` clips in order via `ffmpeg`, mixes in the music bed from Phase 6, and writes `videos.final_video_url`.
- Handle partial failure gracefully (if one scene fails validation/rendering after all repair attempts, the video is marked `failed` with a clear pointer to which scene broke, rather than silently producing a broken final cut).
- **Milestone:** a multi-scene prompt produces one single, continuously narrated final video file, in the correct order, with music — end to end, the full 3Blue1Brown-style pipeline working together.

---

## 7. Cross-Cutting Production Concerns (apply across all phases)

- **Cost/rate-limit control:** the model router + `aiolimiter` + `tenacity` combo (Section 2) is not optional polish — without it, Phase 3 onward (many LLM calls per video) will simply start failing under Groq's free-tier caps.
- **Observability:** every LangGraph node write to `pipeline_events` (Section 5) from Phase 0 onward, not bolted on later — otherwise debugging *why* a video came out wrong becomes guesswork.
- **Backward compatibility during migration:** Phase 0's schema split should keep the existing `GET/DELETE /scenes`, `POST /prompt` endpoints working (now backed by the new collections) so nothing currently working breaks while this is built incrementally.
- **Testing:** the deterministic reference-trace module (Section 4) is the easiest, highest-value thing to get full unit-test coverage on, since it has no AI involved and is exactly the kind of thing that must never be wrong.

---

## 8. Explicitly Deferred

- **Frontend** — not touched until this backend is solid, per direction. `FRONTEND_PLAN.md` gets revisited once the API surface here (especially Phase 8's review/approval endpoints and Phase 3's per-scene structure) is stable, since the UI needs to reflect the new multi-scene, multi-stage pipeline rather than the old single-shot flow.
- **RAG/vector search for open-ended (non-algorithmic) concepts** — noted in Section 4 as a future option, not needed for the current algorithm-visualization scope.
- **Moving media storage to MinIO/S3** — noted in Section 5 as a future scaling step, not needed at current scale.

---

## Sources consulted for this plan

- [How I animate 3Blue1Brown — Grant Sanderson](https://3blue1brown.substack.com/p/how-i-animate-3blue1brown)
- [3Blue1Brown — Wikipedia](https://en.wikipedia.org/wiki/3Blue1Brown)
- [Grant Sanderson — Dwarkesh Podcast interview](https://www.dwarkesh.com/p/grant-sanderson)
- [manim-voiceover — GitHub (ManimCommunity)](https://github.com/ManimCommunity/manim-voiceover)
- [kokoro-manim-voiceover — GitHub](https://github.com/xposed73/kokoro-manim-voiceover) / [PyPI](https://pypi.org/project/kokoro-manim-voiceover/)
- [Best Open-Source TTS Models 2026 — CodeSOTA](https://www.codesota.com/speech/best-open-source)
- [Kokoro vs XTTS vs Chatterbox — Local AI Master](https://localaimaster.com/blog/kokoro-vs-xtts-vs-chatterbox)
- [Groq Pricing & Free Tier 2026 — eesel AI](https://www.eesel.ai/blog/groq-pricing)
- [Groq Free Tier Limits 2026 — Grizzly Peak Software](https://www.grizzlypeaksoftware.com/articles/p/groq-api-free-tier-limits-in-2026-what-you-actually-get-uwysd6mb)
- [Groq Model Deprecations — GroqDocs](https://console.groq.com/docs/deprecations)
- [LangChain structured output docs](https://docs.langchain.com/oss/python/langchain/structured-output)
