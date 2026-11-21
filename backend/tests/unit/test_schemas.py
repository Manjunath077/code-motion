"""Artifact schemas: the contract between pipeline stages."""
import pytest
from pydantic import ValidationError

from app.schemas.artifacts import (
    Domain, Outline, OutlineScene, QAReport, SceneBeat, Spec, Storyboard, Trace, TraceEvent, TraceOp, Zone,
)
from app.schemas.status import VIDEO_HALT_STATUSES, VideoStatus

HEAP_SPEC = {
    "topic": "Heap Sort", "domain": "algorithm", "audience": "CS undergrad",
    "duration_s": 300, "words_budget": 750, "style": "dark-3b1b-like",
    "learning_goals": ["max-heap property", "array↔tree mapping", "sift-down"],
}


# ── Spec ──────────────────────────────────────────────────────────────────────

def test_spec_parses_plan_example():
    spec = Spec.model_validate(HEAP_SPEC)
    assert spec.domain == Domain.ALGORITHM


def test_spec_rejects_unknown_keys():
    with pytest.raises(ValidationError):
        Spec.model_validate({**HEAP_SPEC, "extra": 1})


def test_spec_rejects_unknown_domain():
    with pytest.raises(ValidationError):
        Spec.model_validate({**HEAP_SPEC, "domain": "cooking"})


def test_word_budget_150_wpm():
    assert Spec.budget_for(300) == 750
    assert Spec.budget_for(60) == 150


# ── Trace ─────────────────────────────────────────────────────────────────────

def test_trace_event_ops_need_operands():
    TraceEvent(index=0, op="compare", phase="build", i=3, j=7)
    TraceEvent(index=1, op="shrink", heap_size=7)
    with pytest.raises(ValidationError):
        TraceEvent(index=0, op="swap", i=3)
    with pytest.raises(ValidationError):
        TraceEvent(index=0, op="shrink")


def test_trace_indexes_must_be_sequential():
    events = [TraceEvent(index=0, op=TraceOp.SWAP, i=0, j=1), TraceEvent(index=2, op=TraceOp.SWAP, i=0, j=1)]
    with pytest.raises(ValidationError):
        Trace(input=[2, 1], events=events, output=[1, 2])


# ── Outline ───────────────────────────────────────────────────────────────────

def _scene(sid: str, seconds: int) -> OutlineScene:
    return OutlineScene(id=sid, title="t", role="mechanism", duration_s=seconds, content="c")


def test_outline_total_duration():
    assert Outline(title="Heap Sort", scenes=[_scene("S1", 25), _scene("S2", 45)]).total_duration_s == 70


def test_outline_rejects_duplicate_ids():
    with pytest.raises(ValidationError):
        Outline(title="x", scenes=[_scene("S1", 10), _scene("S1", 10)])


def test_outline_scene_id_format():
    with pytest.raises(ValidationError):
        _scene("scene-1", 10)


# ── Storyboard ────────────────────────────────────────────────────────────────

def test_storyboard_parses_plan_example_and_counts_words_without_bookmarks():
    sb = Storyboard.model_validate({
        "id": "S4", "duration_s": 45,
        "start_state": "array top, tree bottom, values from trace step 0",
        "end_state": "node 4 settled at index 3",
        "beats": [
            {"narration": "Suppose the root breaks the rule. <bookmark mark='cmp'/>Compare it with both children",
             "visual": "highlight root yellow; at 'cmp' pulse children", "trace_ref": [12, 13]},
            {"narration": "Swap with the larger one", "visual": "swap in tree AND array"},
        ],
        "layout": {"array": "TOP_ZONE", "tree": "CENTER_ZONE", "caption": "BOTTOM_ZONE"},
    })

    assert sb.layout["tree"] == Zone.CENTER
    assert sb.beats[0].word_count == 11
    assert sb.word_count == 16


def test_storyboard_rejects_free_coordinates_as_zone():
    with pytest.raises(ValidationError):
        Storyboard(
            id="S1", duration_s=10, start_state="", end_state="",
            beats=[SceneBeat(narration="n", visual="v")], layout={"array": "[0, 2, 0]"},
        )


def test_storyboard_needs_beats():
    with pytest.raises(ValidationError):
        Storyboard(id="S1", duration_s=10, start_state="", end_state="", beats=[])


# ── QA / statuses ─────────────────────────────────────────────────────────────

def test_qa_report_defaults():
    report = QAReport(passed=True)
    assert report.issues == [] and report.fix_attempts == 0


def test_halt_statuses():
    assert VIDEO_HALT_STATUSES == {VideoStatus.FAILED, VideoStatus.WAITING_QUOTA}
