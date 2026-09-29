"""Uploaden via de YouTube Data API v3 (OAuth 'Desktop app')."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..config import DATA_DIR, EXPORT_DIR, google_client_secret
from .schedule import parse_iso

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
TOKEN = DATA_DIR / "youtube_token.json"


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds if creds.valid else None


def _service():
    from googleapiclient.discovery import build

    creds = _creds()
    if not creds:
        raise RuntimeError("YouTube is niet gekoppeld (Instellingen -> YouTube koppelen)")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def connect() -> str:
    """Opent de browser voor Google-login en bewaart het token lokaal."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = google_client_secret()
    if not secret.exists():
        raise RuntimeError(f"OAuth-bestand niet gevonden: {secret.name} (zie README)")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return status()["channel"]


def status() -> dict:
    if not google_client_secret().exists():
        return {"connected": False, "channel": "", "secret": False}
    try:
        yt = _service()
        r = yt.channels().list(part="snippet", mine=True).execute()
        items = r.get("items") or []
        return {"connected": True, "channel": items[0]["snippet"]["title"] if items else "?", "secret": True}
    except Exception as e:
        return {"connected": False, "channel": "", "secret": True, "error": str(e)[:300]}


def full_description(clip: dict, settings: dict) -> str:
    parts = [clip.get("description", "").strip(), clip.get("hashtags", "").strip(),
             settings.get("default_hashtags", "").strip(), settings.get("description_footer", "").strip()]
    text = "\n\n".join(p for p in parts if p)
    # Dubbele hashtags weghalen
    seen: set[str] = set()

    def dedupe(m: re.Match) -> str:
        tag = m.group(0).lower()
        if tag in seen:
            return ""
        seen.add(tag)
        return m.group(0)

    return re.sub(r"#\w+", dedupe, text).strip()


def tags_of(clip: dict, settings: dict) -> list[str]:
    tags = re.findall(r"#(\w+)", f"{clip.get('hashtags', '')} {settings.get('default_hashtags', '')}")
    return list(dict.fromkeys(tags))[:15]


def upload_clip(clip: dict, settings: dict, progress: Callable[[int], None] | None = None) -> str:
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    publish = parse_iso(clip.get("publish_at", ""))
    status: dict = {"selfDeclaredMadeForKids": bool(settings.get("made_for_kids", False))}
    if publish and publish > datetime.now(timezone.utc):
        status["privacyStatus"] = "private"
        status["publishAt"] = publish.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    else:
        status["privacyStatus"] = "public"
    body = {
        "snippet": {
            "title": clip["title"][:100],
            "description": full_description(clip, settings)[:4900],
            "tags": tags_of(clip, settings),
            "categoryId": str(settings.get("category_id", "22")),
        },
        "status": status,
    }
    lang = settings.get("language")
    if lang and lang != "auto":
        body["snippet"]["defaultLanguage"] = lang
        body["snippet"]["defaultAudioLanguage"] = lang
    media = MediaFileUpload(clip["output"], mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        st, response = req.next_chunk(num_retries=5)
        if st and progress:
            progress(int(st.progress() * 100))
    return response["id"]


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f#]', "", name).strip()[:80] or "short"


def export_for_studio(clip: dict, settings: dict) -> Path:
    """Kopieert de Short naar data/export met een metadatabestand ernaast."""
    when = parse_iso(clip.get("publish_at", ""))
    prefix = when.astimezone().strftime("%Y-%m-%d %H%M") if when else "zonder datum"
    dst = EXPORT_DIR / f"{prefix} - {_safe(clip['title'])}.mp4"
    shutil.copy(clip["output"], dst)
    meta = [
        f"TITEL:\n{clip['title']}",
        f"BESCHRIJVING:\n{full_description(clip, settings)}",
        f"INPLANNEN OP:\n{when.astimezone().strftime('%A %d-%m-%Y %H:%M') if when else '-'}",
    ]
    dst.with_suffix(".txt").write_text("\n\n".join(meta) + "\n", encoding="utf-8")
    return dst
