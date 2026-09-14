"""Time-window resolution in factory-local time.

Every MES tool takes a time window. Windows are resolved here, once, in Python
rather than in SQL, so that:

  * "today" means today in the *factory's* timezone, not the database server's
    UTC (a scoping decision — see docs/05-seed-data.md §6);
  * the rule is unit-testable without a database;
  * every tool result can report the exact dates it used, which is what makes
    an answer explainable.

The most important rule is `this_week`. Scoping fixed "this week" as the current
ISO week with elapsed days excluded, because a factory manager asking "how many
can we produce this week" means the hours still ahead, not the whole week.
`full_week` is kept for the rare question that really does mean Monday--Sunday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

WINDOW_LABELS: dict[str, str] = {
    "today": "The current factory day.",
    "tomorrow": "The next calendar day.",
    "yesterday": "The previous calendar day (may be a non-working day).",
    "this_week": "The remaining part of the current ISO week, from today to Sunday.",
    "full_week": "The whole current ISO week, Monday to Sunday, including elapsed days.",
    "next_week": "The next ISO week, Monday to Sunday.",
    "last_week": "The previous ISO week, Monday to Sunday.",
    "last_7_days": "The seven days ending yesterday.",
    "last_30_days": "The thirty days ending yesterday.",
}


class WindowError(ValueError):
    """Raised when a window specification cannot be resolved."""


class ResolvedWindow(BaseModel):
    """A concrete, inclusive date range plus the reasoning that produced it."""

    label: str = Field(
        description="The requested window, e.g. 'this_week' or '2026-09-08..2026-09-13'"
    )
    start: date
    end: date
    days: int
    timezone: str
    basis: str = Field(description="Why these dates — shown to the user for explainability")

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class FactoryClock:
    """The factory's notion of 'now'. Injectable so tests need no real clock."""

    timezone: str = "Asia/Tokyo"
    _fixed_today: date | None = None

    def today(self) -> date:
        if self._fixed_today is not None:
            return self._fixed_today
        return datetime.now(ZoneInfo(self.timezone)).date()

    def now(self) -> datetime:
        current = datetime.now(ZoneInfo(self.timezone))
        if self._fixed_today is None:
            return current
        # A pinned day keeps the real time of day, so a rehearsal still shows a
        # clock that moves — only the calendar is fixed.
        return datetime.combine(self._fixed_today, current.timetz())

    def at(self, day: date) -> FactoryClock:
        """A clock pinned to a specific day — used by tests and demo rehearsals."""
        return FactoryClock(timezone=self.timezone, _fixed_today=day)


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.isoweekday() - 1)


def week_end(day: date) -> date:
    """Sunday of the ISO week containing `day`."""
    return week_start(day) + timedelta(days=6)


def _explicit(spec: str) -> tuple[date, date] | None:
    """Parse 'YYYY-MM-DD' or 'YYYY-MM-DD..YYYY-MM-DD'."""
    parts = spec.split("..")
    try:
        if len(parts) == 1:
            d = date.fromisoformat(parts[0].strip())
            return d, d
        if len(parts) == 2:
            return date.fromisoformat(parts[0].strip()), date.fromisoformat(parts[1].strip())
    except ValueError:
        return None
    return None


def resolve_window(
    spec: str | None, clock: FactoryClock, *, default: str = "this_week"
) -> ResolvedWindow:
    """Turn a window keyword or explicit range into concrete dates.

    Accepts any label in WINDOW_LABELS, an ISO date, or an ISO range 'a..b'.
    """
    label = (spec or default).strip()
    today = clock.today()
    tz = clock.timezone

    def out(start: date, end: date, basis: str) -> ResolvedWindow:
        if end < start:
            raise WindowError(f"Window '{label}' ends ({end}) before it starts ({start}).")
        return ResolvedWindow(
            label=label,
            start=start,
            end=end,
            days=(end - start).days + 1,
            timezone=tz,
            basis=basis,
        )

    match label:
        case "today" | "now":
            return out(today, today, f"Today is {today} in {tz}.")
        case "tomorrow":
            d = today + timedelta(days=1)
            return out(d, d, f"The day after {today} in {tz}.")
        case "yesterday":
            d = today - timedelta(days=1)
            return out(d, d, f"The day before {today} in {tz}.")
        case "this_week":
            end = week_end(today)
            return out(
                today,
                end,
                f"The current ISO week runs {week_start(today)} to {end}; elapsed days are "
                f"excluded, so capacity is counted from today ({today}).",
            )
        case "full_week":
            return out(
                week_start(today),
                week_end(today),
                f"The whole current ISO week, {week_start(today)} to {week_end(today)}, "
                "including days already elapsed.",
            )
        case "next_week":
            s = week_start(today) + timedelta(days=7)
            return out(s, s + timedelta(days=6), f"The ISO week after the one containing {today}.")
        case "last_week":
            s = week_start(today) - timedelta(days=7)
            return out(s, s + timedelta(days=6), f"The ISO week before the one containing {today}.")
        case "last_7_days":
            return out(
                today - timedelta(days=7),
                today - timedelta(days=1),
                f"The 7 days ending {today - timedelta(days=1)}.",
            )
        case "last_30_days":
            return out(
                today - timedelta(days=30),
                today - timedelta(days=1),
                f"The 30 days ending {today - timedelta(days=1)}.",
            )

    explicit = _explicit(label)
    if explicit:
        return out(explicit[0], explicit[1], f"Explicit date range supplied by the caller ({tz}).")

    raise WindowError(
        f"Unknown time window '{label}'. Supported: {', '.join(WINDOW_LABELS)}, "
        "an ISO date, or an ISO range 'YYYY-MM-DD..YYYY-MM-DD'."
    )
