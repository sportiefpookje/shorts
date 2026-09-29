"""Kleine SQLite-laag voor jobs en clips."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,          -- URL of lokaal pad
    kind TEXT NOT NULL,            -- 'url' of 'file'
    title TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    progress TEXT DEFAULT '',
    error TEXT DEFAULT '',
    meta TEXT DEFAULT '{}',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rank INTEGER DEFAULT 0,
    start REAL NOT NULL,           -- absolute tijd in de bronvideo (s)
    end REAL NOT NULL,
    win_start REAL NOT NULL,       -- beschikbaar venster voor bijstellen
    win_end REAL NOT NULL,
    src_file TEXT DEFAULT '',      -- videobestand voor preview/render
    src_offset REAL DEFAULT 0,     -- absolute tijd van t=0 in src_file
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    hashtags TEXT DEFAULT '',
    hook TEXT DEFAULT '',
    score REAL DEFAULT 0,
    reason TEXT DEFAULT '',
    words TEXT DEFAULT '[]',       -- [[start,end,woord],...] absolute tijden
    layout TEXT DEFAULT 'blur',
    framing TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending', -- pending / approved / rejected
    render_status TEXT DEFAULT 'none', -- none / queued / rendering / done / error
    render_error TEXT DEFAULT '',
    output TEXT DEFAULT '',
    publish_at TEXT DEFAULT '',    -- ISO-tijd (UTC) of leeg
    upload_status TEXT DEFAULT 'none', -- none / queued / uploading / done / error / exported
    upload_error TEXT DEFAULT '',
    youtube_id TEXT DEFAULT ''
);
"""

JSON_FIELDS = {"meta", "words", "framing"}


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


def init() -> None:
    conn().executescript(SCHEMA)
    # Na een herstart: onderbroken werk opnieuw in de wachtrij
    conn().execute(
        "UPDATE jobs SET status='queued', progress='' WHERE status NOT IN ('ready','error','queued')"
    )
    conn().execute("UPDATE clips SET render_status='queued' WHERE render_status='rendering'")
    conn().execute("UPDATE clips SET upload_status='queued' WHERE upload_status='uploading'")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_FIELDS & d.keys():
        d[k] = json.loads(d[k] or ("[]" if k == "words" else "{}"))
    return d


def _enc(fields: dict) -> dict:
    return {k: json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v for k, v in fields.items()}


def add_job(source: str, kind: str, title: str = "") -> int:
    cur = conn().execute(
        "INSERT INTO jobs (source, kind, title, created) VALUES (?,?,?,?)",
        (source, kind, title, time.time()),
    )
    return cur.lastrowid


def get_job(job_id: int) -> dict | None:
    return _row(conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs() -> list[dict]:
    rows = conn().execute(
        """SELECT j.*,
             (SELECT COUNT(*) FROM clips c WHERE c.job_id=j.id) AS n_clips,
             (SELECT COUNT(*) FROM clips c WHERE c.job_id=j.id AND c.status='pending') AS n_pending,
             (SELECT COUNT(*) FROM clips c WHERE c.job_id=j.id AND c.status='approved') AS n_approved
           FROM jobs j ORDER BY j.id DESC"""
    ).fetchall()
    return [_row(r) for r in rows]


def update_job(job_id: int, **fields: Any) -> None:
    fields = _enc(fields)
    sets = ", ".join(f"{k}=?" for k in fields)
    conn().execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))


def next_queued_job() -> dict | None:
    return _row(conn().execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone())


def delete_job(job_id: int) -> None:
    conn().execute("DELETE FROM clips WHERE job_id=?", (job_id,))
    conn().execute("DELETE FROM jobs WHERE id=?", (job_id,))


def add_clip(**fields: Any) -> int:
    fields = _enc(fields)
    cols = ", ".join(fields)
    qs = ", ".join("?" for _ in fields)
    cur = conn().execute(f"INSERT INTO clips ({cols}) VALUES ({qs})", tuple(fields.values()))
    return cur.lastrowid


def get_clip(clip_id: int) -> dict | None:
    return _row(conn().execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())


def list_clips(job_id: int | None = None, where: str = "", params: tuple = ()) -> list[dict]:
    q = "SELECT * FROM clips WHERE 1=1"
    args: tuple = ()
    if job_id is not None:
        q += " AND job_id=?"
        args += (job_id,)
    if where:
        q += f" AND {where}"
        args += params
    q += " ORDER BY job_id DESC, rank"
    return [_row(r) for r in conn().execute(q, args).fetchall()]


def update_clip(clip_id: int, **fields: Any) -> None:
    fields = _enc(fields)
    sets = ", ".join(f"{k}=?" for k in fields)
    conn().execute(f"UPDATE clips SET {sets} WHERE id=?", (*fields.values(), clip_id))


def approved_titles(limit: int = 12) -> list[str]:
    rows = conn().execute(
        "SELECT title FROM clips WHERE status='approved' AND title!='' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [r["title"] for r in rows]
