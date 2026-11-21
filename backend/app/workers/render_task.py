import shutil
import subprocess
import tempfile
from pathlib import Path

from app.workers.celery_app import celery_app
from app.repository.sync_scene_repository import get_scene_sync, update_scene_status_sync
from app.repository.sync_video_repository import update_video_status_sync
from app.schemas.status import SceneStatus, VideoStatus
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def scene_media_path(video_id: str, scene_id: str) -> tuple[Path, str]:
    """(file on disk, public URL) — media/{video_id}/scenes/{scene_id}.mp4."""
    relative = f"{video_id}/scenes/{scene_id}.mp4"
    return Path(settings.MEDIA_DIR) / relative, f"/media/{relative}"


@celery_app.task(bind=True, name="render_scene", max_retries=1)
def render_scene(self, scene_id: str):
    logger.info("Render task started for scene %s", scene_id)

    scene = get_scene_sync(scene_id)
    if not scene:
        logger.error("Scene %s not found", scene_id)
        return
    video_id = str(scene.video_id)

    def fail(message: str) -> None:
        update_scene_status_sync(scene_id, SceneStatus.FAILED, error_message=message)
        update_video_status_sync(video_id, VideoStatus.FAILED, error_message=message)

    if not scene.generated_script:
        fail("Scene has no script")
        return

    tmp_root = Path(tempfile.mkdtemp())
    scene_dir = tmp_root / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    script_path = scene_dir / "scene.py"
    script_path.write_text(scene.generated_script, encoding="utf-8")
    manim_media_dir = scene_dir / "media"

    try:
        result = subprocess.run(
            [
                "manim", "render", str(script_path),
                "-qm",
                "--media_dir", str(manim_media_dir),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Manim exited with non-zero status")

        video_files = list(manim_media_dir.rglob("*.mp4"))
        if not video_files:
            raise RuntimeError("Manim produced no .mp4 output")

        final_path, video_url = scene_media_path(video_id, scene_id)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video_files[0]), str(final_path))

        update_scene_status_sync(scene_id, SceneStatus.RENDERED, rendered_segment_url=video_url)
        # Single-scene interim flow: the scene is the whole video.
        update_video_status_sync(video_id, VideoStatus.COMPLETED, final_video_url=video_url)
        logger.info("Scene %s rendered successfully → %s", scene_id, video_url)

    except subprocess.TimeoutExpired:
        fail("Rendering timed out after 120 seconds")
        logger.error("Scene %s timed out", scene_id)

    except Exception as e:
        fail(str(e))
        logger.error("Scene %s render failed: %s", scene_id, e)

    finally:
        shutil.rmtree(str(tmp_root), ignore_errors=True)
