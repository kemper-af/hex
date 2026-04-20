"""
Find candidate meeting slots that honor config.yaml's working hours, daily blocks
(e.g. lunch), and buffer preferences.

This is complementary to the Calendar MCP's `suggest_time`. `suggest_time` is great at
multi-attendee availability; this module adds the config-aware flavor: it keeps lunch
free, puts a buffer around existing meetings, and prefers mid-morning / mid-afternoon
windows.

Typical flow (when Claude runs it):
  1. Fetch events from the MCP's `list_events` for each calendar of interest.
  2. Convert to `Event`s via calendar_client.from_mcp_events.
  3. Call `busy_intervals(events)` to get merged busy tuples.
  4. Pass them into `propose_slots(...)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import load_config


WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass
class Slot:
    start: datetime
    end: datetime
    score: float
    notes: list[str]

    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def _tz() -> ZoneInfo:
    return ZoneInfo(load_config().get("timezone", "UTC"))


def _parse_hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _working_window(d: date) -> tuple[datetime, datetime] | None:
    wh = load_config().get("working_hours", {}) or {}
    key = WEEKDAY_KEYS[d.weekday()]
    spec = wh.get(key)
    if not spec:
        return None
    tz = _tz()
    start = datetime.combine(d, _parse_hm(spec["start"]), tzinfo=tz)
    end = datetime.combine(d, _parse_hm(spec["end"]), tzinfo=tz)
    return start, end


def _daily_block_intervals(d: date) -> list[tuple[datetime, datetime]]:
    blocks = load_config().get("daily_blocks", []) or []
    tz = _tz()
    return [
        (
            datetime.combine(d, _parse_hm(b["start"]), tzinfo=tz),
            datetime.combine(d, _parse_hm(b["end"]), tzinfo=tz),
        )
        for b in blocks
    ]


def _free_subranges(
    window: tuple[datetime, datetime],
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    ws, we = window
    rel = []
    for bs, be in busy:
        if be <= ws or bs >= we:
            continue
        rel.append((max(bs, ws), min(be, we)))
    rel.sort()
    free: list[tuple[datetime, datetime]] = []
    cursor = ws
    for bs, be in rel:
        if bs > cursor:
            free.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < we:
        free.append((cursor, we))
    return free


def _score(slot_start: datetime, today: date) -> float:
    score = 100.0
    days_out = (slot_start.date() - today).days
    score -= max(0, days_out) * 2
    hour = slot_start.hour + slot_start.minute / 60.0
    if 10 <= hour <= 11 or 14 <= hour <= 15:
        score += 10
    elif hour < 9.5 or hour > 16:
        score -= 8
    return score


def propose_slots(
    duration_minutes: int,
    busy: list[tuple[datetime, datetime]],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    buffer_minutes: int | None = None,
    step_minutes: int = 30,
    max_results: int = 5,
) -> list[Slot]:
    """
    Return up to `max_results` candidate slots, best first.

    Args:
        duration_minutes: Meeting length.
        busy: Your merged busy intervals (use calendar_client.busy_intervals to build).
        start_date, end_date: Search window (inclusive). Defaults to today..today+14.
        buffer_minutes: Defaults to config.default_buffer_minutes.
        step_minutes: Granularity of candidate start times.
        max_results: Limit on returned slots (at most one per (date, hour)).
    """
    cfg = load_config()
    tz = _tz()
    if buffer_minutes is None:
        buffer_minutes = int(cfg.get("default_buffer_minutes", 10))
    today = datetime.now(tz).date()
    start_date = start_date or today
    end_date = end_date or (start_date + timedelta(days=14))

    dur = timedelta(minutes=duration_minutes)
    buf = timedelta(minutes=buffer_minutes)

    candidates: list[Slot] = []
    d = start_date
    while d <= end_date:
        work = _working_window(d)
        if not work:
            d += timedelta(days=1)
            continue

        all_busy_today = busy + _daily_block_intervals(d)
        free_ranges = _free_subranges(work, all_busy_today)

        for fs, fe in free_ranges:
            usable_start = fs + buf if fs > work[0] else fs
            usable_end = fe - buf if fe < work[1] else fe
            if usable_end - usable_start < dur:
                continue

            t = usable_start
            minute_offset = t.minute % step_minutes
            if minute_offset:
                t = t + timedelta(minutes=(step_minutes - minute_offset))
            while t + dur <= usable_end:
                candidates.append(Slot(
                    start=t,
                    end=t + dur,
                    score=_score(t, today),
                    notes=[],
                ))
                t += timedelta(minutes=step_minutes)

        d += timedelta(days=1)

    candidates.sort(key=lambda s: (-s.score, s.start))
    seen = set()
    pruned: list[Slot] = []
    for c in candidates:
        key = (c.start.date(), c.start.hour)
        if key in seen:
            continue
        seen.add(key)
        pruned.append(c)
        if len(pruned) >= max_results:
            break
    return pruned
