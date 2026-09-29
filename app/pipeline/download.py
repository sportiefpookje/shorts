"""Downloaden met yt-dlp: eerst alleen audio, later alleen de gekozen fragmenten."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yt_dlp
from yt_dlp.utils import download_range_func

Progress = Callable[[str], None]

# Liefst H.264 (speelt overal af in de browser), max 1080p
VIDEO_FORMAT = (
    "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/"
    "bv*[vcodec^=avc1][height<=1080]+ba/"
    "bv*[height<=1080]+ba/b[height<=1080]/b"
)


def _base_opts(progress: Progress | None) -> dict:
    def hook(d: dict) -> None:
        if progress and d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip()
            progress(f"downloaden {pct}")

    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "noplaylist": True,
    }


def fetch_info(url: str) -> dict:
    with yt_dlp.YoutubeDL({**_base_opts(None), "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title") or "",
        "duration": float(info.get("duration") or 0),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "description": (info.get("description") or "")[:1500],
        # "Meest opnieuw afgespeeld"-grafiek van YouTube: goud voor highlightdetectie
        "heatmap": [
            {"start": h["start_time"], "end": h["end_time"], "value": h["value"]}
            for h in (info.get("heatmap") or [])
        ],
        "chapters": [
            {"start": c.get("start_time", 0), "title": c.get("title", "")} for c in (info.get("chapters") or [])
        ],
        "extractor": info.get("extractor_key", ""),
    }


def download_audio(url: str, out_dir: Path, progress: Progress | None = None) -> Path:
    opts = {
        **_base_opts(progress),
        "format": "ba[abr<=160]/ba/b",
        "outtmpl": str(out_dir / "audio.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


def download_section(url: str, start: float, end: float, dst: Path, progress: Progress | None = None) -> Path:
    """Downloadt alleen [start, end] in max 1080p naar dst (.mp4)."""
    opts = {
        **_base_opts(progress),
        "format": VIDEO_FORMAT,
        "format_sort": ["res:1080", "vcodec:avc1", "acodec:m4a"],
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(max(0.0, start), end)]),
        "outtmpl": str(dst.with_suffix("")) + ".%(ext)s",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    matches = sorted(dst.parent.glob(dst.stem + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    matches = [m for m in matches if m.suffix in (".mp4", ".webm", ".mkv")]
    if not matches:
        raise RuntimeError("Download van fragment mislukt")
    return matches[0]
