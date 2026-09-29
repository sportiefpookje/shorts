"""Hoogtepunten kiezen: Claude beoordeelt het transcript + signalen.

Zonder API-sleutel valt het terug op een eenvoudige selectie op geluidspieken.
"""
from __future__ import annotations

import json
import logging

from ..config import anthropic_key

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a top YouTube Shorts editor. Your clips consistently go viral because you are extremely picky: you would rather deliver 2 great clips than 8 mediocre ones.

You receive a timestamped transcript of a long video (seconds, per segment). Some lines carry signal tags:
- «LOUD+z» the audio is much louder than its surroundings (shouting, laughter, applause, action); higher z = stronger
- «REPLAYED» viewers of the original video rewatched this part most often (very strong signal)

Find the moments that will perform best as standalone vertical Shorts. A great Short:
1. Hooks within the first 1-2 seconds: it starts mid-action, with a bold claim, a question, a conflict or a surprising line. Never start with filler ("so", "um", "anyway", greetings, context setup).
2. Is self-contained: a viewer with zero context understands it.
3. Has one clear payoff: a punchline, reveal, strong opinion, useful insight, emotional peak or crazy moment.
4. Ends right after the payoff (no trailing chatter), which makes it loop well.
5. Is between {min_dur} and {max_dur} seconds; 20-45 s is usually ideal.

Rules:
- `start` must equal the start time of a transcript line, `end` must equal the end time of a transcript line (use the numbers exactly as given).
- Clips must not overlap.
- Score each clip 1-10 for realistic viral potential and be honest and strict: 9-10 = exceptional, 7-8 = strong, <=6 = not worth posting. Only return clips scoring {min_score} or higher, at most {max_clips}. Returning fewer (even zero) is fine.
- Write `title`, `hook_text`, `description` and hashtags in the language of the video{lang_hint}.
- `title`: max 60 characters, curiosity-driven but truthful (no misleading clickbait), at most one emoji.
- `hook_text`: max 7 words, shown big on screen during the first seconds; it should make people stay (tension, question, bold promise). It must not just repeat the first spoken sentence.
- `description`: 1-2 short sentences that add context or invite comments.
- `hashtags`: 3-5 specific, relevant hashtags (with #), no generic spam.
- `reason`: one short sentence (in Dutch) explaining why this moment works.
{channel}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "score": {"type": "integer"},
                    "hook_text": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["start", "end", "score", "hook_text", "title", "description", "hashtags", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def format_transcript(segments: list[dict], sig: dict) -> str:
    loud = sig.get("loud", [])
    replayed = sig.get("replayed", [])
    lines = []
    for s in segments:
        tags = []
        z = max((p["z"] for p in loud if s["start"] - 1 <= p["t"] <= s["end"] + 1), default=None)
        if z is not None:
            tags.append(f"«LOUD+{z:.1f}»")
        if any(h["start"] < s["end"] and h["end"] > s["start"] for h in replayed):
            tags.append("«REPLAYED»")
        lines.append(f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']} {' '.join(tags)}".rstrip())
    return "\n".join(lines)


def select_with_claude(meta: dict, segments: list[dict], sig: dict, settings: dict,
                       approved_titles: list[str], language: str | None) -> list[dict]:
    import anthropic

    channel = ""
    if settings.get("channel_description"):
        channel += f"\nAbout the channel / audience: {settings['channel_description']}"
    if approved_titles:
        channel += "\nTitles the creator approved before (match this style): " + " | ".join(approved_titles)
    lang_hint = f" (language code: {language})" if language else ""
    system = SYSTEM_PROMPT.format(
        min_dur=settings["min_duration"], max_dur=settings["max_duration"], min_score=settings["min_score"],
        max_clips=settings["max_clips"], lang_hint=lang_hint, channel=channel,
    )
    user = (
        f"Video title: {meta.get('title', '')}\n"
        f"Channel: {meta.get('uploader', '')}\n"
        f"Duration: {meta.get('duration', 0):.0f} s\n"
        + (f"Video description: {meta['description'][:600]}\n" if meta.get("description") else "")
        + "\nTranscript:\n" + format_transcript(segments, sig)
    )

    client = anthropic.Anthropic(api_key=anthropic_key(), max_retries=3)
    kwargs = dict(
        model=settings["claude_model"],
        max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        # Bij een (zeldzame) weigering neemt de API automatisch een ander model
        with client.beta.messages.stream(
            **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError as e:
        log.warning("Fallback-optie geweigerd (%s), opnieuw zonder", e)
        with client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude weigerde deze video te beoordelen")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Antwoord van Claude was te lang (max_tokens)")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)["clips"]


def select_heuristic(meta: dict, segments: list[dict], sig: dict, settings: dict) -> list[dict]:
    """Zonder AI: rond de sterkste geluidspieken / terugspoelmomenten."""
    cands = [(p["t"], p["z"]) for p in sig.get("loud", [])]
    cands += [((h["start"] + h["end"]) / 2, 3.0 + h["value"]) for h in sig.get("replayed", [])]
    cands.sort(key=lambda c: c[1], reverse=True)
    target = min(35.0, float(settings["max_duration"]))
    out = []
    for t, z in cands:
        start = max(0.0, t - 12)
        seg_start = [s for s in segments if s["start"] <= start + 2]
        if seg_start:
            start = seg_start[-1]["start"]
        end = start + target
        seg_end = [s for s in segments if start + settings["min_duration"] <= s["end"] <= start + settings["max_duration"]]
        if seg_end:
            end = min(seg_end, key=lambda s: abs(s["end"] - (start + target)))["end"]
        text = " ".join(s["text"] for s in segments if s["start"] >= start and s["end"] <= end)
        first = text.split(".")[0][:57].strip()
        out.append({
            "start": start, "end": end, "score": min(10, round(5 + z)),
            "hook_text": "", "title": first or meta.get("title", "Clip")[:57],
            "description": "", "hashtags": [], "reason": f"Geluidspiek (z={z:.1f}) — gekozen zonder AI",
        })
    return out


def clean(clips: list[dict], settings: dict, duration: float) -> list[dict]:
    """Valideert tijden, verwijdert overlap, sorteert op score."""
    lo, hi = float(settings["min_duration"]), float(settings["max_duration"])
    result: list[dict] = []
    for c in sorted(clips, key=lambda c: c["score"], reverse=True):
        start = max(0.0, float(c["start"]))
        end = min(float(c["end"]), duration or float(c["end"]))
        if end - start > hi:
            end = start + hi
        if end - start < lo * 0.8:
            continue
        if any(start < r["end"] and end > r["start"] for r in result):
            continue
        tags = [h if h.startswith("#") else f"#{h}" for h in c.get("hashtags", [])]
        result.append({**c, "start": start, "end": end, "hashtags": [t.replace(" ", "") for t in tags]})
        if len(result) >= int(settings["max_clips"]):
            break
    return result


def snap_to_words(start: float, end: float, words: list[list], max_dur: float) -> tuple[float, float]:
    """Laat de clip precies vóór het eerste woord beginnen en net na het laatste eindigen."""
    if not words:
        return start, end
    inside = [w for w in words if w[0] >= start - 0.4 and w[1] <= end + 0.6]
    if not inside:
        return start, end
    new_start = max(inside[0][0] - 0.12, start - 0.4)
    ends = [w for w in inside if w[1] - new_start <= max_dur - 0.3]
    if not ends:
        return start, end
    last = ends[-1]
    # Te lang? Liefst stoppen aan het eind van een zin
    if inside[-1][1] - new_start > max_dur - 0.3:
        sentence_ends = [w for w in ends if w[2][-1:] in ".!?" and w[1] - new_start > max_dur * 0.5]
        if sentence_ends:
            last = sentence_ends[-1]
    return round(new_start, 3), round(last[1] + 0.35, 3)
