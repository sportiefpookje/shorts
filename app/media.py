"""ffmpeg/ffprobe-hulpjes, encoderdetectie en audio-uitlijning."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

# Op Windows geen zwart consolevenster per ffmpeg-aanroep
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

SAMPLE_RATE = 16000


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], cwd: Path | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd, cwd=cwd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
    )
    if p.returncode != 0:
        tail = p.stderr.decode("utf-8", "replace")[-1500:]
        raise MediaError(f"{Path(cmd[0]).name} faalde:\n{tail}")
    return p


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(f"{tool} niet gevonden. Installeer ffmpeg (zie README).")


def probe(path: Path) -> dict:
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(p.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    fps = 30.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else 30.0
    rotation = 0
    if v:
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = abs(int(sd["rotation"]))
    w, h = (v["width"], v["height"]) if v else (0, 0)
    if rotation in (90, 270):
        w, h = h, w
    return {
        "duration": float(info["format"].get("duration", 0) or 0),
        "width": w,
        "height": h,
        "fps": fps,
        "vcodec": v["codec_name"] if v else None,
        "acodec": a["codec_name"] if a else None,
        "has_video": v is not None,
        "has_audio": a is not None,
    }


def extract_audio(src: Path, dst: Path) -> Path:
    """16 kHz mono wav: klein, snel, en precies wat Whisper wil."""
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-c:a", "pcm_s16le", str(dst)])
    return dst


def load_wav(path: Path, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    """Leest (een deel van) een 16 kHz mono wav als float32-array."""
    import wave

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        w.setpos(min(int(start * sr), w.getnframes()))
        n = w.getnframes() - w.tell() if duration is None else int(duration * sr)
        raw = w.readframes(max(n, 0))
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def audio_of(src: Path, start: float, duration: float) -> np.ndarray:
    p = run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"])
    return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def find_offset(full_wav: Path, section: Path, expected: float, search: float = 20.0) -> float:
    """Bepaalt waar `section` begint in de volledige audio via kruiscorrelatie.

    yt-dlp knipt op keyframes, dus het echte begin wijkt een paar seconden af
    van wat we vroegen. Door de audio te vergelijken weten we het tot op ~10 ms.
    """
    sr = 2000  # lage resolutie is ruim genoeg en veel sneller
    probe_len = 8.0
    sec = audio_of(section, 1.0, probe_len)  # eerste seconde overslaan (fade/keyframe-rommel)
    lo = max(0.0, expected - search)
    ref = load_wav(full_wav, lo, 2 * search + probe_len + 2)
    if len(sec) < SAMPLE_RATE or len(ref) < len(sec):
        return expected
    step = SAMPLE_RATE // sr
    a = np.abs(sec[::step])
    b = np.abs(ref[::step])
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    n = len(b) + len(a)
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)[: len(b) - len(a) + 1]
    best = int(np.argmax(corr))
    confidence = corr[best] / len(a)
    if confidence < 0.2:
        return expected
    return lo + best / sr - 1.0


ENCODER_ARGS = {
    "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M"],
    "h264_amf": ["-c:v", "h264_amf", "-quality", "quality", "-rc", "vbr_peak", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M"],
    "h264_qsv": ["-c:v", "h264_qsv", "-preset", "medium", "-b:v", "10M", "-maxrate", "14M", "-bufsize", "20M"],
    "libx264": ["-c:v", "libx264", "-preset", "faster", "-crf", "20", "-maxrate", "14M", "-bufsize", "20M"],
}
ENCODER_ORDER = ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"]


@lru_cache(maxsize=None)
def detect_encoder(preferred: str = "auto") -> str:
    """Probeert hardware-encoders met een mini-encode; valt terug op libx264."""
    order = ENCODER_ORDER if preferred == "auto" else [preferred, "libx264"]
    for enc in order:
        try:
            run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=1080x1920:d=0.5",
                 "-pix_fmt", "yuv420p", *ENCODER_ARGS[enc], "-f", "null", "-"], timeout=30)
            return enc
        except (MediaError, subprocess.TimeoutExpired, KeyError):
            continue
    return "libx264"


BROWSER_VCODECS = {"h264", "vp9", "av1", "vp8"}


def ensure_browser_playable(src: Path, dst: Path) -> Path:
    """Zorgt voor een mp4/webm die de browser kan afspelen (voor de preview)."""
    info = probe(src)
    if src.suffix.lower() in (".mp4", ".webm", ".m4v", ".mov") and info["vcodec"] in BROWSER_VCODECS \
            and info["acodec"] in (None, "aac", "opus", "mp3", "vorbis"):
        return src
    if info["vcodec"] in {"h264"}:
        try:  # snel: alleen omverpakken
            run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dst)])
            return dst
        except MediaError:
            pass
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(dst)])
    return dst
