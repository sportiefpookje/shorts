"""Eindrender naar 1080x1920 met ffmpeg."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import FONT_FILE
from ..media import ENCODER_ARGS, detect_encoder, probe, run
from .captions import build_ass

PAN_SECONDS = 0.4


def _even(v: float) -> int:
    return int(v) // 2 * 2


def video_filter(clip: dict, W: int, H: int, rel_start: float) -> str:
    """Filtergraaf van [0:v] naar [base] (1080x1920) voor de gekozen layout."""
    fr = clip.get("framing") or {}
    layout = clip["layout"]
    if layout in ("track", "center") and W / max(H, 1) < 0.9:
        layout = "blur"  # verticale bron: niets bij te snijden
    cw = _even(H * 9 / 16)
    max_x = max(W - cw, 0)

    if layout == "center" or (layout == "track" and not fr.get("track")):
        x = min(max(fr.get("cx", 0.5) * W - cw / 2, 0), max_x)
        return f"[0:v]crop={cw}:{H}:{x:.0f}:0,scale=1080:1920:flags=lanczos,setsar=1[base]"

    if layout == "track":
        keys = fr["track"]
        px = [min(max(k[1] * W - cw / 2, 0), max_x) for k in keys]
        expr = f"{px[0]:.1f}"
        for i in range(1, len(keys)):
            t0 = keys[i][0] - rel_start
            expr += f"+({px[i] - px[i - 1]:.1f})*clip((t-{t0:.3f})/{PAN_SECONDS},0,1)"
        return f"[0:v]crop={cw}:{H}:x='clip({expr},0,{max_x})':y=0,scale=1080:1920:flags=lanczos,setsar=1[base]"

    if layout == "split" and fr.get("facecam"):
        fx, fy, fw, fh = fr["facecam"]
        top = f"crop={_even(fw * W)}:{_even(fh * H)}:{fx * W:.0f}:{fy * H:.0f},scale=1080:768:force_original_aspect_ratio=increase,crop=1080:768"
        gw = min(_even(H * 1080 / 1152), W)
        gx = min(max(fr.get("game_cx", 0.5) * W - gw / 2, 0), W - gw)
        bottom = f"crop={gw}:{H}:{gx:.0f}:0,scale=1080:1152:force_original_aspect_ratio=increase,crop=1080:1152"
        return (f"[0:v]split=2[t][b];[t]{top},setsar=1[top];[b]{bottom},setsar=1[bot];"
                f"[top][bot]vstack=inputs=2[base]")

    # blur (ook de terugval)
    return ("[0:v]split=2[a][b];"
            "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=12:2,"
            "scale=1080:1920,eq=brightness=-0.07[bg];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]")


def render(clip: dict, settings: dict, out: Path) -> Path:
    src = Path(clip["src_file"])
    info = probe(src)
    W, H = info["width"], info["height"]
    rel_start = clip["start"] - clip["src_offset"]
    dur = clip["end"] - clip["start"]
    work = out.parent
    work.mkdir(parents=True, exist_ok=True)

    # Werkmap als cwd, zodat ffmpeg-filterpaden relatief en Windows-veilig zijn
    ass_name = f"clip_{clip['id']}.ass"
    words = [[w[0] - clip["start"], w[1] - clip["start"], w[2]] for w in clip.get("words") or []
             if w[1] > clip["start"] and w[0] < clip["end"]]
    (work / ass_name).write_text(
        build_ass(words, dur, clip["layout"], settings, clip.get("hook", "")), encoding="utf-8"
    )
    font_copy = work / FONT_FILE.name
    if not font_copy.exists():
        shutil.copy(FONT_FILE, font_copy)

    encoder = detect_encoder(settings.get("encoder", "auto"))
    pix = "nv12" if encoder == "h264_qsv" else "yuv420p"
    graph = video_filter(clip, W, H, rel_start) + f";[base]subtitles={ass_name}:fontsdir=.,format={pix}[v]"
    fps = min(info["fps"] or 30, 60)
    tmp = out.with_name(out.stem + ".part.mp4")
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{max(rel_start, 0):.3f}", "-i", str(src.resolve()), "-t", f"{dur:.3f}",
        "-filter_complex", graph, "-map", "[v]",
    ]
    if info["has_audio"]:
        cmd += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += [*ENCODER_ARGS[encoder], "-r", f"{fps:.3f}", "-movflags", "+faststart", tmp.name]
    run(cmd, cwd=work)
    tmp.replace(out)
    return out
