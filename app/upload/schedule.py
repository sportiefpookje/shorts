"""Publicatietijden verdelen over vaste dagelijkse tijdsloten."""
from __future__ import annotations

from datetime import datetime, timedelta


def parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def next_slots(n: int, slots: list[str], taken: list[datetime], after: datetime | None = None) -> list[datetime]:
    """Geeft n vrije slot-tijden (lokale tijdzone, tz-aware) na `after`."""
    now = (after or datetime.now().astimezone() + timedelta(minutes=30))
    times = sorted({tuple(int(p) for p in s.split(":")[:2]) for s in slots if ":" in s}) or [(12, 0)]
    taken_keys = {t.astimezone().replace(second=0, microsecond=0) for t in taken}
    out: list[datetime] = []
    day = now.date()
    while len(out) < n:
        for h, m in times:
            cand = datetime(day.year, day.month, day.day, h, m).astimezone()
            if cand > now and cand not in taken_keys:
                out.append(cand)
                if len(out) == n:
                    break
        day += timedelta(days=1)
    return out
