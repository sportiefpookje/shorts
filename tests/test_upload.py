"""Inplannen, YouTube-upload (gemockt) en Studio-export."""
from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_next_slots_skips_taken_and_past():
    from app.upload.schedule import next_slots

    after = datetime(2026, 10, 1, 13, 0).astimezone()
    taken = [datetime(2026, 10, 1, 17, 0).astimezone()]
    got = next_slots(4, ["12:00", "17:00", "20:00"], taken, after)
    assert [(d.day, d.hour) for d in got] == [(1, 20), (2, 12), (2, 17), (2, 20)]


def test_upload_body_scheduled(monkeypatch, tmp_path):
    from app.upload import youtube

    captured = {}

    class Req:
        def next_chunk(self, num_retries=0):
            return None, {"id": "abc123"}

    class Videos:
        def insert(self, part, body, media_body):
            captured.update(part=part, body=body)
            return Req()

    class Service:
        def videos(self):
            return Videos()

    monkeypatch.setattr(youtube, "_service", lambda: Service())
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 1024)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    clip = {"title": "Titel", "description": "Wat vind jij?", "hashtags": "#gaming #Shorts",
            "publish_at": when.isoformat(), "output": str(video)}
    settings = {"default_hashtags": "#shorts", "description_footer": "Volg voor meer!", "category_id": "20",
                "language": "nl", "made_for_kids": False}
    assert youtube.upload_clip(clip, settings) == "abc123"
    body = captured["body"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == when.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert body["snippet"]["tags"] == ["gaming", "Shorts", "shorts"]
    assert body["snippet"]["categoryId"] == "20"
    desc = body["snippet"]["description"]
    assert desc.count("#shorts") + desc.count("#Shorts") == 1  # dubbele hashtag weg
    assert desc.endswith("Volg voor meer!")

    # Zonder datum: direct openbaar
    clip["publish_at"] = ""
    youtube.upload_clip(clip, settings)
    assert captured["body"]["status"] == {"selfDeclaredMadeForKids": False, "privacyStatus": "public"}


def test_export_for_studio(tmp_path):
    from app.upload import youtube

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    clip = {"title": 'Wat?! "Echt" / nee', "description": "d", "hashtags": "#a",
            "publish_at": datetime(2026, 10, 2, 17, 0).astimezone().isoformat(), "output": str(video)}
    out = youtube.export_for_studio(clip, {"default_hashtags": "", "description_footer": ""})
    assert out.name == "2026-10-02 1700 - Wat! Echt  nee.mp4"
    assert Path(out.with_suffix(".txt")).read_text(encoding="utf-8").startswith("TITEL:\nWat?!")
