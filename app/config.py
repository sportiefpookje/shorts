"""Paden, .env en gebruikersinstellingen (data/settings.json)."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
DATA_DIR = Path(os.environ.get("SHORTS_DATA_DIR", ROOT / "data"))
JOBS_DIR = DATA_DIR / "jobs"
UPLOADS_DIR = DATA_DIR / "uploads"
EXPORT_DIR = DATA_DIR / "export"
DB_PATH = DATA_DIR / "shorts.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
FONT_FILE = APP_DIR / "static" / "fonts" / "Montserrat-ExtraBold.ttf"
FONT_NAME = "Montserrat ExtraBold"
FACE_MODEL = APP_DIR / "static" / "models" / "face_detection_yunet_2023mar.onnx"

load_dotenv(ROOT / ".env")

for d in (DATA_DIR, JOBS_DIR, UPLOADS_DIR, EXPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS: dict = {
    # Inhoud
    "channel_description": "",       # waar gaat je kanaal over, voor wie? (helpt Claude)
    "language": "auto",              # "auto" of taalcode zoals "nl", "en"
    "default_hashtags": "#shorts",
    "description_footer": "",
    # Clips
    "max_clips": 6,                  # kwaliteit boven kwantiteit
    "min_score": 7,                  # alleen clips met viraliteitsscore >= dit getal
    "min_duration": 15,
    "max_duration": 59,
    "captions": True,
    "caption_uppercase": True,
    "caption_color": "#FFE600",      # kleur van het actieve woord
    "hook_overlay": True,
    # Modellen
    "claude_model": "claude-opus-5-5",
    "whisper_fast_model": "small",          # pass 1: hele video, alleen om te kiezen
    "whisper_quality_model": "large-v3-turbo",  # pass 2: alleen de gekozen clips
    # Renderen
    "render_parallel": 2,
    "encoder": "auto",               # auto, h264_amf, h264_qsv, h264_nvenc, libx264
    # Uploaden
    "upload_mode": "studio",         # "studio" (handmatig slepen) of "api"
    "api_verified": False,           # API-project geaudit door Google?
    "schedule_slots": ["12:00", "17:00", "20:00"],
    "category_id": "22",             # 22 = People & Blogs, 20 = Gaming, 24 = Entertainment
    "made_for_kids": False,
}

_lock = threading.Lock()


def load_settings() -> dict:
    with _lock:
        data = {}
        if SETTINGS_PATH.exists():
            try:
                data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        return {**DEFAULT_SETTINGS, **data}


def save_settings(new: dict) -> dict:
    current = load_settings()
    for key, default in DEFAULT_SETTINGS.items():
        if key not in new:
            continue
        value = new[key]
        # Types gelijk houden aan de standaardwaarde
        if isinstance(default, bool):
            value = value in (True, "true", "on", "1", 1)
        elif isinstance(default, int):
            value = int(value)
        elif isinstance(default, list) and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        current[key] = value
    with _lock:
        SETTINGS_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def anthropic_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or None


def google_client_secret() -> Path:
    p = Path(os.environ.get("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json"))
    return p if p.is_absolute() else ROOT / p
