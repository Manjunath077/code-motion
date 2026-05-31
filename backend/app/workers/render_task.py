import shutil
import subprocess
import tempfile
from pathlib import Path

from app.workers.celery_app import celery_app
from app.repository.sync_scene_repository import (
    get_scene_by_id_sync,
    update_scene_status_sync,
    update_scene_video_sync,
)
from app.schemas.scene_schema import SceneStatus
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(bind=True, name="render_scene", max_retries=1)
def render_scene(self, scene_id: str):
    logger.info("Render task started for scene %s", scene_id)
    update_scene_status_sync(scene_id, SceneStatus.RENDERING)

    scene = get_scene_by_id_sync(scene_id)
    if not scene or not scene.generated_script:
        update_scene_status_sync(
            scene_id, SceneStatus.FAILED, error_message="Scene or script not found"
        )
        return

    tmp_root = Path(tempfile.mkdtemp())
    scene_dir = tmp_root / scene_id
    scene_dir.mkdir(parents=True, exist_ok=True)
    script_path = scene_dir / "scene.py"
    script_path.write_text(scene.generated_script)
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

        dest_dir = Path(settings.MEDIA_DIR) / scene_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_path = dest_dir / "output.mp4"
        shutil.move(str(video_files[0]), str(final_path))

        video_url = f"/media/{scene_id}/output.mp4"
        update_scene_video_sync(scene_id, video_url)
        update_scene_status_sync(scene_id, SceneStatus.COMPLETED)
        logger.info("Scene %s rendered successfully → %s", scene_id, video_url)

    except subprocess.TimeoutExpired:
        msg = "Rendering timed out after 120 seconds"
        update_scene_status_sync(scene_id, SceneStatus.FAILED, error_message=msg)
        logger.error("Scene %s timed out", scene_id)

    except Exception as e:
        msg = str(e)
        update_scene_status_sync(scene_id, SceneStatus.FAILED, error_message=msg)
        logger.error("Scene %s render failed: %s", scene_id, msg)

    finally:
        shutil.rmtree(str(tmp_root), ignore_errors=True)
