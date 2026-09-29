"""Niet-talige signalen: geluidspieken en YouTube's 'meest opnieuw afgespeeld'-grafiek."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..media import SAMPLE_RATE, load_wav

WINDOW = 0.5  # seconden


def loudness_curve(wav: Path) -> np.ndarray:
    """Luidheid (dB) per halve seconde, relatief t.o.v. de omgeving (±30 s).

    Door te vergelijken met de lokale mediaan tellen schreeuwen, lachen en
    applaus mee, ook in een video die overal al hard is.
    """
    audio = load_wav(wav)
    hop = int(SAMPLE_RATE * WINDOW)
    n = len(audio) // hop
    if n == 0:
        return np.zeros(0)
    frames = audio[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)
    # Snelle lopende mediaan: mediaan per blok van 10 s, daarna gemiddeld over ±30 s
    block = int(10 / WINDOW)
    meds = np.array([np.median(db[i:i + block]) for i in range(0, n, block)])
    meds = np.convolve(np.pad(meds, 3, mode="edge"), np.ones(7) / 7, mode="valid")
    ctx = np.interp(np.arange(n), np.arange(len(meds)) * block + block / 2, meds)
    rel = db - ctx
    return (rel - rel.mean()) / (rel.std() + 1e-9)


def peaks(curve: np.ndarray, top: int = 40, min_gap: float = 20.0, threshold: float = 1.8) -> list[dict]:
    order = np.argsort(curve)[::-1]
    chosen: list[dict] = []
    for i in order:
        if curve[i] < threshold or len(chosen) >= top:
            break
        t = i * WINDOW
        if all(abs(t - c["t"]) >= min_gap for c in chosen):
            chosen.append({"t": round(t, 1), "z": round(float(curve[i]), 2)})
    return sorted(chosen, key=lambda c: c["t"])


def heatmap_peaks(heatmap: list[dict], top: int = 10) -> list[dict]:
    """Stukken die kijkers het vaakst terugspoelen (alleen YouTube)."""
    if not heatmap:
        return []
    vals = np.array([h["value"] for h in heatmap])
    thr = max(np.percentile(vals, 85), vals.mean() + vals.std())
    hot = [h for h in heatmap if h["value"] >= thr]
    hot.sort(key=lambda h: h["value"], reverse=True)
    return sorted(hot[:top], key=lambda h: h["start"])


def compute(wav: Path, meta: dict) -> dict:
    curve = loudness_curve(wav)
    return {
        "loud": peaks(curve),
        "replayed": heatmap_peaks(meta.get("heatmap") or []),
    }
