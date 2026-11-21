"""OpenRouter model router — all network, Redis and DB access mocked."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError
from tenacity import wait_none

import app.core.model_router as router
from app.core.config import Settings, settings
from app.core.model_router import LLMError, PaidModelError, QuotaExhausted, call_text

ULTRA, VL, LIGHTNING = settings.MODEL_ULTRA, settings.MODEL_VL, settings.MODEL_LIGHTNING


def _response(content="hello", finish_reason="stop", model=ULTRA, usage=(11, 22)):
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None,
        choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=content))],
    )


def _http_error(cls, status):
    resp = httpx.Response(status, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    return cls(f"HTTP {status}", response=resp, body=None)


class _FakeClient:
    def __init__(self, create: AsyncMock):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def llm(monkeypatch):
    """Mocked OpenRouter: `llm.create` is the chat.completions.create call."""
    create = AsyncMock(return_value=_response())
    ensure_quota = AsyncMock()
    acquire = AsyncMock()
    record = AsyncMock()
    monkeypatch.setattr(router, "_make_client", lambda: _FakeClient(create))
    monkeypatch.setattr(router.quota, "ensure_quota", ensure_quota)
    monkeypatch.setattr(router.rate_limiter, "acquire", acquire)
    monkeypatch.setattr(router, "record_event", record)
    monkeypatch.setattr(router, "_RETRY_WAIT", wait_none())
    return SimpleNamespace(create=create, ensure_quota=ensure_quota, acquire=acquire, record=record)


# ── routing ──────────────────────────────────────────────────────────────────

async def test_codegen_routes_to_ultra_with_fallback_chain(llm):
    assert await call_text("codegen", "sys", "user") == "hello"

    kwargs = llm.create.await_args.kwargs
    assert kwargs["model"] == ULTRA
    assert kwargs["extra_body"] == {"models": [ULTRA, VL, LIGHTNING]}
    assert kwargs["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}]
    assert "response_format" not in kwargs  # unsupported on the :free Ultra/Lightning endpoints


async def test_spec_routes_to_lightning_first(llm):
    await call_text("spec", "sys", "user")

    kwargs = llm.create.await_args.kwargs
    assert kwargs["model"] == LIGHTNING
    assert kwargs["extra_body"] == {"models": [LIGHTNING, ULTRA, VL]}


async def test_unknown_stage_raises(llm):
    with pytest.raises(ValueError):
        await call_text("nope", "sys", "user")
    llm.create.assert_not_awaited()


async def test_every_call_goes_through_quota_and_rate_limiter(llm):
    await call_text("codegen", "sys", "user")
    llm.ensure_quota.assert_awaited_once()
    llm.acquire.assert_awaited_once()


# ── :free guard ──────────────────────────────────────────────────────────────

async def test_paid_model_refused_per_call(llm, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_VL", "nvidia/nemotron-3.5-super-vl")  # fallback entry, no :free

    with pytest.raises(PaidModelError):
        await call_text("codegen", "sys", "user")
    llm.create.assert_not_awaited()


def test_paid_model_refused_at_boot():
    with pytest.raises(ValidationError, match=":free"):
        Settings(OPENROUTER_API_KEY="k", MODEL_ULTRA="nvidia/nemotron-3-ultra-550b-a55b")


# ── retries and quota ────────────────────────────────────────────────────────

async def test_retries_on_server_error(llm):
    llm.create.side_effect = [_http_error(openai.InternalServerError, 503), _response()]

    assert await call_text("codegen", "sys", "user") == "hello"
    assert llm.create.await_count == 2


async def test_retries_on_connection_error(llm):
    llm.create.side_effect = [openai.APIConnectionError(request=httpx.Request("POST", "https://x")), _response()]

    assert await call_text("codegen", "sys", "user") == "hello"
    assert llm.create.await_count == 2


async def test_gives_up_after_max_attempts(llm):
    llm.create.side_effect = _http_error(openai.InternalServerError, 500)

    with pytest.raises(openai.InternalServerError):
        await call_text("codegen", "sys", "user")
    assert llm.create.await_count == router._MAX_ATTEMPTS


async def test_per_minute_429_is_retried(llm):
    llm.create.side_effect = [_http_error(openai.RateLimitError, 429), _response()]

    assert await call_text("codegen", "sys", "user") == "hello"
    llm.ensure_quota.assert_any_await(force_refresh=True)


async def test_daily_cap_429_raises_quota_exhausted_without_retry(llm):
    llm.create.side_effect = _http_error(openai.RateLimitError, 429)
    # Pre-call check passes; the re-check after the 429 shows the cap is hit.
    llm.ensure_quota.side_effect = [None, QuotaExhausted("0 left")]

    with pytest.raises(QuotaExhausted):
        await call_text("codegen", "sys", "user")
    assert llm.create.await_count == 1


async def test_quota_exhausted_before_call(llm):
    llm.ensure_quota.side_effect = QuotaExhausted("0 left")

    with pytest.raises(QuotaExhausted):
        await call_text("codegen", "sys", "user")
    llm.create.assert_not_awaited()


async def test_client_error_not_retried(llm):
    llm.create.side_effect = _http_error(openai.BadRequestError, 400)

    with pytest.raises(openai.BadRequestError):
        await call_text("codegen", "sys", "user")
    assert llm.create.await_count == 1


# ── bad answers ──────────────────────────────────────────────────────────────

async def test_truncated_response_raises(llm):
    llm.create.return_value = _response(content="partial", finish_reason="length")

    with pytest.raises(LLMError, match="truncated"):
        await call_text("codegen", "sys", "user")
    assert llm.create.await_count == 1


async def test_empty_response_raises(llm):
    llm.create.return_value = _response(content=None)

    with pytest.raises(LLMError):
        await call_text("codegen", "sys", "user")


# ── structured output ────────────────────────────────────────────────────────

class _Spec(BaseModel):
    topic: str
    duration_s: int


async def test_schema_returns_validated_model(llm):
    llm.create.return_value = _response('```json\n{"topic": "Heap Sort", "duration_s": 300}\n```')

    result = await call_text("spec", "sys", "user", schema=_Spec)

    assert result == _Spec(topic="Heap Sort", duration_s=300)
    system = llm.create.await_args.kwargs["messages"][0]["content"]
    assert "JSON schema" in system and "duration_s" in system


async def test_schema_retries_once_with_validation_error(llm):
    llm.create.side_effect = [
        _response('{"topic": "Heap Sort"}'),
        _response('{"topic": "Heap Sort", "duration_s": 300}'),
    ]

    result = await call_text("spec", "sys", "user", schema=_Spec)

    assert result.duration_s == 300
    retry_messages = llm.create.await_args_list[1].kwargs["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": '{"topic": "Heap Sort"}'}
    assert "duration_s" in retry_messages[-1]["content"]


async def test_schema_invalid_twice_raises(llm):
    llm.create.return_value = _response("not json at all")

    with pytest.raises(LLMError, match="invalid JSON twice"):
        await call_text("spec", "sys", "user", schema=_Spec)
    assert llm.create.await_count == 2


# ── PipelineEvent logging ────────────────────────────────────────────────────

async def test_success_records_event(llm):
    llm.create.return_value = _response(model=VL)  # answered by a fallback model

    await call_text("codegen", "sys", "user", scene_id="scene-1")

    kwargs = llm.record.await_args.kwargs
    assert kwargs["node_name"] == "codegen"
    assert kwargs["status"] == "ok"
    assert kwargs["scene_id"] == "scene-1"
    assert kwargs["model_used"] == VL
    assert (kwargs["tokens_in"], kwargs["tokens_out"]) == (11, 22)
    assert isinstance(kwargs["latency_ms"], int)


async def test_missing_usage_is_tolerated(llm):
    llm.create.return_value = _response(usage=None)

    await call_text("codegen", "sys", "user")

    kwargs = llm.record.await_args.kwargs
    assert kwargs["tokens_in"] is None and kwargs["tokens_out"] is None


async def test_failed_attempts_are_recorded(llm):
    llm.create.side_effect = [_http_error(openai.InternalServerError, 500), _response()]

    await call_text("codegen", "sys", "user")

    statuses = [c.kwargs["status"] for c in llm.record.await_args_list]
    assert statuses == ["error", "ok"]
