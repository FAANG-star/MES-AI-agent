"""The factory time zone is validated when the application starts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.timewindow import FactoryClock, resolve_window


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "Asia/Shanghai", "Europe/Berlin", "UTC"])
def test_an_iana_zone_is_accepted(zone):
    assert Settings(factory_timezone=zone).factory_timezone == zone


@pytest.mark.parametrize("zone", ["China", "Beijing", "GMT+8", "Asia/Nowhere", ""])
def test_a_name_that_is_not_a_zone_stops_the_application(zone):
    """A typo must fail at startup, not on the first question of the demo."""
    with pytest.raises(ValidationError, match="IANA time zone"):
        Settings(factory_timezone=zone)


def test_the_same_instant_is_a_different_factory_day_in_another_zone():
    """Why the factory's zone — not the viewer's — decides what "today" means.

    At 00:30 in Tokyo it is still 23:30 the previous day in Shanghai. A factory
    in Tokyo is already running Monday's shifts; one in Shanghai is finishing
    Sunday's. The same question, "today", is two different sets of rows.
    """
    from datetime import date

    tokyo = FactoryClock("Asia/Tokyo").at(date(2026, 9, 14))
    shanghai = FactoryClock("Asia/Shanghai").at(date(2026, 9, 13))

    assert resolve_window("today", tokyo).start == date(2026, 9, 14)
    assert resolve_window("today", shanghai).start == date(2026, 9, 13)
    assert resolve_window("today", shanghai).timezone == "Asia/Shanghai"
