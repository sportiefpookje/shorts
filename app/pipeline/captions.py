"""Ondertitels in Shorts-stijl als ASS-bestand (voor ffmpeg/libass).

- 1-3 woorden tegelijk, groot en vet met dikke rand
- het woord dat nu gezegd wordt licht op in de accentkleur
- optioneel een hook-tekst bovenin tijdens de eerste seconden
"""
from __future__ import annotations

from ..config import FONT_NAME

# Verticale positie (midden van de tekst) per layout, in 1080x1920
CAPTION_Y = {"track": 1370, "center": 1370, "blur": 1430, "split": 768}
HOOK_Y = 250
HOOK_SECONDS = 3.0
MAX_WORDS = 3
MAX_CHARS = 16
# ASS-lettergrootte; libass rekent met winAscent+winDescent (Montserrat: 1,562 em)
CAP_SIZE = 118
HOOK_SIZE = 84


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(words: list[list]) -> list[list[list]]:
    groups: list[list[list]] = []
    cur: list[list] = []
    for w in words:
        if cur:
            gap = w[0] - cur[-1][1]
            chars = sum(len(x[2]) + 1 for x in cur) + len(w[2])
            if len(cur) >= MAX_WORDS or chars > MAX_CHARS or gap > 0.45 or cur[-1][2][-1:] in ".!?,":
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def build_ass(words: list[list], duration: float, layout: str, settings: dict, hook: str = "") -> str:
    """`words` zijn [[start, eind, woord], ...] relatief t.o.v. het begin van de clip."""
    accent = _ass_color(settings.get("caption_color", "#FFE600"))
    upper = settings.get("caption_uppercase", True)
    y = CAPTION_Y.get(layout, 1370)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT_NAME},{CAP_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,8,3,5,60,60,0,1
Style: Hook,{FONT_NAME},{HOOK_SIZE},&H00000000,&H00000000,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,3,22,0,8,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if hook.strip() and settings.get("hook_overlay", True):
        end = min(HOOK_SECONDS, duration)
        text = _esc(hook.strip())
        events.append(
            f"Dialogue: 1,{_ts(0)},{_ts(end)},Hook,,0,0,0,,"
            f"{{\\an8\\pos(540,{HOOK_Y})\\fad(80,250)\\fscx85\\fscy85\\t(0,120,\\fscx100\\fscy100)}}{text}"
        )
    if settings.get("captions", True) and words:
        groups = group_words([w for w in words if w[1] > 0 and w[0] < duration])
        for gi, g in enumerate(groups):
            next_start = groups[gi + 1][0][0] if gi + 1 < len(groups) else duration
            g_end = min(next_start, g[-1][1] + 0.5, duration)
            for wi, w in enumerate(g):
                ev_start = g[0][0] if wi == 0 else w[0]
                ev_end = g[wi + 1][0] if wi + 1 < len(g) else g_end
                if ev_end <= ev_start:
                    continue
                parts = []
                for j, x in enumerate(g):
                    t = _esc(x[2].upper() if upper else x[2])
                    if j == wi:
                        parts.append(f"{{\\c{accent}}}{t}{{\\c&H00FFFFFF&}}")
                    else:
                        parts.append(t)
                pop = "\\fscx70\\fscy70\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
                events.append(
                    f"Dialogue: 0,{_ts(ev_start)},{_ts(ev_end)},Cap,,0,0,0,,"
                    f"{{\\an5\\pos(540,{y}){pop}}}{' '.join(parts)}"
                )
    return header + "\n".join(events) + "\n"
