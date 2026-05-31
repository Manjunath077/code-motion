from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from app.repository.scene_repository import (
    create_scene,
    get_scene_by_id,
    update_scene_status,
    delete_scene,
    list_scenes,
)
from app.schemas.scene_schema import SceneStatus


# ── helpers ───────────────────────────────────────────────────────────────────

def _scene_doc(oid=None):
    oid = oid or ObjectId()
    return {
        "_id": oid,
        "prompt": "test prompt",
        "generated_script": None,
        "status": SceneStatus.PENDING,
        "video_url": None,
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def _mock_collection():
    col = MagicMock()
    col.insert_one = AsyncMock()
    col.find_one = AsyncMock()
    col.update_one = AsyncMock()
    col.delete_one = AsyncMock()
    col.count_documents = AsyncMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    col.find.return_value = cursor
    return col, cursor


def _mock_db(col):
    db = MagicMock()
    db.scenes = col
    return db


# ── create_scene ──────────────────────────────────────────────────────────────

async def test_create_scene_returns_scene_document():
    col, _ = _mock_collection()
    oid = ObjectId()
    col.insert_one.return_value = MagicMock(inserted_id=oid)

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        scene = await create_scene("test prompt")

    assert scene.id == str(oid)
    assert scene.prompt == "test prompt"
    assert scene.status == SceneStatus.PENDING
    assert scene.generated_script is None
    col.insert_one.assert_called_once()


# ── get_scene_by_id ───────────────────────────────────────────────────────────

async def test_get_scene_by_id_found():
    col, _ = _mock_collection()
    doc = _scene_doc()
    col.find_one.return_value = doc

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        scene = await get_scene_by_id(str(doc["_id"]))

    assert scene is not None
    assert scene.id == str(doc["_id"])
    assert scene.prompt == "test prompt"


async def test_get_scene_by_id_not_found_returns_none():
    col, _ = _mock_collection()
    col.find_one.return_value = None

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        scene = await get_scene_by_id(str(ObjectId()))

    assert scene is None


async def test_get_scene_by_id_invalid_id_returns_none():
    db = MagicMock()
    with patch("app.repository.scene_repository.get_db", return_value=db):
        scene = await get_scene_by_id("not-a-valid-objectid")
    assert scene is None


# ── update_scene_status ───────────────────────────────────────────────────────

async def test_update_scene_status_calls_update_one():
    col, _ = _mock_collection()
    scene_id = str(ObjectId())

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        await update_scene_status(scene_id, SceneStatus.COMPLETED)

    col.update_one.assert_called_once()
    _, update_arg = col.update_one.call_args[0]
    assert update_arg["$set"]["status"] == SceneStatus.COMPLETED


async def test_update_scene_status_with_extra_kwargs():
    col, _ = _mock_collection()
    scene_id = str(ObjectId())

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        await update_scene_status(scene_id, SceneStatus.FAILED, error_message="boom")

    _, update_arg = col.update_one.call_args[0]
    assert update_arg["$set"]["error_message"] == "boom"


# ── delete_scene ──────────────────────────────────────────────────────────────

async def test_delete_scene_returns_true_when_deleted():
    col, _ = _mock_collection()
    col.delete_one.return_value = MagicMock(deleted_count=1)

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        result = await delete_scene(str(ObjectId()))

    assert result is True


async def test_delete_scene_returns_false_when_not_found():
    col, _ = _mock_collection()
    col.delete_one.return_value = MagicMock(deleted_count=0)

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        result = await delete_scene(str(ObjectId()))

    assert result is False


async def test_delete_scene_invalid_id_returns_false():
    db = MagicMock()
    with patch("app.repository.scene_repository.get_db", return_value=db):
        result = await delete_scene("bad-id")
    assert result is False


# ── list_scenes ───────────────────────────────────────────────────────────────

async def test_list_scenes_returns_list_and_total():
    col, cursor = _mock_collection()
    docs = [_scene_doc(), _scene_doc()]
    col.count_documents.return_value = 2
    cursor.to_list.return_value = docs

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        scenes, total = await list_scenes(limit=20, skip=0)

    assert len(scenes) == 2
    assert total == 2


async def test_list_scenes_empty():
    col, cursor = _mock_collection()
    col.count_documents.return_value = 0
    cursor.to_list.return_value = []

    with patch("app.repository.scene_repository.get_db", return_value=_mock_db(col)):
        scenes, total = await list_scenes()

    assert scenes == []
    assert total == 0
