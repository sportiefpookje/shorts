"""Webserver: wachtrij, review, uploaden en instellingen."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, worker
from .config import APP_DIR, EXPORT_DIR, UPLOADS_DIR, anthropic_key, load_settings, save_settings
from .pipeline.captions import CAP_SIZE, CAPTION_Y, HOOK_SECONDS, HOOK_SIZE, HOOK_Y, MAX_CHARS, MAX_WORDS
from .upload import schedule, youtube

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Shorts-fabriek", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def page(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"settings": load_settings(), "has_key": bool(anthropic_key()), **ctx})


# ---------- Pagina's ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return page(request, "index.html")


@app.get("/review", response_class=HTMLResponse)
def review(request: Request, job: int | None = None):
    caption_cfg = {"y": CAPTION_Y, "hook_y": HOOK_Y, "hook_seconds": HOOK_SECONDS,
                   "max_words": MAX_WORDS, "max_chars": MAX_CHARS, "cap_size": CAP_SIZE, "hook_size": HOOK_SIZE}
    return page(request, "review.html", job_id=job, caption_cfg=caption_cfg)


@app.get("/publish", response_class=HTMLResponse)
def publish(request: Request):
    return page(request, "publish.html")


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    return page(request, "settings.html")


# ---------- Jobs ----------

@app.get("/api/jobs")
def api_jobs():
    return db.list_jobs()


@app.post("/api/jobs")
async def api_add_jobs(request: Request):
    data = await request.json()
    lines = [ln.strip() for ln in str(data.get("urls", "")).splitlines() if ln.strip()]
    ids = []
    for ln in lines:
        if ln.startswith(("http://", "https://")):
            ids.append(db.add_job(ln, "url"))
        elif Path(ln.strip('"')).exists():  # lokaal pad geplakt
            ids.append(db.add_job(ln.strip('"'), "file", Path(ln.strip('"')).stem))
        else:
            raise HTTPException(400, f"Geen geldige link of bestand: {ln[:80]}")
    return {"ids": ids}


@app.post("/api/jobs/upload")
async def api_upload_file(file: UploadFile):
    name = Path(file.filename or "video.mp4").name
    dst = UPLOADS_DIR / name
    i = 1
    while dst.exists():
        dst = UPLOADS_DIR / f"{Path(name).stem}_{i}{Path(name).suffix}"
        i += 1
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f, length=8 * 1024 * 1024)
    return {"id": db.add_job(str(dst), "file", Path(name).stem)}


@app.post("/api/jobs/{job_id}/retry")
def api_retry(job_id: int):
    db.delete_clips_of_job(job_id)
    db.update_job(job_id, status="queued", error="", progress="")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: int):
    db.delete_job(job_id)
    shutil.rmtree(worker.job_dir(job_id), ignore_errors=True)
    return {"ok": True}


# ---------- Clips ----------

@app.get("/api/clips")
def api_clips(job: int | None = None, status: str | None = None):
    where, params = "", ()
    if status and status != "all":
        where, params = "status=?", (status,)
    clips = db.list_clips(job, where, params)
    if job is None and not status:
        clips = [c for c in clips if c["status"] == "pending"]
    return sorted(clips, key=lambda c: (c["status"] != "pending", -c["score"], c["id"]))


RENDER_FIELDS = {"start", "end", "layout", "framing", "hook", "words"}


def _retime_words(words: list, start: float, end: float, text: str) -> list:
    """Nieuwe ondertiteltekst over de bestaande woordtimings verdelen."""
    inside = [w for w in words if w[1] > start and w[0] < end]
    tokens = text.split()
    if not inside or not tokens:
        return words
    before = [w for w in words if w[1] <= start]
    after = [w for w in words if w[0] >= end]
    if len(tokens) == len(inside):
        new = [[w[0], w[1], t] for w, t in zip(inside, tokens)]
    else:
        t0, t1 = inside[0][0], inside[-1][1]
        weights = [len(t) + 2 for t in tokens]
        total = sum(weights)
        new, cur = [], t0
        for tok, wgt in zip(tokens, weights):
            d = (t1 - t0) * wgt / total
            new.append([round(cur, 3), round(cur + d * 0.9, 3), tok])
            cur += d
    return before + new + after


@app.patch("/api/clips/{clip_id}")
async def api_update_clip(clip_id: int, request: Request):
    clip = db.get_clip(clip_id)
    if not clip:
        raise HTTPException(404)
    data = await request.json()
    s = load_settings()
    upd: dict = {}
    for k in ("title", "description", "hashtags", "hook", "layout"):
        if k in data:
            upd[k] = str(data[k])
    if "framing" in data:
        upd["framing"] = {**clip["framing"], **data["framing"]}
    if "start" in data or "end" in data:
        start = float(data.get("start", clip["start"]))
        end = float(data.get("end", clip["end"]))
        start = max(clip["win_start"], min(start, clip["win_end"] - 1))
        end = min(clip["win_end"], max(end, start + 1))
        end = min(end, start + float(s["max_duration"]))
        upd["start"], upd["end"] = round(start, 3), round(end, 3)
    if "caption_text" in data:
        upd["words"] = _retime_words(clip["words"], upd.get("start", clip["start"]),
                                     upd.get("end", clip["end"]), str(data["caption_text"]))
    if "status" in data and data["status"] in ("pending", "approved", "rejected"):
        upd["status"] = data["status"]
    if RENDER_FIELDS & upd.keys() and clip["upload_status"] == "exported":
        upd["upload_status"] = "none"  # klaargezette versie is verouderd
    if upd:
        db.update_clip(clip_id, **upd)
    new = db.get_clip(clip_id)
    needs_render = new["status"] == "approved" and (
        ("status" in upd and clip["status"] != "approved") or RENDER_FIELDS & upd.keys()
        or new["render_status"] in ("none", "error")
    )
    if needs_render and new["render_status"] != "queued":
        worker.queue_render(clip_id)
    if new["status"] != "approved" and new["render_status"] == "queued":
        db.update_clip(clip_id, render_status="none")
    return db.get_clip(clip_id)


@app.get("/media/source/{clip_id}")
def media_source(clip_id: int):
    clip = db.get_clip(clip_id)
    if not clip or not Path(clip["src_file"]).exists():
        raise HTTPException(404)
    return FileResponse(clip["src_file"])


@app.get("/media/short/{clip_id}")
def media_short(clip_id: int):
    clip = db.get_clip(clip_id)
    if not clip or not clip["output"] or not Path(clip["output"]).exists():
        raise HTTPException(404)
    return FileResponse(clip["output"], media_type="video/mp4")


# ---------- Publiceren ----------

@app.get("/api/publish")
def api_publish_list():
    clips = db.list_clips(where="status='approved'")
    return sorted(clips, key=lambda c: (c["publish_at"] or "9999", c["id"]))


@app.post("/api/schedule")
async def api_schedule(request: Request):
    """Verdeelt de gekozen (of alle ongeplande) clips over de vrije tijdsloten."""
    data = await request.json()
    s = load_settings()
    approved = db.list_clips(where="status='approved' AND upload_status NOT IN ('done','exported')")
    ids = data.get("ids") or [c["id"] for c in approved if not c["publish_at"]]
    taken = [schedule.parse_iso(c["publish_at"]) for c in db.list_clips(where="publish_at!=''")
             if c["id"] not in ids]
    slots = schedule.next_slots(len(ids), s["schedule_slots"], [t for t in taken if t])
    for cid, when in zip(ids, slots):
        db.update_clip(cid, publish_at=when.isoformat())
    return {"ok": True}


@app.post("/api/clips/{clip_id}/publish_at")
async def api_set_publish_at(clip_id: int, request: Request):
    data = await request.json()
    value = str(data.get("publish_at", ""))
    when = schedule.parse_iso(value)
    db.update_clip(clip_id, publish_at=when.astimezone().isoformat() if when else "")
    return db.get_clip(clip_id)


@app.post("/api/youtube/upload")
async def api_youtube_upload(request: Request):
    data = await request.json()
    ids = [int(i) for i in data.get("ids", [])]
    worker.queue_upload(ids)
    return {"ok": True}


@app.post("/api/export")
async def api_export(request: Request):
    data = await request.json()
    s = load_settings()
    done = []
    for cid in data.get("ids", []):
        clip = db.get_clip(int(cid))
        if clip and clip["render_status"] == "done":
            youtube.export_for_studio(clip, s)
            db.update_clip(clip["id"], upload_status="exported")
            done.append(clip["id"])
    return {"exported": done, "folder": str(EXPORT_DIR)}


@app.post("/api/clips/{clip_id}/mark_uploaded")
def api_mark_uploaded(clip_id: int):
    db.update_clip(clip_id, upload_status="done")
    return {"ok": True}


@app.post("/api/open_export")
def api_open_export():
    if sys.platform == "win32":
        os.startfile(EXPORT_DIR)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", EXPORT_DIR])
    else:
        subprocess.Popen(["xdg-open", EXPORT_DIR])
    return {"ok": True}


@app.get("/api/youtube/status")
def api_youtube_status():
    return youtube.status()


_connect_state: dict = {"running": False, "error": ""}


@app.post("/api/youtube/connect")
def api_youtube_connect():
    if _connect_state["running"]:
        return _connect_state

    def run():
        _connect_state.update(running=True, error="")
        try:
            youtube.connect()
        except Exception as e:
            _connect_state["error"] = str(e)[:300]
        finally:
            _connect_state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return {"running": True}


@app.get("/api/youtube/connect")
def api_youtube_connect_state():
    return _connect_state


# ---------- Instellingen ----------

@app.get("/api/settings")
def api_settings():
    return load_settings()


@app.post("/api/settings")
async def api_save_settings(request: Request):
    return save_settings(await request.json())


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", 8765))
    if os.environ.get("SHORTS_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
