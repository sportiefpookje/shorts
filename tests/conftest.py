import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def data_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("data")
    os.environ["SHORTS_DATA_DIR"] = str(d)
    os.environ["ANTHROPIC_API_KEY"] = ""
    return d


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """90 s 16:9-testvideo met een paar harde geluidspieken."""
    out = tmp_path_factory.mktemp("media") / "sample.mkv"
    vol = "if(between(t,30,33)+between(t,62,64),1.0,0.08)"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=90",
        "-f", "lavfi", "-i", "sine=f=440:d=90",
        "-filter_complex", f"[1:a]volume='{vol}':eval=frame[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out),
    ], check=True)
    return out


def fake_segments(duration: float = 90.0):
    segs = []
    t = 0.0
    i = 0
    while t < duration - 5:
        segs.append({"start": t, "end": t + 4.5, "text": f"Dit is zin nummer {i} met iets spannends."})
        t += 5
        i += 1
    return {"language": "nl", "segments": segs}


def fake_words(wav, start, end, model, language):
    words = []
    t = start + 0.2
    i = 0
    while t < end - 0.5:
        words.append([round(t, 3), round(t + 0.3, 3), f"woord{i}" + ("." if i % 6 == 5 else "")])
        t += 0.4
        i += 1
    return words
