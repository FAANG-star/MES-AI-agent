"""Is the factory's data still about today? (`app/dataset.py`)

The defect these cover reached a demo. The dataset is laid out around whatever
"today" was when `db/seed.sql` ran, so the morning after a seed every figure is
still internally consistent — the agent answered "CNC-03, 20 effective hours of
40 planned", and the SQL oracle agreed — while the *story* had broken: the
overhaul that should start tomorrow was active today, and "yesterday" held no
production at all.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import dataset
from app.config import Settings
from tests.conftest import requires_db

TODAY = date(2026, 9, 16)


def test_a_week_seeded_this_morning_is_fresh():
    """The seed always writes production history up to and including yesterday."""
    freshness = dataset.assess(TODAY - timedelta(days=1), TODAY)

    assert freshness.fresh
    assert freshness.stale_days == 0
    assert freshness.note is None


@pytest.mark.parametrize("days", [1, 2, 7])
def test_a_seed_left_behind_by_the_calendar_is_counted(days):
    freshness = dataset.assess(TODAY - timedelta(days=days + 1), TODAY)

    assert not freshness.fresh
    assert freshness.stale_days == days
    assert freshness.note is not None
    assert "make db-seed" in freshness.note
    # The note has to name what will actually go wrong, or nobody acts on it.
    assert "Scenario 2" in freshness.note and "scenario 4" in freshness.note


def test_one_day_is_said_in_the_singular():
    assert "1 day out of date" in dataset.assess(TODAY - timedelta(days=2), TODAY).note


def test_an_empty_factory_is_not_the_same_as_a_stale_one():
    """A different problem with the same fix, and it must not be miscounted."""
    freshness = dataset.assess(None, TODAY)

    assert not freshness.fresh
    assert freshness.stale_days == 0
    assert "No production history" in freshness.note


def test_data_later_than_yesterday_is_reported_too():
    """FACTORY_TODAY pinned behind the data, or a seed for a future date."""
    freshness = dataset.assess(TODAY + timedelta(days=3), TODAY)

    assert not freshness.fresh
    assert freshness.stale_days < 0
    assert "later than" in freshness.note


def test_the_json_shape_is_what_the_interface_reads():
    payload = dataset.assess(TODAY - timedelta(days=2), TODAY).as_json()

    assert payload == {
        "last_production_day": "2026-09-14",
        "expected_last_day": "2026-09-15",
        "stale_days": 1,
        "fresh": False,
        "note": payload["note"],
    }
    assert payload["note"]


# ------------------------------------------------------- against the factory


@requires_db
async def test_the_seeded_factory_reads_as_fresh(repo, ctx):
    """`make db-seed` and `make db-verify` were both run for the current day."""
    freshness = dataset.assess(await repo.last_production_day(), ctx.clock.today())

    assert freshness.fresh, freshness.note


@requires_db
async def test_a_calendar_that_has_moved_on_reads_as_stale(repo):
    """The real failure, reproduced with the rehearsal clock.

    Pinning the factory two days ahead of the seeded week is exactly what an
    unattended stack does overnight.
    """
    clock = Settings(
        factory_today=await repo.last_production_day() + timedelta(days=3)
    ).factory_clock()
    freshness = dataset.assess(await repo.last_production_day(), clock.today())

    assert not freshness.fresh
    assert freshness.stale_days == 2
