"""Volledige analyse van één job: bron -> transcript -> keuze -> fragmenten -> clips in de review."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .. import db
from ..config import JOBS_DIR, anthropic_key, load_settings
from ..media import ensure_browser_playable, extract_audio, find_offset, probe, require_ffmpeg
from . import download, framing, select, signals, transcribe

log = logging.getLogger(__name__)

PAD = 15.0  # extra seconden rond elke clip, zodat je in de review kunt bijstellen


def _cached(path: Path, fn):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fn()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def run_job(job: dict) -> None:
    require_ffmpeg()
    jid = job["id"]
    work = JOBS_DIR / str(jid)
    work.mkdir(parents=True, exist_ok=True)
    settings = load_settings()

    def progress(msg: str) -> None:
        db.update_job(jid, progress=msg)

    # 1. Bron + audio
    wav = work / "audio.wav"
    if job["kind"] == "url":
        db.update_job(jid, status="downloading", progress="info ophalen")
        meta = _cached(work / "meta.json", lambda: download.fetch_info(job["source"]))
        db.update_job(jid, title=meta["title"])
        if not wav.exists():
            progress("audio downloaden")
            audio = download.download_audio(job["source"], work, progress)
            extract_audio(audio, wav)
            audio.unlink(missing_ok=True)
    else:
        src = Path(job["source"])
        info = probe(src)
        meta = {"title": job["title"] or src.stem, "duration": info["duration"], "uploader": "", "heatmap": []}
        if not wav.exists():
            db.update_job(jid, status="downloading", progress="audio uitpakken")
            extract_audio(src, wav)
    if not meta.get("duration"):
        meta["duration"] = probe(wav)["duration"]

    # 2. Transcript (pass 1)
    db.update_job(jid, status="transcribing", progress="transcriberen")
    lang = None if settings["language"] == "auto" else settings["language"]
    tr = _cached(work / "transcript.json",
                 lambda: transcribe.transcribe_segments(wav, settings["whisper_fast_model"], lang, progress))
    lang = lang or tr["language"]
    if not tr["segments"]:
        raise RuntimeError("Geen spraak gevonden in deze video")

    # 3. Hoogtepunten kiezen
    db.update_job(jid, status="analyzing", progress="hoogtepunten zoeken")
    sig = signals.compute(wav, meta)
    note = ""
    raw: list[dict] = []
    if anthropic_key():
        progress("Claude bekijkt het transcript")
        try:
            raw = select.select_with_claude(meta, tr["segments"], sig, settings, db.approved_titles(), lang)
        except Exception as e:  # netwerk, quota, ...: niet blokkeren, terugvallen
            log.exception("Claude-selectie mislukt")
            note = f"AI-selectie mislukt ({e.__class__.__name__}: {str(e)[:200]}); gekozen op geluid."
    else:
        note = "Geen ANTHROPIC_API_KEY: clips gekozen op geluid, titels zijn ruw."
    if not raw and (note or not anthropic_key()):
        raw = select.select_heuristic(meta, tr["segments"], sig, settings)
    clips = select.clean(raw, settings, meta["duration"])
    db.update_job(jid, meta={"note": note, "language": lang, "duration": meta["duration"]})
    if not clips:
        db.update_job(jid, status="ready", progress="geen clips die goed genoeg zijn gevonden")
        return

    # 4. Per clip: beeld ophalen, woorden, kadrering
    playable = None
    if job["kind"] == "file":
        progress("video voorbereiden voor preview")
        playable = ensure_browser_playable(Path(job["source"]), work / "source.mp4")

    for i, c in enumerate(clips):
        db.update_job(jid, status="preparing", progress=f"clip {i + 1}/{len(clips)} voorbereiden")
        win_start = max(0.0, c["start"] - PAD)
        win_end = min(meta["duration"], c["end"] + PAD)
        if playable:
            src_file, offset = playable, 0.0
        else:
            src_file = download.download_section(job["source"], win_start, win_end, work / f"section_{i}.mp4")
            offset = find_offset(wav, src_file, win_start)
            win_start, win_end = max(win_start, offset), min(win_end, offset + probe(src_file)["duration"])
        words = transcribe.transcribe_words(wav, win_start, win_end, settings["whisper_quality_model"], lang)
        start, end = select.snap_to_words(c["start"], c["end"], words, float(settings["max_duration"]))
        start, end = max(start, win_start), min(end, win_end)
        fr = framing.analyze(Path(src_file), start - offset, end - offset)
        tags = " ".join(c["hashtags"])
        db.add_clip(
            job_id=jid, rank=i, start=start, end=end, win_start=win_start, win_end=win_end,
            src_file=str(src_file), src_offset=offset, title=c["title"][:100], description=c["description"],
            hashtags=tags, hook=c["hook_text"], score=c["score"], reason=c["reason"], words=words,
            layout=fr.get("auto_layout", "blur"), framing=fr,
        )
    db.update_job(jid, status="ready", progress=f"{len(clips)} clips klaar voor review")
