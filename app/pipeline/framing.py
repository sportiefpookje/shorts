"""Slim verticaal bijsnijden: gezichten vinden en een layout kiezen.

Layouts:
- track : 9:16-uitsnede die het hoofdgezicht volgt (rustig, met korte pans)
- center: vaste 9:16-uitsnede (positie instelbaar in de review)
- blur  : hele beeld in het midden, vervaagde kopie als achtergrond
- split : facecam boven, gameplay onder (streams met webcam in een hoek)
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..config import FACE_MODEL

SAMPLE_FPS = 3.0
DETECT_W = 640


def detect_faces(video: Path, start: float, end: float) -> tuple[list[tuple[float, list]], int, int]:
    """Gezichten per sample: [(t_abs_in_file, [(cx, cy, w, h, score), ...])] genormaliseerd 0..1."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return [], 0, 0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    scale = DETECT_W / max(W, 1)
    dw, dh = DETECT_W, max(1, int(H * scale))
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (dw, dh), 0.75, 0.3, 50)
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    step = max(1, int(round(fps / SAMPLE_FPS)))
    samples = []
    idx = 0
    t = start
    while t <= end:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            small = cv2.resize(frame, (dw, dh))
            _, faces = det.detect(small)
            found = []
            if faces is not None:
                for f in faces:
                    x, y, w, h, score = f[0], f[1], f[2], f[3], f[-1]
                    found.append(((x + w / 2) / dw, (y + h / 2) / dh, w / dw, h / dh, float(score)))
            samples.append((t, found))
        idx += 1
    cap.release()
    return samples, W, H


def _main_face(faces: list) -> tuple | None:
    return max(faces, key=lambda f: f[2] * f[3]) if faces else None


def track_keyframes(samples: list, crop_frac: float) -> list[list[float]]:
    """Rustige camera: alleen verschuiven als het gezicht echt ergens anders is.

    Geeft [[t, cx], ...] terug; tussen keyframes pant de render kort (0,4 s).
    """
    xs, ts = [], []
    last = 0.5
    for t, faces in samples:
        f = _main_face(faces)
        last = f[0] if f else last
        xs.append(last)
        ts.append(t)
    if not xs:
        return [[0.0, 0.5]]
    xs = np.array(xs)
    # Mediaanfilter tegen losse misdetecties
    k = 2
    xs = np.array([np.median(xs[max(0, i - k): i + k + 1]) for i in range(len(xs))])
    half = crop_frac / 2
    clamp = lambda v: float(min(max(v, half), 1 - half))  # noqa: E731
    keys = [[ts[0], clamp(xs[0])]]
    cur = keys[0][1]
    run_start = None
    for i, (t, x) in enumerate(zip(ts, xs)):
        if abs(clamp(x) - cur) > 0.07:
            run_start = i if run_start is None else run_start
            if t - ts[run_start] >= 1.0:  # blijft >1 s ergens anders -> meebewegen
                cur = clamp(float(np.mean(xs[run_start:i + 1])))
                keys.append([ts[run_start], cur])
                run_start = None
        else:
            run_start = None
    return [[round(t, 2), round(x, 4)] for t, x in keys]


def analyze(video: Path, start: float, end: float) -> dict:
    samples, W, H = detect_faces(video, start, end)
    if not W:
        return {"auto_layout": "blur", "src_w": 0, "src_h": 0}
    framing: dict = {"src_w": W, "src_h": H, "cx": 0.5, "game_cx": 0.5}
    aspect = W / H
    if aspect < 0.9:  # bron is al (bijna) verticaal
        framing["auto_layout"] = "blur"
        return framing
    crop_frac = (H * 9 / 16) / W
    with_face = [(t, _main_face(f)) for t, f in samples if f]
    presence = len(with_face) / max(1, len(samples))
    if presence >= 0.35:
        fx = np.array([f[0] for _, f in with_face])
        fy = np.array([f[1] for _, f in with_face])
        fh = np.array([f[3] for _, f in with_face])
        fw = np.array([f[2] for _, f in with_face])
        small = np.median(fh) < 0.2
        steady = fx.std() < 0.04 and fy.std() < 0.04
        at_edge = min(np.median(fx), 1 - np.median(fx)) < 0.3 or min(np.median(fy), 1 - np.median(fy)) < 0.3
        if small and steady and at_edge:
            # Facecam: kader rond het gezicht in de verhouding van het bovenpaneel (1080x768)
            cx, cy = float(np.median(fx)), float(np.median(fy))
            ch = float(np.median(fh)) * 2.6
            cw = ch * H * (1080 / 768) / W
            cw, ch = min(cw, 1.0), min(ch, 1.0)
            x = min(max(cx - cw / 2, 0), 1 - cw)
            y = min(max(cy - ch / 2, 0), 1 - ch)
            framing["facecam"] = [round(x, 4), round(y, 4), round(cw, 4), round(ch, 4)]
            framing["auto_layout"] = "split"
            # Gameplay-uitsnede weg van de facecam
            framing["game_cx"] = 0.5
        else:
            framing["track"] = track_keyframes(samples, crop_frac)
            framing["cx"] = float(np.median(fx))
            framing["auto_layout"] = "track"
        framing["face_w"] = float(np.median(fw))
    else:
        framing["auto_layout"] = "blur"
    framing["presence"] = round(presence, 2)
    return framing
