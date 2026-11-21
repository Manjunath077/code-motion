"""OpenRouter model routing — free models only (NEW_PLAN.md Section 4).

Every LLM call in the app goes through `call_text(stage, ...)`. Which model
handles a stage is decided here, once, in `STAGE_MODEL`, by naming a setting
(MODEL_ULTRA / MODEL_VL / MODEL_LIGHTNING) — model IDs live in config only.

Per call:
  1. :free guard on every model ID in the request (a non-:free ID bills credits).
  2. Daily quota check (QuotaExhausted below LLM_DAILY_RESERVE).
  3. Shared Redis rate limiter (LLM_RPM across API + all workers).
  4. Request with OpenRouter's `models: [...]` fallback chain.
  5. One PipelineEvent row per attempt.
Transient failures (429 rate limit, 5xx, timeout, connection) are retried with
backoff; a 429 caused by the daily cap becomes QuotaExhausted (no retry).

`call_vision` (visual critic, MODEL_VL, no fallback) is added in step 11.
"""
import json
import time
from typing import Optional, Type, TypeVar, Union

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.core import quota, rate_limiter
from app.core.config import settings
from app.core.logging import get_logger
from app.core.quota import QuotaExhausted
from app.repository.pipeline_event_repository import IdLike, record_event

logger = get_logger(__name__)

# Stage → name of the setting that holds its model ID.
STAGE_MODEL: dict[str, str] = {
    "spec": "MODEL_LIGHTNING",
    "clarify": "MODEL_LIGHTNING",
    "classify_error": "MODEL_LIGHTNING",
    "word_fix": "MODEL_LIGHTNING",
    "outline": "MODEL_ULTRA",
    "storyboard": "MODEL_ULTRA",
    "codegen": "MODEL_ULTRA",
    "code_fix": "MODEL_ULTRA",
}

# Fallback order for text calls; the stage's own model always goes first.
TEXT_FALLBACK_ORDER = ("MODEL_ULTRA", "MODEL_VL", "MODEL_LIGHTNING")

_MAX_ATTEMPTS = 4
# Module-level so tests can swap in a zero wait.
_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=20)

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model answered, but not with something usable."""


class PaidModelError(LLMError):
    """A model ID without the ':free' suffix reached a call."""


def _models_for(stage: str) -> list[str]:
    if stage not in STAGE_MODEL:
        raise ValueError(f"Unknown LLM stage '{stage}' — add it to STAGE_MODEL in app/core/model_router.py")
    primary = getattr(settings, STAGE_MODEL[stage])
    chain = [primary]
    for name in TEXT_FALLBACK_ORDER:
        model = getattr(settings, name)
        if model not in chain:
            chain.append(model)
    return chain


def _assert_free(models: list[str]) -> None:
    for model in models:
        if not model.endswith(":free"):
            raise PaidModelError(f"Refusing to call non-free model '{model}'")


def _make_client() -> AsyncOpenAI:
    # SDK retries off: tenacity is the only retry layer, so every attempt goes
    # through the quota check and rate limiter and is logged exactly once.
    return AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        timeout=settings.LLM_TIMEOUT,
        max_retries=0,
    )


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, APIConnectionError):  # includes APITimeoutError
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


async def _attempt(
    stage: str, models: list[str], messages: list[dict], video_id: IdLike, scene_id: IdLike
) -> str:
    """One request to OpenRouter. Returns the reply text."""
    _assert_free(models)
    await quota.ensure_quota()
    await rate_limiter.acquire()

    event = dict(node_name=stage, video_id=video_id, scene_id=scene_id)
    input_summary = {"chars": sum(len(m["content"]) for m in messages), "models": models}
    started = time.monotonic()

    try:
        async with _make_client() as client:
            response = await client.chat.completions.create(
                model=models[0],
                messages=messages,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
                extra_body={"models": models},
            )
    except RateLimitError:
        latency_ms = int((time.monotonic() - started) * 1000)
        await record_event(**event, status="rate_limited", latency_ms=latency_ms, input_summary=input_summary)
        # A 429 is either the per-minute limit (retry) or the daily cap (stop).
        # Re-read the real remaining count to tell which.
        await quota.ensure_quota(force_refresh=True)
        raise
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        await record_event(
            **event, status="error", latency_ms=latency_ms, input_summary=input_summary,
            output_summary={"error": f"{type(e).__name__}: {e}"[:500]},
        )
        raise

    latency_ms = int((time.monotonic() - started) * 1000)
    model_used = response.model
    # Free endpoints don't always report usage.
    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else None
    tokens_out = usage.completion_tokens if usage else None
    choice = response.choices[0] if response.choices else None
    finish_reason = choice.finish_reason if choice else None
    content = (choice.message.content or "") if choice else ""

    if finish_reason == "length" or not content.strip():
        await record_event(
            **event, status="truncated", model_used=model_used, tokens_in=tokens_in, tokens_out=tokens_out,
            latency_ms=latency_ms, input_summary=input_summary,
            output_summary={"finish_reason": finish_reason, "chars": len(content)},
        )
        # These models reason before answering, and reasoning tokens count
        # toward max_tokens — an empty or cut-off answer usually means the
        # budget went on reasoning.
        raise LLMError(
            f"Response for stage '{stage}' (model {model_used}) was empty or truncated "
            f"(finish_reason={finish_reason!r}). Raise LLM_MAX_TOKENS if this repeats."
        )

    await record_event(
        **event, status="ok", model_used=model_used, tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=latency_ms, input_summary=input_summary,
        output_summary={"finish_reason": finish_reason, "chars": len(content)},
    )
    logger.info("LLM stage '%s' answered by %s in %d ms", stage, model_used, latency_ms)
    return content


async def _request(
    stage: str, models: list[str], messages: list[dict], video_id: IdLike, scene_id: IdLike
) -> str:
    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(_MAX_ATTEMPTS),
        wait=_RETRY_WAIT,
        reraise=True,
    ):
        with attempt:
            content = await _attempt(stage, models, messages, video_id, scene_id)
    return content


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may be fenced or chatty."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse(text: str, schema: Type[T]) -> T:
    return schema.model_validate_json(_extract_json(text))


async def call_text(
    stage: str,
    system: str,
    user: str,
    schema: Optional[Type[T]] = None,
    *,
    video_id: IdLike = None,
    scene_id: IdLike = None,
) -> Union[str, T]:
    """Text LLM call for a pipeline stage.

    Without `schema`, returns the reply text. With a Pydantic `schema`, asks for
    JSON matching it and returns a validated instance, retrying once with the
    validation error. JSON is requested in the prompt, not via response_format:
    the :free Ultra and Lightning endpoints do not support response_format.
    """
    models = _models_for(stage)

    if schema is not None:
        system = (
            f"{system}\n\nRespond with ONLY a JSON object (no prose, no markdown fences) "
            f"matching this JSON schema:\n{json.dumps(schema.model_json_schema())}"
        )

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    content = await _request(stage, models, messages, video_id, scene_id)

    if schema is None:
        return content

    try:
        return _parse(content, schema)
    except ValidationError as e:
        logger.warning("Stage '%s' returned invalid JSON, retrying once: %s", stage, str(e)[:200])
        error = str(e)

    retry_messages = messages + [
        {"role": "assistant", "content": content},
        {
            "role": "user",
            "content": (
                f"Your reply did not match the schema. Validation error:\n{error}\n\n"
                "Reply again with ONLY the corrected JSON object."
            ),
        },
    ]
    content = await _request(stage, models, retry_messages, video_id, scene_id)
    try:
        return _parse(content, schema)
    except ValidationError as e:
        raise LLMError(f"Stage '{stage}' returned invalid JSON twice: {e}") from e


__all__ = ["call_text", "LLMError", "PaidModelError", "QuotaExhausted", "STAGE_MODEL"]
