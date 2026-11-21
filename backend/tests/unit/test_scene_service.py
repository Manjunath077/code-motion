"""Generate → validate → repair loop (replaced the LangGraph graph in step 2)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.scene_service as svc
from app.schemas.scene_schema import SceneStatus
from app.utils.script_validator import ValidationResult

VALID = ValidationResult(is_valid=True, error="")
INVALID = ValidationResult(is_valid=False, error="banned import 'os'")


@pytest.fixture
def mocks(monkeypatch):
    m = {
        "generate": AsyncMock(return_value="script-0"),
        "fix": AsyncMock(side_effect=["script-1", "script-2"]),
        "validate": MagicMock(return_value=VALID),
        "status": AsyncMock(),
        "save": AsyncMock(),
        "render": MagicMock(),
    }
    monkeypatch.setattr(svc, "generate_manim_script", m["generate"])
    monkeypatch.setattr(svc, "fix_manim_script", m["fix"])
    monkeypatch.setattr(svc, "validate_manim_script", m["validate"])
    monkeypatch.setattr(svc, "update_scene_status", m["status"])
    monkeypatch.setattr(svc, "update_scene_script", m["save"])
    monkeypatch.setattr(svc, "render_scene", m["render"])
    return m


async def test_valid_first_time_no_repair(mocks):
    await svc.generate_and_queue("s1", "prompt")

    mocks["fix"].assert_not_awaited()
    mocks["save"].assert_awaited_once_with("s1", "script-0")
    mocks["render"].delay.assert_called_once_with("s1")
    assert mocks["status"].await_args_list[-1].args == ("s1", SceneStatus.QUEUED)


async def test_one_repair_then_valid(mocks):
    mocks["validate"].side_effect = [INVALID, VALID]

    await svc.generate_and_queue("s1", "prompt")

    assert mocks["fix"].await_count == 1
    mocks["save"].assert_awaited_once_with("s1", "script-1")


async def test_gives_up_after_two_repairs(mocks):
    mocks["validate"].return_value = INVALID

    with pytest.raises(svc.ScriptValidationError):
        await svc.generate_and_queue("s1", "prompt")

    assert mocks["fix"].await_count == 2
    mocks["save"].assert_not_awaited()
    assert mocks["status"].await_args_list[-1].args == ("s1", SceneStatus.FAILED)


async def test_llm_error_marks_failed_and_reraises(mocks):
    mocks["generate"].side_effect = RuntimeError("OpenRouter down")

    with pytest.raises(RuntimeError):
        await svc.generate_and_queue("s1", "prompt")

    last = mocks["status"].await_args_list[-1]
    assert last.args == ("s1", SceneStatus.FAILED)
    assert last.kwargs["error_message"] == "OpenRouter down"
