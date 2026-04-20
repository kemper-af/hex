"""
Reschedulability scoring.

Inputs: an `Event` + the `reschedule:` block of config.yaml.
Output: a `Movability` verdict containing:
  - score: int (0 = hard-locked, 100 = very flexible)
  - category: "locked" | "borderline" | "flex"
  - reasons: human-readable bullets explaining the verdict
  - confirm_required: bool (True if config says always_confirm_before_moving)

Multiple signals are blended; any single strong "lock" signal dominates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .calendar_client import Event
from .config import load_config


@dataclass
class Movability:
    event_id: str
    summary: str
    score: int
    category: str   # "locked" | "borderline" | "flex"
    reasons: list[str] = field(default_factory=list)
    confirm_required: bool = True


def _rules() -> dict[str, Any]:
    return load_config().get("reschedule", {}) or {}


def classify(event: Event) -> Movability:
    rules = _rules()
    reasons: list[str] = []
    score = 50  # neutral default
    hard_lock = False
    hard_flex = False

    # --- Title keywords ---
    summary_l = (event.summary or "").lower()
    for kw in rules.get("lock_keywords", []) or []:
        if kw.lower() in summary_l:
            reasons.append(f"title contains lock keyword \u201c{kw}\u201d")
            hard_lock = True
    for kw in rules.get("flex_keywords", []) or []:
        if kw.lower() in summary_l:
            reasons.append(f"title contains flex keyword \u201c{kw}\u201d")
            score += 15
            hard_flex = True

    # --- Color ---
    locked_colors = set(str(c) for c in rules.get("locked_color_ids", []) or [])
    flex_colors = set(str(c) for c in rules.get("flex_color_ids", []) or [])
    if event.color_id and str(event.color_id) in locked_colors:
        reasons.append(f"calendar color id={event.color_id} marked locked in config")
        hard_lock = True
    elif event.color_id and str(event.color_id) in flex_colors:
        reasons.append(f"calendar color id={event.color_id} marked flexible in config")
        score += 20
        hard_flex = True

    # --- Attendees / organizer ---
    if rules.get("solo_is_flex", True) and event.attendee_count <= 1:
        reasons.append("solo event (no other attendees)")
        score += 25
    if rules.get("organized_by_me_is_flex", True) and event.organizer_self:
        reasons.append("you're the organizer")
        score += 10
    if rules.get("organized_by_others_is_locked_default", True) and not event.organizer_self and event.attendee_count > 1:
        reasons.append("organized by someone else, multi-attendee \u2192 treat as locked by default")
        score -= 20
        # Not a hard lock; user may still say "ask them to move."

    # --- External attendees get extra caution ---
    if event.has_external_attendees:
        reasons.append("has external attendees (outside your org)")
        score -= 10

    # --- Resolve final category ---
    if hard_lock:
        score = 0
        category = "locked"
    else:
        score = max(0, min(100, score))
        if hard_flex and score >= 60:
            category = "flex"
        elif score >= 70:
            category = "flex"
        elif score <= 30:
            category = "locked"
        else:
            category = "borderline"

    confirm_required = bool(rules.get("always_confirm_before_moving", True))

    if not reasons:
        reasons.append("no strong signals either way")

    return Movability(
        event_id=event.id,
        summary=event.summary,
        score=score,
        category=category,
        reasons=reasons,
        confirm_required=confirm_required,
    )


def classify_many(events: list[Event]) -> list[Movability]:
    return [classify(e) for e in events]


def find_conflicts(events: list[Event], start, end) -> list[Event]:
    """Return events overlapping the [start, end) window."""
    return [e for e in events if e.start < end and e.end > start]
