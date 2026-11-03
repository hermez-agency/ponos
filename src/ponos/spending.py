"""What the sessions cost, session by session, as a CSV to justify an invoice.

The statistics give a project's cost as a sum; an agency that re-bills a client
needs the lines it adds up. Each row is one line of the runner's history — a
session that ended, whatever it came to — and the rows of a project over a
period are exactly the ones its page sums: the same lines, selected by the same
means (`web/statistics.figures`). So the total of the column is the figure on
the page, to the cent.

Which lines belong to a project depends on who is asking. The console has the
board and says whose a ticket is *today*, as the statistics do; the command
line has no board and goes by the project each line carries, the name it had
when the session ran. The two differ only for a ticket moved to another
project since, or deleted.

The board is also where the type, the sub-type and the link come from; without
it they are empty, except the link, which Notion resolves from the bare id.

Dates are this machine's days and hours, as the statistics count them. The
file is the `csv` module's, quoting what needs it, so an accent or a comma in a
title survives; a console download adds a byte-order mark for the spreadsheets
that would otherwise read UTF-8 as Latin-1.
"""

from __future__ import annotations

import calendar
import csv
import io
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from . import timestamps

COLUMNS = (
    "date",
    "ticket",
    "lien",
    "type",
    "sous-type",
    "modèle",
    "statut final",
    "durée (s)",
    "coût (USD)",
    "PR",
)

NOTION = "https://www.notion.so/"


def month_span(month: str) -> tuple[date, date]:
    """The first and last day of `2026-10`, refused when it is not a month."""
    try:
        year, number = (int(part) for part in month.split("-"))
        first = date(year, number, 1)
    except ValueError:
        raise ValueError(f"a month is written 2026-10, not {month!r}") from None
    return first, first.replace(day=calendar.monthrange(year, number)[1])


def window(first: date, last: date, zone: tzinfo | None = None) -> tuple[str, str]:
    """The UTC timestamps that hold every moment of the days `first` to `last`, a day to spare.

    The history is dated in UTC and the days are the machine's: the day of
    margin on each side is what a zone's offset can reach, and `rows` then
    keeps the lines whose own day is in the period.
    """
    start = datetime.combine(first - timedelta(days=1), time.min, tzinfo=UTC)
    end = datetime.combine(last + timedelta(days=2), time.min, tzinfo=UTC)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def rows(
    history: Iterable[dict[str, Any]],
    first: date,
    last: date,
    *,
    tickets: Iterable[dict[str, Any]] | None = None,
    project: str | None = None,
    models: dict[str, str] | None = None,
    zone: tzinfo | None = None,
) -> list[list[str]]:
    """One row per session ended between `first` and `last`, oldest first.

    With `tickets` (the board's cards), `project` keeps the lines of the tickets
    that are that project's now; without, the lines that name it, whatever the
    case. No `project` is every line, the tickets of no project and the ones
    gone from the board included — as the global statistics count them.
    """
    cards = {str(card.get("id", "")).replace("-", ""): card for card in tickets or ()}
    wanted = None if project is None else project.casefold()
    found = []
    for entry in history:
        stamp = timestamps.parse(entry.get("at", ""), naive="utc")
        if stamp is None or not first <= stamp.astimezone(zone).date() <= last:
            continue
        key = str(entry.get("id", "")).replace("-", "")
        card = cards.get(key, {})
        if wanted is not None:
            named = str(card.get("project") or "") if tickets is not None else entry.get("project")
            if str(named or "").casefold() != wanted:
                continue
        found.append((stamp, entry, key, card))
    found.sort(key=lambda item: item[0])
    return [
        _row(stamp.astimezone(zone), entry, key, card, models or {})
        for stamp, entry, key, card in found
    ]


def _row(
    stamp: datetime, entry: dict[str, Any], key: str, card: dict[str, Any], models: dict[str, str]
) -> list[str]:
    seconds = entry.get("seconds")
    cost = entry.get("cost_usd")
    return [
        stamp.strftime("%Y-%m-%d %H:%M"),
        str(entry.get("ticket") or card.get("title") or ""),
        str(card.get("url") or (NOTION + key if key else "")),
        str(card.get("type") or ""),
        str(card.get("subtype") or ""),
        models.get(str(entry.get("session") or ""), ""),
        str(entry.get("status") or ""),
        "" if not isinstance(seconds, (int, float)) else f"{seconds:.0f}",
        "" if not isinstance(cost, (int, float)) else f"{cost:.4f}",
        str(entry.get("pull_request") or entry.get("merged") or ""),
    ]


def write(lines: list[list[str]]) -> str:
    """The CSV text of the header and `lines`."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS)
    writer.writerows(lines)
    return buffer.getvalue()
