"""Is the factory's data still about today?

The seeded factory is deliberately relative: `db/seed.sql` lays the week out
around whatever "today" is when it runs, which is what lets the demo work on any
day of the week. The cost is that a database seeded yesterday is a database
about yesterday, and nothing in the system noticed.

It went unnoticed for a good reason: every figure stays internally consistent.
Asked which machine limited A12 the morning after a seed, the agent answered
"CNC-03, 20 effective hours of 40 planned" — correct against the rows, correct
against the SQL oracle, and a day out of date. What breaks is the *story*: the
overhaul that should start tomorrow is active today, so CNC-03 is refused rather
than cleared (S2), and "yesterday" holds no production at all, so the shortfall
has nothing to explain (S4).

The check keys on one invariant: **the seed always writes production history up
to and including yesterday.** If the newest record is older than yesterday, the
dataset was laid out for an earlier day, and by exactly that many days.

Nothing here reseeds. The backend reads the factory; rewriting it on a hunch
would be the one thing a read-only tool layer exists to prevent, and an
automatic reseed during a demo would change the numbers under the presenter.
It reports, the interface says so, and `make db-seed` is one command.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DatasetFreshness:
    """How the seeded week sits against the factory's today."""

    last_production_day: date | None
    expected_last_day: date
    stale_days: int

    @property
    def fresh(self) -> bool:
        return self.stale_days == 0 and self.last_production_day is not None

    @property
    def note(self) -> str | None:
        """What to tell a human, or None when there is nothing to say."""
        if self.last_production_day is None:
            return (
                "No production history is recorded. Run `make db-seed` to build the factory's week."
            )
        if self.stale_days > 0:
            day = "day" if self.stale_days == 1 else "days"
            return (
                f"The factory data is {self.stale_days} {day} out of date: the newest "
                f"production record is {self.last_production_day}, and 'yesterday' is "
                f"{self.expected_last_day}. Scenario 2 (CNC-03 cleared to run today) and "
                f"scenario 4 (yesterday's shortfall) will not hold. Run `make db-seed`."
            )
        if self.stale_days < 0:
            return (
                f"The factory data runs to {self.last_production_day}, which is later than "
                f"yesterday ({self.expected_last_day}). Either FACTORY_TODAY is pinned to "
                f"an earlier day than the data, or the data was seeded for a future date."
            )
        return None

    def as_json(self) -> dict:
        return {
            "last_production_day": (
                self.last_production_day.isoformat() if self.last_production_day else None
            ),
            "expected_last_day": self.expected_last_day.isoformat(),
            "stale_days": self.stale_days,
            "fresh": self.fresh,
            "note": self.note,
        }


def assess(last_production_day: date | None, today: date) -> DatasetFreshness:
    """Compare the newest production record with the factory's yesterday."""
    expected = today - timedelta(days=1)
    if last_production_day is None:
        # Distinct from "stale": an empty factory is not a factory laid out for
        # the wrong day, and the fix is the same command for a different reason.
        return DatasetFreshness(None, expected, stale_days=0)
    return DatasetFreshness(last_production_day, expected, (expected - last_production_day).days)
