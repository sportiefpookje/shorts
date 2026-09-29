"""End-to-end: lokaal bestand -> analyse -> clips -> render (Whisper en Claude gestubd)."""
import json
from types import SimpleNamespace

from conftest import fake_segments, fake_words


def test_file_job_to_rendered_short(sample_video, monkeypatch):
    from app import db
    from app.config import JOBS_DIR, load_settings
    from app.media import probe
    from app.pipeline import analyze, select, transcribe
    from app.pipeline.render import render

    db.init()
    monkeypatch.setattr(transcribe, "transcribe_segments", lambda *a, **k: fake_segments())
    monkeypatch.setattr(transcribe, "transcribe_words", fake_words)

    job_id = db.add_job(str(sample_video), "file", "Testvideo")
    analyze.run_job(db.get_job(job_id))

    job = db.get_job(job_id)
    assert job["status"] == "ready", job
    clips = db.list_clips(job_id)
    assert clips, "verwacht minstens één clip"
    # Heuristiek moet rond de geluidspiek op 30-33 s uitkomen
    assert any(c["start"] <= 31 <= c["end"] for c in clips)

    settings = load_settings()
    for layout in ("track", "center", "blur", "split"):
        c = dict(clips[0], layout=layout, hook="Dit geloof je nooit", status="approved")
        if layout == "split":
            c["framing"] = {**c["framing"], "facecam": [0.7, 0.05, 0.28, 0.3]}
        if layout == "track":
            c["framing"] = {**c["framing"], "track": [[c["start"], 0.3], [c["start"] + 5, 0.7]]}
        out = JOBS_DIR / str(job_id) / "out" / f"test_{layout}.mp4"
        render(c, settings, out)
        info = probe(out)
        assert (info["width"], info["height"]) == (1080, 1920), layout
        assert info["duration"] < 60
        assert abs(info["duration"] - (c["end"] - c["start"])) < 0.5
        assert info["has_audio"]


def test_claude_response_is_parsed(monkeypatch):
    """De Claude-aanroep zelf gemockt: controleert request-vorm en parsing."""
    import anthropic

    from app.config import load_settings
    from app.pipeline import select

    captured = {}
    payload = {"clips": [{"start": 10.0, "end": 40.0, "score": 8, "hook_text": "Wacht op het einde",
                          "title": "Hij had dit nooit verwacht 😳", "description": "Wat zou jij doen?",
                          "hashtags": ["gaming", "#fail"], "reason": "Sterke clou"}]}

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="thinking"),
                                            SimpleNamespace(type="text", text=json.dumps(payload))])

    class FakeClient:
        def __init__(self, **kw):
            self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self.stream))

        def stream(self, **kw):
            captured.update(kw)
            return FakeStream()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    segs = fake_segments()["segments"]
    sig = {"loud": [{"t": 31.0, "z": 3.2}], "replayed": []}
    raw = select.select_with_claude({"title": "t", "duration": 90}, segs, sig, load_settings(), ["Oude titel"], "nl")
    clips = select.clean(raw, load_settings(), 90)
    assert clips[0]["hashtags"] == ["#gaming", "#fail"]
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert "«LOUD+3.2»" in captured["messages"][0]["content"]
    assert "Oude titel" in captured["system"]


def test_clean_and_snap():
    from app.pipeline import select

    s = {"min_duration": 15, "max_duration": 59, "max_clips": 2}
    raw = [
        {"start": 0, "end": 30, "score": 7, "hashtags": []},
        {"start": 20, "end": 50, "score": 9, "hashtags": []},   # overlapt, hogere score wint
        {"start": 60, "end": 65, "score": 10, "hashtags": []},  # te kort
        {"start": 70, "end": 200, "score": 8, "hashtags": []},  # te lang -> ingekort
    ]
    out = select.clean(raw, s, 300)
    assert [c["score"] for c in out] == [9, 8]
    assert out[1]["end"] - out[1]["start"] == 59

    words = [[10.5, 10.8, "Hoi"], [11.0, 11.4, "daar."], [30.0, 30.5, "einde."]]
    st, en = select.snap_to_words(10.0, 31.0, words, 59)
    assert abs(st - 10.38) < 1e-6 and abs(en - 30.85) < 1e-6


def test_captions_ass():
    from app.pipeline.captions import build_ass, group_words

    words = [[0.1, 0.4, "Dit"], [0.45, 0.7, "is"], [0.75, 1.0, "echt"], [1.05, 1.3, "gek."], [2.5, 3.0, "Ja"]]
    groups = group_words(words)
    assert [len(g) for g in groups] == [3, 1, 1]
    ass = build_ass(words, 5.0, "track", {"caption_color": "#FFE600", "caption_uppercase": True,
                                          "captions": True, "hook_overlay": True}, hook="Kijk dit")
    assert "Style: Cap,Montserrat ExtraBold" in ass
    assert "{\\c&H0000E6FF&}DIT" in ass
    assert "Kijk dit" in ass


def test_find_offset_realigns_section(tmp_path):
    """yt-dlp knipt op keyframes; de audio-uitlijning moet het echte begin vinden."""
    import subprocess

    from app.media import extract_audio, find_offset

    src, sec = tmp_path / "src.mp4", tmp_path / "sec.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=d=90:c=pink:a=0.3",
                    "-af", "volume='0.2+0.8*abs(sin(t*1.7)*sin(t*0.31))':eval=frame", "-c:a", "aac", str(src)],
                   check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "44", "-i", str(src), "-t", "30", "-c:a", "aac", str(sec)],
                   check=True)
    wav = extract_audio(src, tmp_path / "full.wav")
    assert abs(find_offset(wav, sec, 47.3) - 44.0) < 0.05
