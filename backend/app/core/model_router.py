"""Groq free-tier model routing (see PRODUCTION_PLAN.md Section 2).

Every LLM call in the app goes through `call_llm(node_name, ...)`. Which Groq
model handles a given pipeline node is decided here, once, in `NODE_MODEL_MAP`
— nowhere else in the codebase should reference a Groq model id directly.
Only "scene_codegen" is populated in Phase 0; later phases add
"scriptwriter" / "storyboard" / "critic" entries as those nodes are built.
"""
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from aiolimiter import AsyncLimiter
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

NODE_MODEL_MAP: dict[str, str] = {
    "scene_codegen": "openai/gpt-oss-20b",
}

# Free-tier RPM per model is documented at 30/min (see PRODUCTION_PLAN.md
# Section 2) — stay a little under that rather than racing the exact cap.
_RATE_LIMIT_RPM = 28

_limiters: dict[str, AsyncLimiter] = {}
_clients: dict[str, ChatGroq] = {}


def _limiter_for(model: str) -> AsyncLimiter:
    if model not in _limiters:
        _limiters[model] = AsyncLimiter(_RATE_LIMIT_RPM, time_period=60)
    return _limiters[model]


def _client_for(model: str) -> ChatGroq:
    if model not in _clients:
        kwargs = dict(
            model=model,
            api_key=settings.GROQ_API_KEY,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
            # Room for a few-hundred-line script, not just the model's internal
            # reasoning — gpt-oss models "think" before answering (visible as
            # reasoning_content) and will burn the whole budget on that alone if
            # max_tokens is left at langchain-groq's small default. 8000 is well
            # under gpt-oss-20b's ~32k completion cap.
            max_tokens=8000,
        )
        if "gpt-oss" in model:
            # Less internal deliberation for a fairly mechanical code-gen task —
            # leaves more of max_tokens for the actual answer. Not a universal
            # Groq param, so only set it for the reasoning-model family that has it.
            kwargs["reasoning_effort"] = "low"
        _clients[model] = ChatGroq(**kwargs)
    return _clients[model]


@retry(reraise=True, stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=1, max=20))
async def call_llm(node_name: str, system_prompt: str, user_prompt: str) -> str:
    """Route an LLM call through the Groq model assigned to this pipeline node,
    rate-limited to stay under the free-tier cap and retried with backoff on
    transient failures (e.g. a 429 that slips past the limiter)."""
    model = NODE_MODEL_MAP[node_name]
    client = _client_for(model)

    async with _limiter_for(model):
        logger.info("Calling Groq model %s for node '%s'", model, node_name)
        response = await client.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        )

    if response.response_metadata.get("finish_reason") == "length":
        raise RuntimeError(
            f"Groq response for node '{node_name}' (model {model}) was truncated "
            "before producing an answer — it likely spent its token budget on "
            "internal reasoning. Raise max_tokens or lower reasoning_effort in "
            "app/core/model_router.py."
        )

    return response.content
