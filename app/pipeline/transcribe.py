"""Transcriptie met faster-whisper in twee passes.

Pass 1: klein, snel model over de hele video -> genoeg om hoogtepunten te kiezen.
Pass 2: nauwkeurig model met woordtimings, alleen op de gekozen clips -> ondertitels.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from ..media import load_wav

_models: dict[str, object] = {}
_lock = threading.Lock()


def _model(name: str):
    from faster_whisper import WhisperModel

    with _lock:
        if name not in _models:
            _models.clear()  # max één model tegelijk in het geheugen
            try:
                import ctranslate2

                cuda = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                cuda = False
            _models[name] = WhisperModel(
                name,
                device="cuda" if cuda else "cpu",
                compute_type="float16" if cuda else "int8",
                cpu_threads=os.cpu_count() or 4,
            )
        return _models[name]


def transcribe_segments(wav: Path, model: str, language: str | None,
                        progress: Callable[[str], None] | None = None) -> dict:
    """Pass 1 -> {'language': 'nl', 'segments': [{'start','end','text'}]}"""
    m = _model(model)
    segments, info = m.transcribe(
        str(wav), language=language, vad_filter=True, beam_size=1,
        condition_on_previous_text=False,
    )
    out = []
    total = info.duration or 1
    for s in segments:
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        if progress and len(out) % 20 == 0:
            progress(f"transcriberen {min(99, int(100 * s.end / total))}%")
    return {"language": info.language, "segments": out}


def transcribe_words(wav: Path, start: float, end: float, model: str, language: str | None) -> list[list]:
    """Pass 2 -> [[start, end, woord], ...] met absolute tijden."""
    audio = load_wav(wav, start, end - start)
    m = _model(model)
    segments, _ = m.transcribe(
        audio, language=language, word_timestamps=True, vad_filter=True, beam_size=5,
    )
    words = []
    for s in segments:
        for w in s.words or []:
            text = w.word.strip()
            if text:
                words.append([round(start + w.start, 3), round(start + w.end, 3), text])
    return words
