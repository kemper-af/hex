"""
Render a daily agenda in two formats: plain text (for chat) and HTML (for email drafts).

Input: a list of `Event`s (already fetched via MCP and converted with
`calendar_client.from_mcp_events`). This module is pure presentation logic — no
calendar API calls here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from . import calendar_client as cc
from .config import load_config


LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass
class AgendaDay:
    day: date
    events: list[cc.Event]


def _tz() -> ZoneInfo:
    return ZoneInfo(load_config().get("timezone", "UTC"))


def _fmt_time(dt: datetime) -> str:
    local = dt.astimezone(_tz())
    return local.strftime("%-I:%M %p").lstrip("0")


def _extract_links(description: str) -> list[str]:
    if not description:
        return []
    clean = re.sub(r"<[^>]+>", " ", description)
    # Trim trailing punctuation that isn't part of a URL.
    raw = LINK_RE.findall(clean)
    cleaned = [r.rstrip(").,;:'\"") for r in raw]
    return list(dict.fromkeys(cleaned))


def _event_location(ev: cc.Event) -> str:
    if ev.hangout_link:
        return f"Google Meet: {ev.hangout_link}"
    if ev.location:
        return ev.location
    return ""


def _event_attendees(ev: cc.Event, cap: int = 6) -> str:
    names = []
    for a in ev.attendees or []:
        if a.get("self"):
            continue
        name = a.get("displayName") or a.get("email", "")
        if name:
            names.append(name)
    if not names:
        return ""
    if len(names) > cap:
        return ", ".join(names[:cap]) + f" (+{len(names) - cap} more)"
    return ", ".join(names)


# ---------- text (chat) render ----------


def render_text(
    d: date,
    events: list[cc.Event],
    *,
    include_documents: bool = True,
) -> str:
    tz = _tz()
    header = f"Agenda for {d.strftime('%A, %B %-d, %Y')} ({tz.key})"
    lines = [header, "=" * len(header), ""]
    if not events:
        lines.append("Nothing scheduled. Clear day.")
        return "\n".join(lines)

    for ev in events:
        tag = f"  [{ev.source}]" if ev.source else ""
        if ev.all_day:
            lines.append(f"[all day] {ev.summary}{tag}")
        else:
            lines.append(f"{_fmt_time(ev.start)}\u2013{_fmt_time(ev.end)}  {ev.summary}{tag}")
        loc = _event_location(ev)
        if loc:
            lines.append(f"    \u2022 Where: {loc}")
        atts = _event_attendees(ev)
        if atts:
            lines.append(f"    \u2022 With: {atts}")
        if include_documents:
            docs: list[str] = []
            for att in ev.attachments or []:
                title = att.get("title") or att.get("fileUrl", "attachment")
                url = att.get("fileUrl", "")
                docs.append(f"{title} \u2014 {url}" if url else title)
            for link in _extract_links(ev.description):
                if all(link not in d_ for d_ in docs):
                    docs.append(link)
            for d_ in docs[:5]:
                lines.append(f"    \u2022 Doc: {d_}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- HTML (email) render ----------


def render_html(
    d: date,
    events: list[cc.Event],
    *,
    include_documents: bool = True,
    preview_tomorrow: list[cc.Event] | None = None,
) -> str:
    tz = _tz()
    parts = [
        "<!doctype html><html><body style=\"font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; color:#222;\">",
        f"<h2 style=\"margin-bottom:4px;\">Agenda for {escape(d.strftime('%A, %B %-d, %Y'))}</h2>",
        f"<div style=\"color:#666;font-size:12px;margin-bottom:16px;\">Timezone: {escape(tz.key)}</div>",
    ]
    if not events:
        parts.append("<p><em>Nothing scheduled. Clear day.</em></p>")
    else:
        parts.append("<table style=\"border-collapse:collapse;width:100%;\">")
        for ev in events:
            tstr = "all day" if ev.all_day else f"{_fmt_time(ev.start)}\u2013{_fmt_time(ev.end)}"
            loc = _event_location(ev)
            atts = _event_attendees(ev)
            doc_html = ""
            if include_documents:
                docs: list[str] = []
                for att in ev.attachments or []:
                    title = att.get("title") or "attachment"
                    url = att.get("fileUrl", "")
                    docs.append(
                        f'<a href="{escape(url)}">{escape(title)}</a>' if url else escape(title)
                    )
                for link in _extract_links(ev.description):
                    docs.append(f'<a href="{escape(link)}">{escape(link)}</a>')
                if docs:
                    doc_html = (
                        "<div style=\"margin-top:4px;font-size:13px;color:#444;\">"
                        + " &middot; ".join(docs[:6])
                        + "</div>"
                    )

            meta_bits = []
            if loc:
                meta_bits.append(f"<span>{escape(loc)}</span>")
            if atts:
                meta_bits.append(f"<span>with {escape(atts)}</span>")
            if ev.source:
                meta_bits.append(f"<span style=\"color:#999;\">{escape(ev.source)}</span>")
            meta_html = " &middot; ".join(meta_bits)

            parts.append(
                "<tr style=\"border-top:1px solid #eee;vertical-align:top;\">"
                f"<td style=\"padding:10px 12px 10px 0;font-weight:600;white-space:nowrap;\">{escape(tstr)}</td>"
                f"<td style=\"padding:10px 0;\">"
                f"<div style=\"font-weight:600;\">{escape(ev.summary)}</div>"
                f"<div style=\"font-size:13px;color:#555;margin-top:2px;\">{meta_html}</div>"
                f"{doc_html}"
                "</td></tr>"
            )
        parts.append("</table>")

    if preview_tomorrow:
        parts.append("<h3 style=\"margin-top:24px;\">Tomorrow's preview</h3><ul>")
        for ev in preview_tomorrow:
            tstr = "all day" if ev.all_day else _fmt_time(ev.start)
            parts.append(f"<li>{escape(tstr)} \u2014 {escape(ev.summary)}</li>")
        parts.append("</ul>")

    parts.append("</body></html>")
    return "".join(parts)
