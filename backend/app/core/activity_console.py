"""Prints the pipeline activity feed (app/core/activity.py) in the API's log.

Started by the API lifespan as a background task. It reads only events
published after the API started (from the stream's last entry at start-up),
so a restart does not replay history. Each event becomes one bordered block, e.g.:

┌─ LLM ANSWER ────────────────────────────────────────── 17:50:41 · worker ┐
│ video      4ae8067c-6ebf-4131-b816-1fb414480b9a                          │
│ stage      codegen                                                       │
│ model      nvidia/nemotron-3-ultra-550b-a55b:free                        │
│ took       56.7 s                                                        │
└──────────────────────────────────────────────────────────────────────────┘

Colour (green finished, red failed, yellow stuck/quota, cyan LLM) only when
stdout is a terminal, so redirected logs stay plain text.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime

from app.core import redis_client
from app.core.activity import STREAM
from app.core.logging import _utf8_stdout, get_logger

logger = get_logger(__name__)

_WIDTH = 76          # total box width, borders included
_LABEL = 10          # width of the label column
_BLOCK_MS = 5000     # XREAD block time
_RETRY_S = 5         # wait after a Redis error

# kind → (title, colour)
_GREEN, _RED, _YELLOW, _CYAN, _BLUE, _MAGENTA = "32", "31", "33", "36", "34", "35"
KINDS: dict[str, tuple[str, str]] = {
    "video_created": ("VIDEO CREATED", _BLUE),
    "stage_queued": ("STAGE QUEUED", _BLUE),
    "stage_started": ("WORKER STARTED STAGE", _MAGENTA),
    "stage_finished": ("WORKER FINISHED STAGE", _GREEN),
    "stage_failed": ("WORKER STAGE FAILED", _RED),
    "waiting_quota": ("WAITING FOR LLM QUOTA", _YELLOW),
    "llm_call": ("LLM CALL", _CYAN),
    "llm_answer": ("LLM ANSWER", _CYAN),
    "llm_error": ("LLM ERROR", _RED),
    "rate_limit_wait": ("LLM RATE LIMIT — WAITING", _YELLOW),
    "render_started": ("RENDER STARTED", _MAGENTA),
    "render_finished": ("RENDER FINISHED", _GREEN),
    "render_failed": ("RENDER FAILED", _RED),
    "video_stuck": ("VIDEO STUCK — RE-QUEUED", _YELLOW),
    "video_resumed": ("VIDEO RESUMED", _BLUE),
    "video_completed": ("VIDEO COMPLETED", _GREEN),
    "video_failed": ("VIDEO FAILED", _RED),
}

# Plain formatter: the block carries its own time and source.
_out = logging.getLogger("activity")
if not _out.handlers:
    _handler = logging.StreamHandler(_utf8_stdout())
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _out.addHandler(_handler)
    _out.setLevel(logging.INFO)
    _out.propagate = False


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def render(fields: dict, colour: bool = False) -> str:
    """One event as a bordered block (plain text unless colour=True)."""
    kind = fields.get("kind", "?")
    title, code = KINDS.get(kind, (kind.upper(), _BLUE))
    try:
        when = datetime.fromtimestamp(float(fields.get("ts", 0))).strftime("%H:%M:%S")
    except ValueError:
        when = "--:--:--"
    right = f" {when} · {fields.get('source', '?')} "
    left = f"─ {title} "
    inner = _WIDTH - 2
    top = "┌" + left + "─" * max(inner - len(left) - len(right), 1) + right + "┐"

    rows: list[tuple[str, str]] = []
    if fields.get("video_id"):
        rows.append(("video", fields["video_id"]))
    if fields.get("scene_id"):
        rows.append(("scene", fields["scene_id"]))
    try:
        details = json.loads(fields.get("details") or "{}")
    except ValueError:
        details = {"details": fields.get("details")}
    for key, value in details.items():
        if value is None or value == "":
            continue
        for i, line in enumerate(str(value).splitlines() or [""]):
            rows.append((key if i == 0 else "", line))

    text_w = _WIDTH - _LABEL - 5  # "│ " + label + " " + text + " │"
    body = [f"│ {label:<{_LABEL}} {_fit(value, text_w):<{text_w}} │" for label, value in rows[:12]]
    bottom = "└" + "─" * inner + "┘"
    lines = [top, *body, bottom]
    if colour:
        lines = [f"\x1b[{code}m{line}\x1b[0m" for line in lines]
    return "\n".join(lines)


async def run() -> None:
    """Print every new activity event until cancelled. Survives Redis outages."""
    colour = sys.stdout.isatty()
    last_id = None
    while True:
        try:
            async with redis_client.get_redis() as r:
                if last_id is None:
                    # Start after the newest entry. Not "$" in the loop: "$" is
                    # re-evaluated per XREAD, so events published between two
                    # reads would be skipped.
                    newest = await r.xrevrange(STREAM, count=1)
                    last_id = newest[0][0] if newest else "0-0"
                while True:
                    reply = await r.xread({STREAM: last_id}, block=_BLOCK_MS, count=100)
                    for _stream, entries in reply or []:
                        for entry_id, fields in entries:
                            last_id = entry_id
                            _out.info(render(fields, colour=colour))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Activity console: Redis unavailable (%s) — retrying in %d s", e, _RETRY_S)
            await asyncio.sleep(_RETRY_S)
