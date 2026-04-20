"""
Event dataclass + helpers for normalizing events returned by the Google Calendar MCP
connector.

Claude talks to Google Calendar through the MCP tools (list_events, create_event, etc.)
and passes the raw JSON dicts into `from_mcp_event()` here to get a typed `Event` that
`reschedule.py` and `agenda.py` can work with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateparser


@dataclass
class Event:
    """Normalized view of a Google Calendar event."""
    id: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    calendar_id: str = ""
    location: str = ""
    description: str = ""
    organizer_email: str = ""
    organizer_self: bool = False
    attendees: list[dict[str, Any]] = field(default_factory=list)
    color_id: str | None = None
    attachments: list[dict[str, str]] = field(default_factory=list)
    hangout_link: str = ""
    html_link: str = ""
    # Source label — not authoritative; useful when an agenda mixes calendars
    # and you want to tag rows (e.g. "work", "personal"). Set by the caller.
    source: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def attendee_count(self) -> int:
        return len(self.attendees)

    @property
    def has_external_attendees(self) -> bool:
        return any(not a.get("self") for a in self.attendees)


def _parse_time(t: Any) -> tuple[datetime, bool]:
    """
    Handle both:
      - Google API shape: {"dateTime": "...", "timeZone": "..."} or {"date": "YYYY-MM-DD"}
      - Plain ISO string (which is what the MCP sometimes returns flattened)
    Returns (datetime, is_all_day).
    """
    if isinstance(t, str):
        return dateparser.isoparse(t), False
    if not isinstance(t, dict):
        raise ValueError(f"Unrecognized time value: {t!r}")
    if "dateTime" in t:
        return dateparser.isoparse(t["dateTime"]), False
    if "date" in t:
        d = dateparser.isoparse(t["date"]).date()
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc), True
    raise ValueError(f"Unrecognized time dict: {t!r}")


def from_mcp_event(
    raw: dict[str, Any],
    *,
    calendar_id: str = "",
    source: str = "",
) -> Event:
    """
    Convert an event dict returned by the Google Calendar MCP tools into our Event.

    The MCP's JSON shape tracks the Google Calendar v3 REST schema fairly closely;
    occasionally fields come through with slightly different casing or flattening.
    This function is tolerant of both camelCase ("dateTime") and already-flat
    ISO strings for start/end.
    """
    start_raw = raw.get("start") or raw.get("startTime") or raw.get("start_time")
    end_raw = raw.get("end") or raw.get("endTime") or raw.get("end_time")
    if start_raw is None or end_raw is None:
        raise ValueError(f"Event missing start/end: id={raw.get('id')}")

    start, all_day_s = _parse_time(start_raw)
    end, all_day_e = _parse_time(end_raw)

    organizer = raw.get("organizer") or {}

    attendees = raw.get("attendees") or []
    # Accept flattened attendee shape too.
    normalized_attendees = []
    for a in attendees:
        if isinstance(a, str):
            normalized_attendees.append({"email": a, "self": False})
        else:
            normalized_attendees.append(a)

    return Event(
        id=raw.get("id") or raw.get("eventId") or "",
        summary=raw.get("summary") or raw.get("title") or "(no title)",
        start=start,
        end=end,
        all_day=bool(all_day_s and all_day_e),
        calendar_id=calendar_id or raw.get("calendarId", "") or "",
        location=raw.get("location") or "",
        description=raw.get("description") or "",
        organizer_email=(organizer.get("email") if isinstance(organizer, dict) else "") or "",
        organizer_self=bool(organizer.get("self")) if isinstance(organizer, dict) else False,
        attendees=normalized_attendees,
        color_id=raw.get("colorId") or raw.get("color_id"),
        attachments=raw.get("attachments") or [],
        hangout_link=raw.get("hangoutLink") or raw.get("hangout_link") or "",
        html_link=raw.get("htmlLink") or raw.get("html_link") or "",
        source=source,
        raw=raw,
    )


def from_mcp_events(
    events: list[dict[str, Any]],
    *,
    calendar_id: str = "",
    source: str = "",
) -> list[Event]:
    return [from_mcp_event(e, calendar_id=calendar_id, source=source) for e in events]


# ---------- window / conflict helpers ----------


def find_conflicts(events: list[Event], start: datetime, end: datetime) -> list[Event]:
    """Return events overlapping the half-open window [start, end)."""
    return [e for e in events if e.start < end and e.end > start]


def busy_intervals(events: list[Event]) -> list[tuple[datetime, datetime]]:
    """
    Extract (start, end) busy intervals from a list of events, merging overlaps.
    Skips all-day events (treat them as informational, not blocking) unless you
    want to pass a filtered list in.
    """
    intervals = [(e.start, e.end) for e in events if not e.all_day]
    if not intervals:
        return []
    intervals.sort()
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged
