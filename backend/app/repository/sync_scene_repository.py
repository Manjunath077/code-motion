from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId  # type: ignore[import]
from app.db.sync_mongodb import get_sync_db
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


def get_scene_by_id_sync(scene_id: str) -> Optional[SceneDocument]:
    db = get_sync_db()
    try:
        oid = ObjectId(scene_id)
    except Exception:
        return None
    doc = db.scenes.find_one({"_id": oid})
    return _doc_to_scene(doc) if doc else None


def update_scene_status_sync(scene_id: str, status: SceneStatus, **kwargs) -> None:
    db = get_sync_db()
    fields = {"status": status, "updated_at": datetime.now(timezone.utc)}
    fields.update(kwargs)
    db.scenes.update_one({"_id": ObjectId(scene_id)}, {"$set": fields})
    logger.info("Scene %s status → %s", scene_id, status)


def update_scene_video_sync(scene_id: str, video_url: str) -> None:
    db = get_sync_db()
    db.scenes.update_one(
        {"_id": ObjectId(scene_id)},
        {"$set": {"video_url": video_url, "updated_at": datetime.now(timezone.utc)}},
    )
