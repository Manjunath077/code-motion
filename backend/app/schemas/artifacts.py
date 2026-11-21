"""Pipeline artifacts — what each stage produces and the next stage consumes.

Shapes follow the worked heap-sort example in NEW_PLAN.md section 3. Each
schema is refined in the step that first produces it; fields may be added,
but these are the contract between stages.
"""
import re
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

WORDS_PER_MINUTE = 150
_BOOKMARK = re.compile(r"<bookmark[^>]*/>")


class _Strict(BaseModel):
    # LLM output is parsed into these models: unknown keys are an error,
    # not something to silently drop.
    model_config = ConfigDict(extra="forbid")


# ── [1] Spec ──────────────────────────────────────────────────────────────────

class Domain(str, Enum):
    ALGORITHM = "algorithm"
    MATH = "math"
    PHYSICS = "physics"
    OTHER = "other"


class Spec(_Strict):
    topic: str = Field(..., min_length=1, max_length=200)
    domain: Domain
    audience: str = Field(..., min_length=1, max_length=200)
    duration_s: int = Field(..., ge=30, le=900)
    words_budget: int = Field(..., gt=0)
    style: str = "dark-3b1b-like"
    learning_goals: list[str] = Field(..., min_length=1, max_length=12)

    @staticmethod
    def budget_for(duration_s: int) -> int:
        """~150 spoken words per minute."""
        return round(duration_s * WORDS_PER_MINUTE / 60)


# ── [2] Ground truth ──────────────────────────────────────────────────────────

class TraceOp(str, Enum):
    COMPARE = "compare"
    SWAP = "swap"
    SHRINK = "shrink"
    SET = "set"
    MARK_SORTED = "mark_sorted"


class TraceEvent(_Strict):
    """One step of a real, instrumented run. `index` is its position in the
    trace and is what storyboard beats reference via `trace_ref`."""
    index: int = Field(..., ge=0)
    op: TraceOp
    phase: Optional[str] = None
    i: Optional[int] = Field(None, ge=0)
    j: Optional[int] = Field(None, ge=0)
    value: Optional[int] = None
    heap_size: Optional[int] = Field(None, ge=0)

    @model_validator(mode="after")
    def _operands(self):
        if self.op in (TraceOp.COMPARE, TraceOp.SWAP) and (self.i is None or self.j is None):
            raise ValueError(f"'{self.op.value}' needs both i and j")
        if self.op == TraceOp.SHRINK and self.heap_size is None:
            raise ValueError("'shrink' needs heap_size")
        if self.op in (TraceOp.SET, TraceOp.MARK_SORTED) and self.i is None:
            raise ValueError(f"'{self.op.value}' needs i")
        return self


class Trace(_Strict):
    input: list[int] = Field(..., min_length=1)
    events: list[TraceEvent]
    output: list[int]

    @model_validator(mode="after")
    def _indexes_sequential(self):
        for position, event in enumerate(self.events):
            if event.index != position:
                raise ValueError(f"event at position {position} has index {event.index}")
        return self


# ── [3] Outline ───────────────────────────────────────────────────────────────

SceneRole = Literal["hook", "intuition", "mechanism", "example", "why", "recap"]


class OutlineScene(_Strict):
    id: str = Field(..., pattern=r"^S\d{1,2}$")
    title: str = Field(..., min_length=1, max_length=120)
    role: SceneRole
    duration_s: int = Field(..., gt=0)
    content: str = Field(..., min_length=1)


class Outline(_Strict):
    title: str = Field(..., min_length=1, max_length=200)
    scenes: list[OutlineScene] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [s.id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene ids must be unique")
        return self

    @property
    def total_duration_s(self) -> int:
        return sum(s.duration_s for s in self.scenes)


# ── [4] Storyboard ────────────────────────────────────────────────────────────

class Zone(str, Enum):
    """Named screen areas; layout never uses free coordinates."""
    TOP = "TOP_ZONE"
    CENTER = "CENTER_ZONE"
    BOTTOM = "BOTTOM_ZONE"
    LEFT = "LEFT_ZONE"
    RIGHT = "RIGHT_ZONE"


class SceneBeat(_Strict):
    """Narration and visual written together. Bookmarks in the narration
    (<bookmark mark='cmp'/>) mark the word where an animation fires."""
    narration: str = Field(..., min_length=1)
    visual: str = Field(..., min_length=1)
    trace_ref: list[int] = Field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(_BOOKMARK.sub(" ", self.narration).split())


class Storyboard(_Strict):
    id: str = Field(..., pattern=r"^S\d{1,2}$")
    duration_s: int = Field(..., gt=0)
    start_state: str
    end_state: str
    beats: list[SceneBeat] = Field(..., min_length=1)
    layout: dict[str, Zone] = Field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return sum(b.word_count for b in self.beats)


# ── [6] QA ────────────────────────────────────────────────────────────────────

class QACheck(str, Enum):
    STATIC = "static"
    PREVIEW = "preview"
    GEOMETRY = "geometry"
    CRITIC = "critic"
    TRACE = "trace"


class QAIssue(_Strict):
    check: QACheck
    severity: Literal["error", "warning"]
    message: str
    bookmark: Optional[str] = None


class QAReport(_Strict):
    passed: bool
    checks_run: list[QACheck] = Field(default_factory=list)
    issues: list[QAIssue] = Field(default_factory=list)
    fix_attempts: int = Field(0, ge=0)
    critic_rounds: int = Field(0, ge=0)
