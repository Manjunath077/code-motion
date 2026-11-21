import shutil
import time
import subprocess
import tempfile
from pathlib import Path

from app.workers.celery_app import celery_app
from app.core import activity
from app.core.logging import get_logger
from app.core.media import scene_media_path
from app.pipeline.transitions import scene_render_finished_sync
from app.repository.sync_scene_repository import get_scene_sync, update_scene_status_sync
from app.schemas.api import SceneOut
from app.schemas.status import SceneStatus

logger = get_logger(__name__)

_RENDER_TIMEOUT_S = 120


def _render(scene: SceneOut) -> str:
    """Render the scene's script with Manim; return the public URL of the mp4."""
    tmp_root = Path(tempfile.mkdtemp())
    try:
        script_path = tmp_root / "scene.py"
        script_path.write_text(scene.generated_script, encoding="utf-8")
        manim_media_dir = tmp_root / "media"

        try:
            result = subprocess.run(
                ["manim", "render", str(script_path), "-qm", "--media_dir", str(manim_media_dir)],
                capture_output=True,
                text=True,
                timeout=_RENDER_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Rendering timed out after {_RENDER_TIMEOUT_S} seconds")

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Manim exited with non-zero status")

        video_files = list(manim_media_dir.rglob("*.mp4"))
        if not video_files:
            raise RuntimeError("Manim produced no .mp4 output")

        final_path, url = scene_media_path(scene.video_id, scene.id)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(video_files[0]), str(final_path))
        return url
    finally:
        shutil.rmtree(str(tmp_root), ignore_errors=True)


@celery_app.task(name="render_scene")
def render_scene(scene_id: str) -> None:
    """Render one scene, save the result on the scene, then let the pipeline
    check whether every scene of the video is done (fan-in)."""
    logger.info("Render task started for scene %s", scene_id)
    scene = get_scene_sync(scene_id)
    if scene is None:
        logger.info("Scene %s no longer exists — skipping", scene_id)
        return

    ids = dict(video_id=scene.video_id, scene_id=scene_id)
    if not scene.generated_script:
        update_scene_status_sync(scene_id, SceneStatus.FAILED, error_message="Scene has no script")
        activity.emit("render_failed", **ids, error="Scene has no script")
    else:
        started = time.monotonic()
        activity.emit("render_started", **ids, scene_no=scene.order, quality="-qm (720p30)")
        try:
            url = _render(scene)
            update_scene_status_sync(
                scene_id, SceneStatus.RENDERED, rendered_segment_url=url, error_message=None
            )
            logger.info("Scene %s rendered → %s", scene_id, url)
            activity.emit("render_finished", **ids, took=f"{time.monotonic() - started:.1f} s", file=url)
        except Exception as e:
            update_scene_status_sync(scene_id, SceneStatus.FAILED, error_message=str(e))
            logger.error("Scene %s render failed: %s", scene_id, e)
            activity.emit(
                "render_failed", **ids, took=f"{time.monotonic() - started:.1f} s", error=str(e)[-500:]
            )

    scene_render_finished_sync(scene.video_id)
