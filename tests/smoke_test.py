"""Smoke test for Hex's pure-Python logic.

No Google or MCP calls — we feed Event objects (or the JSON shapes the MCP returns)
directly into the library and check the output.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from cal_assistant import agenda, calendar_client as cc, reschedule
from cal_assistant.config import load_config
from cal_assistant import propose as prop


def test_config_loads():
    cfg = load_config()
    assert cfg["timezone"] == "America/New_York"
    assert "calendar_tags" in cfg and "working_hours" in cfg and "reschedule" in cfg
    print("[PASS] config.yaml loads with expected top-level keys")


def _fake_event(**overrides):
    tz = ZoneInfo("America/New_York")
    base = dict(
        id="e1", summary="Test",
        start=datetime(2026, 4, 20, 10, 0, tzinfo=tz),
        end=datetime(2026, 4, 20, 11, 0, tzinfo=tz),
        all_day=False, calendar_id="primary", location="", description="",
        organizer_email="", organizer_self=False, attendees=[],
        color_id=None, attachments=[], hangout_link="", html_link="",
        source="work", raw={},
    )
    base.update(overrides)
    return cc.Event(**base)


def test_from_mcp_event_google_shape():
    raw = {
        "id": "evt1",
        "summary": "Thesis discussion",
        "start": {"dateTime": "2026-04-20T14:00:00-04:00"},
        "end":   {"dateTime": "2026-04-20T15:00:00-04:00"},
        "attendees": [
            {"email": "me@x", "self": True, "responseStatus": "accepted"},
            {"email": "advisor@uni.edu", "displayName": "Advisor", "responseStatus": "needsAction"},
        ],
        "organizer": {"email": "me@x", "self": True},
        "colorId": "7",
        "location": "Office 2-314",
    }
    e = cc.from_mcp_event(raw, calendar_id="akemper@ncsu.edu", source="work")
    assert e.summary == "Thesis discussion"
    assert e.start.hour == 14
    assert e.attendee_count == 2
    assert e.has_external_attendees
    assert e.color_id == "7"
    assert e.source == "work"
    assert e.calendar_id == "akemper@ncsu.edu"
    print("[PASS] from_mcp_event parses standard Google shape")


def test_from_mcp_event_all_day():
    raw = {
        "id": "evt2",
        "summary": "Spring break",
        "start": {"date": "2026-04-13"},
        "end":   {"date": "2026-04-20"},
    }
    e = cc.from_mcp_event(raw)
    assert e.all_day is True
    print("[PASS] from_mcp_event handles all-day events")


def test_reschedule_locked_keyword():
    e = _fake_event(summary="Board meeting")
    m = reschedule.classify(e)
    assert m.category == "locked"
    assert any("lock keyword" in r for r in m.reasons)
    print("[PASS] reschedule: 'Board meeting' is locked")


def test_reschedule_flex_solo():
    e = _fake_event(
        summary="Focus time",
        attendees=[{"self": True, "email": "me@x"}],
        organizer_self=True,
    )
    m = reschedule.classify(e)
    assert m.category in ("flex", "borderline")
    print(f"[PASS] reschedule: solo focus event -> {m.category} (score {m.score})")


def test_reschedule_external_organizer():
    e = _fake_event(
        summary="Project sync",
        organizer_self=False,
        organizer_email="external@partner.com",
        attendees=[
            {"self": True, "email": "me@x"},
            {"self": False, "email": "external@partner.com"},
            {"self": False, "email": "teammate@x.com"},
        ],
    )
    m = reschedule.classify(e)
    assert m.category in ("locked", "borderline"), m.category
    print(f"[PASS] reschedule: externally-organized multi-attendee -> {m.category}")


def test_reschedule_confirm_required():
    e = _fake_event(
        summary="[flex] Coffee",
        organizer_self=True,
        attendees=[{"self": True}],
    )
    m = reschedule.classify(e)
    assert m.confirm_required is True
    print("[PASS] reschedule: confirm_required honored")


def test_busy_intervals_merges_and_skips_all_day():
    tz = ZoneInfo("America/New_York")
    events = [
        _fake_event(id="a",
                    start=datetime(2026,4,20,10,0,tzinfo=tz),
                    end=datetime(2026,4,20,11,0,tzinfo=tz)),
        _fake_event(id="b",
                    start=datetime(2026,4,20,10,30,tzinfo=tz),
                    end=datetime(2026,4,20,11,30,tzinfo=tz)),
        _fake_event(id="c", all_day=True,
                    start=datetime(2026,4,20,0,0,tzinfo=timezone.utc),
                    end=datetime(2026,4,21,0,0,tzinfo=timezone.utc)),
    ]
    merged = cc.busy_intervals(events)
    assert len(merged) == 1
    assert merged[0][0].hour == 10 and merged[0][1].hour == 11 and merged[0][1].minute == 30
    print("[PASS] busy_intervals merges overlaps and skips all-day")


def test_propose_empty_monday():
    slots = prop.propose_slots(
        duration_minutes=30,
        busy=[],
        start_date=date(2026, 4, 20),   # Monday
        end_date=date(2026, 4, 20),
        max_results=20,
    )
    assert slots
    for s in slots:
        assert 9 <= s.start.hour < 17
        assert s.start.hour != 12, f"lunch block leaked: {s.start}"
    print(f"[PASS] propose: {len(slots)} slots on empty Mon 4/20, none during lunch")


def test_propose_with_busy_morning():
    tz = ZoneInfo("America/New_York")
    busy = [(datetime(2026,4,20,9,0,tzinfo=tz), datetime(2026,4,20,12,0,tzinfo=tz))]
    slots = prop.propose_slots(
        duration_minutes=30,
        busy=busy,
        start_date=date(2026,4,20),
        end_date=date(2026,4,20),
        max_results=10,
    )
    for s in slots:
        assert s.start.hour >= 13, f"slot leaked into busy morning: {s.start}"
    print("[PASS] propose: busy morning respected")


def test_propose_weekend_excluded():
    slots = prop.propose_slots(
        duration_minutes=30,
        busy=[],
        start_date=date(2026, 4, 18),   # Saturday
        end_date=date(2026, 4, 19),
        max_results=5,
    )
    assert slots == []
    print("[PASS] propose: weekend returns no slots (per working_hours)")


def test_agenda_text_render():
    tz = ZoneInfo("America/New_York")
    d = date(2026, 4, 20)
    events = [
        _fake_event(
            summary="Standup", source="work",
            start=datetime(2026,4,20,9,30,tzinfo=tz),
            end=datetime(2026,4,20,9,45,tzinfo=tz),
            attendees=[{"self":True}, {"displayName":"Alice","email":"a@x"}],
        ),
        _fake_event(
            summary="Office hours", source="work",
            location="Engineering Bldg 2-314",
            start=datetime(2026,4,20,14,0,tzinfo=tz),
            end=datetime(2026,4,20,15,0,tzinfo=tz),
            description="Agenda: https://docs.example.com/oh",
        ),
    ]
    text = agenda.render_text(d, events)
    assert "Standup" in text and "Office hours" in text
    assert "Alice" in text
    assert "Engineering Bldg" in text
    assert "https://docs.example.com/oh" in text
    assert "[work]" in text
    print("[PASS] agenda.render_text contains expected fields")


def test_agenda_html_render():
    tz = ZoneInfo("America/New_York")
    d = date(2026, 4, 20)
    events = [_fake_event(
        summary="Budget sync",
        start=datetime(2026,4,20,10,0,tzinfo=tz),
        end=datetime(2026,4,20,10,30,tzinfo=tz),
    )]
    html = agenda.render_html(d, events)
    assert "<table" in html and "Budget sync" in html and "</html>" in html
    print("[PASS] agenda.render_html emits well-formed HTML")


if __name__ == "__main__":
    test_config_loads()
    test_from_mcp_event_google_shape()
    test_from_mcp_event_all_day()
    test_reschedule_locked_keyword()
    test_reschedule_flex_solo()
    test_reschedule_external_organizer()
    test_reschedule_confirm_required()
    test_busy_intervals_merges_and_skips_all_day()
    test_propose_empty_monday()
    test_propose_with_busy_morning()
    test_propose_weekend_excluded()
    test_agenda_text_render()
    test_agenda_html_render()
    print("\nAll smoke tests passed.")
