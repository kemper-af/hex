# Hex — Calendar & Agenda Assistant

A chat-driven scheduling assistant for your personal and professional Google Calendars.
You talk to Claude; Claude talks to Google via the Calendar + Gmail MCP connectors you
already have enabled in Claude's settings, and uses a small Python library in this
folder for the bits that are about *your* preferences (which meetings are movable,
how the agenda should look, what your working hours are).

## How it works

```
  You (in chat)
      ↓
  Claude
      ├──► Calendar MCP  (list_events, create_event, update_event, respond_to_event, suggest_time…)
      ├──► Gmail MCP     (create_draft)
      └──► this library:
             config.yaml        — your preferences
             reschedule.py      — movability scoring per event
             propose.py         — slot finder that respects lunch + buffers
             agenda.py          — text + HTML rendering
             calendar_client.py — Event dataclass + MCP-JSON → Event converter
```

Everything confirms before mutating your calendar or sending email. Gmail is create-draft
only (no direct send) because that's the connector's capability — which is fine for a
one-click-send workflow.

## What to say

- "What's on my calendar today?" / "…tomorrow?" / "…next Tuesday morning?"
- "Any pending invites I haven't responded to?"
- "Propose three 30-min slots next week for a meeting with alice@example.com and bob@example.com." — I'll use the MCP's `suggest_time` across your calendar and theirs, then re-rank with `propose.py` so lunch stays free and each slot has buffer.
- "Schedule 'Budget sync' with alice@example.com Friday 2–3pm." — I'll show you the event I'm about to create, confirm, then create it.
- "I want to move my Tuesday 2pm. What can shift?" — I'll pull the conflicts and score each with `reschedule.py` based on `config.yaml`; you confirm per event.
- "Accept the thesis defense invite and decline the alumni mixer."
- "Draft tomorrow's agenda email." — I'll create a Gmail draft, addressed per `config.yaml`, for you to review and send.

## Configuring your preferences

Everything lives in [`config.yaml`](./config.yaml):

- `timezone` — IANA name (default `America/New_York`).
- `calendar_tags` — which of your Google calendars count as "work" vs "personal" vs "informational" (holidays, school calendars). I've pre-populated this with the calendars your MCP is showing me; adjust as needed.
- `working_hours` — per weekday; set a day to `null` to block it.
- `daily_blocks` — daily recurring blocks like lunch.
- `default_buffer_minutes` — breathing room around existing meetings.
- `reschedule` — the movability rules:
  - `lock_keywords` / `flex_keywords` — title substrings that lock or flex events.
  - `locked_color_ids` / `flex_color_ids` — Google Calendar color IDs (1–11) to treat as locked or flexible.
  - `solo_is_flex`, `organized_by_me_is_flex`, `organized_by_others_is_locked_default` — attendee/organizer rules.
  - `always_confirm_before_moving` — I'll always ask you before moving anything.
- `agenda` — where to address morning drafts, subject template, whether to include attached docs and a tomorrow-preview.

## Files

| File | Purpose |
|------|---------|
| `config.yaml` | Your preferences |
| `cal_assistant/config.py` | Config loader |
| `cal_assistant/calendar_client.py` | `Event` dataclass + MCP JSON → `Event` conversion |
| `cal_assistant/reschedule.py` | Movability classifier |
| `cal_assistant/propose.py` | Slot finder with preference-aware scoring |
| `cal_assistant/agenda.py` | Text + HTML renderers |

## Development

Install dev deps:

```
pip install -r requirements.txt --break-system-packages
```

Run the smoke tests:

```
python ../tests/smoke_test.py
```
