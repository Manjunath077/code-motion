from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId  # type: ignore[import]
from app.db.mongodb import get_db
from app.schemas.scene_schema import SceneDocument, SceneStatus
from app.core.logging import get_logger

logger = get_logger(__name__)


def _doc_to_scene(doc: dict) -> SceneDocument:
    return SceneDocument(
        id=str(doc["_id"]),
        prompt=doc["prompt"],
        generated_script=doc.get("generated_script"),
        status=doc["status"],
        video_url=doc.get("video_url"),
        error_message=doc.get("error_message"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def create_scene(prompt: str) -> SceneDocument:
    db = get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "prompt": prompt,
        "generated_script": None,
        "status": SceneStatus.PENDING,
        "video_url": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.scenes.insert_one(doc)
    doc["_id"] = result.inserted_id
    logger.info("Scene created: %s", str(result.inserted_id))
    return _doc_to_scene(doc)


async def get_scene_by_id(scene_id: str) -> Optional[SceneDocument]:
    db = get_db()
    try:
        oid = ObjectId(scene_id)
    except Exception:
        return None
    doc = await db.scenes.find_one({"_id": oid})
    return _doc_to_scene(doc) if doc else None


async def list_scenes(limit: int = 20, skip: int = 0) -> tuple[list[SceneDocument], int]:
    db = get_db()
    total = await db.scenes.count_documents({})
    cursor = db.scenes.find({}).sort("created_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [_doc_to_scene(d) for d in docs], total


async def update_scene_status(scene_id: str, status: SceneStatus, **kwargs) -> None:
    db = get_db()
    fields = {"status": status, "updated_at": datetime.now(timezone.utc)}
    fields.update(kwargs)
    await db.scenes.update_one({"_id": ObjectId(scene_id)}, {"$set": fields})
    logger.info("Scene %s status → %s", scene_id, status)


async def delete_scene(scene_id: str) -> bool:
    db = get_db()
    try:
        oid = ObjectId(scene_id)
    except Exception:
        return False
    result = await db.scenes.delete_one({"_id": oid})
    return result.deleted_count > 0


async def update_scene_script(scene_id: str, script: str) -> None:
    db = get_db()
    await db.scenes.update_one(
        {"_id": ObjectId(scene_id)},
        {"$set": {"generated_script": script, "updated_at": datetime.now(timezone.utc)}},
    )


async def update_scene_video(scene_id: str, video_url: str) -> None:
    db = get_db()
    await db.scenes.update_one(
        {"_id": ObjectId(scene_id)},
        {"$set": {"video_url": video_url, "updated_at": datetime.now(timezone.utc)}},
    )
