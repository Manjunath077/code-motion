"""Generate → validate → repair loop, and the separate video/scene statuses it sets."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.scene_service as svc
from app.schemas.status import SceneStatus, VideoStatus
from app.utils.script_validator import ValidationResult

VALID = ValidationResult(is_valid=True, error="")
INVALID = ValidationResult(is_valid=False, error="banned import 'os'")


@pytest.fixture
def mocks(monkeypatch):
    m = {
        "generate": AsyncMock(return_value="script-0"),
        "fix": AsyncMock(side_effect=["script-1", "script-2"]),
        "validate": MagicMock(return_value=VALID),
        "scene_status": AsyncMock(),
        "video_status": AsyncMock(),
        "render": MagicMock(),
    }
    monkeypatch.setattr(svc, "generate_manim_script", m["generate"])
    monkeypatch.setattr(svc, "fix_manim_script", m["fix"])
    monkeypatch.setattr(svc, "validate_manim_script", m["validate"])
    monkeypatch.setattr(svc, "update_scene_status", m["scene_status"])
    monkeypatch.setattr(svc, "update_video_status", m["video_status"])
    monkeypatch.setattr(svc, "render_scene", m["render"])
    return m


def _statuses(mock) -> list:
    return [c.args[1] for c in mock.await_args_list]


async def test_valid_first_time_no_repair(mocks):
    await svc.generate_and_queue("v1", "s1", "prompt")

    mocks["fix"].assert_not_awaited()
    mocks["render"].delay.assert_called_once_with("s1")
    assert _statuses(mocks["scene_status"]) == [
        SceneStatus.CODEGEN, SceneStatus.STATIC_CHECK, SceneStatus.APPROVED,
    ]
    assert mocks["scene_status"].await_args_list[-1].kwargs == {"generated_script": "script-0"}
    assert _statuses(mocks["video_status"]) == [VideoStatus.CODEGEN, VideoStatus.FINAL_RENDER]


async def test_one_repair_then_valid(mocks):
    mocks["validate"].side_effect = [INVALID, VALID]

    await svc.generate_and_queue("v1", "s1", "prompt")

    assert mocks["fix"].await_count == 1
    assert mocks["scene_status"].await_args_list[-1].kwargs == {"generated_script": "script-1"}


async def test_gives_up_after_two_repairs(mocks):
    mocks["validate"].return_value = INVALID

    with pytest.raises(svc.ScriptValidationError):
        await svc.generate_and_queue("v1", "s1", "prompt")

    assert mocks["fix"].await_count == 2
    mocks["render"].delay.assert_not_called()
    assert _statuses(mocks["scene_status"])[-1] == SceneStatus.FAILED
    assert _statuses(mocks["video_status"])[-1] == VideoStatus.FAILED


async def test_llm_error_marks_both_failed_and_reraises(mocks):
    mocks["generate"].side_effect = RuntimeError("OpenRouter down")

    with pytest.raises(RuntimeError):
        await svc.generate_and_queue("v1", "s1", "prompt")

    for mock, status in ((mocks["scene_status"], SceneStatus.FAILED), (mocks["video_status"], VideoStatus.FAILED)):
        last = mock.await_args_list[-1]
        assert last.args[1] == status
        assert last.kwargs["error_message"] == "OpenRouter down"


async def test_queue_failure_marks_both_failed(mocks):
    mocks["render"].delay.side_effect = ConnectionError("redis down")

    with pytest.raises(RuntimeError, match="Queue dispatch failed"):
        await svc.generate_and_queue("v1", "s1", "prompt")

    assert _statuses(mocks["scene_status"])[-1] == SceneStatus.FAILED
    assert _statuses(mocks["video_status"])[-1] == VideoStatus.FAILED
