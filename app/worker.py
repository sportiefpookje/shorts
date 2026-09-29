"""Achtergrondwerk: analyse-wachtrij, parallel renderen en uploaden."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db
from .config import JOBS_DIR, load_settings

log = logging.getLogger(__name__)

_render_pool: ThreadPoolExecutor | None = None
_upload_lock = threading.Lock()
_stop = threading.Event()


def _analysis_loop() -> None:
    from .pipeline.analyze import run_job

    while not _stop.is_set():
        job = db.next_queued_job()
        if not job:
            time.sleep(1)
            continue
        try:
            run_job(job)
        except Exception as e:
            log.exception("Job %s mislukt", job["id"])
            db.update_job(job["id"], status="error", error=f"{e.__class__.__name__}: {e}"[:2000])


def _render(clip_id: int) -> None:
    from .pipeline.render import render

    clip = db.get_clip(clip_id)
    if not clip or clip["status"] != "approved":
        db.update_clip(clip_id, render_status="none")
        return
    db.update_clip(clip_id, render_status="rendering", render_error="")
    try:
        out = JOBS_DIR / str(clip["job_id"]) / "out" / f"short_{clip_id}.mp4"
        render(clip, load_settings(), out)
        # Is de clip tijdens het renderen nog aangepast? Dan opnieuw.
        latest = db.get_clip(clip_id)
        if latest and _render_key(latest) != _render_key(clip):
            db.update_clip(clip_id, render_status="queued")
            _render_pool.submit(_render, clip_id)
            return
        db.update_clip(clip_id, render_status="done", output=str(out))
    except Exception as e:
        log.exception("Render %s mislukt", clip_id)
        db.update_clip(clip_id, render_status="error", render_error=str(e)[-1500:])


def _render_key(c: dict) -> tuple:
    return (c["start"], c["end"], c["layout"], str(c["framing"]), str(c["words"]), c["hook"], c["status"])


def queue_render(clip_id: int) -> None:
    db.update_clip(clip_id, render_status="queued")
    _render_pool.submit(_render, clip_id)


def queue_upload(clip_ids: list[int]) -> None:
    from .upload.youtube import upload_clip

    for cid in clip_ids:
        db.update_clip(cid, upload_status="queued", upload_error="")

    def work() -> None:
        with _upload_lock:
            for cid in clip_ids:
                clip = db.get_clip(cid)
                if not clip or clip["upload_status"] != "queued":
                    continue
                # Wacht tot de render klaar is
                while clip["render_status"] in ("queued", "rendering"):
                    time.sleep(2)
                    clip = db.get_clip(cid)
                if clip["render_status"] != "done":
                    db.update_clip(cid, upload_status="error", upload_error="Render niet gelukt")
                    continue
                db.update_clip(cid, upload_status="uploading")
                try:
                    vid = upload_clip(clip, load_settings(),
                                      lambda p: db.update_clip(cid, upload_error=f"{p}%"))
                    db.update_clip(cid, upload_status="done", youtube_id=vid, upload_error="")
                except Exception as e:
                    log.exception("Upload %s mislukt", cid)
                    db.update_clip(cid, upload_status="error", upload_error=str(e)[:1000])

    threading.Thread(target=work, daemon=True).start()


def start() -> None:
    global _render_pool
    db.init()
    _render_pool = ThreadPoolExecutor(max_workers=max(1, int(load_settings()["render_parallel"])))
    threading.Thread(target=_analysis_loop, daemon=True, name="analyse").start()
    for c in db.list_clips(where="render_status='queued'"):
        _render_pool.submit(_render, c["id"])
    queued = [c["id"] for c in db.list_clips(where="upload_status='queued'")]
    if queued:
        queue_upload(queued)


def stop() -> None:
    _stop.set()


def job_dir(job_id: int) -> Path:
    return JOBS_DIR / str(job_id)
