"""Settings are validated when the application starts."""

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


def test_a_blank_rehearsal_date_means_the_real_date():
    """docker-compose passes FACTORY_TODAY through as an empty string when unset."""
    settings = Settings(factory_today="")
    assert settings.factory_today is None
    assert settings.factory_clock()._fixed_today is None


def test_a_rehearsal_date_pins_the_calendar_but_not_the_time_of_day():
    from datetime import date

    clock = Settings(factory_timezone="Asia/Tokyo", factory_today="2026-09-18").factory_clock()
    assert clock.today() == date(2026, 9, 18)
    assert clock.now().date() == date(2026, 9, 18)
    assert clock.now().tzinfo is not None
    assert resolve_window("this_week", clock).end == date(2026, 9, 20)


def test_a_rehearsal_date_that_is_not_a_date_stops_the_application():
    with pytest.raises(ValidationError):
        Settings(factory_today="next friday")


@pytest.mark.parametrize("field", ["DATABASE_URL", "DATABASE_URL_RO"])
def test_database_credentials_have_no_default_in_code(field, monkeypatch):
    """Credentials come from .env or the environment only.

    With no .env and no variable, startup must stop and name the field rather
    than connect with a password written into the source.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("DATABASE_URL_RO", "postgresql://u:p@h/db")
    monkeypatch.delenv(field)
    with pytest.raises(ValidationError, match=field.lower()):
        Settings(_env_file=None)


def test_a_blank_database_url_is_refused(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("DATABASE_URL_RO", " ")
    with pytest.raises(ValidationError, match="DATABASE_URL_RO is empty"):
        Settings(_env_file=None)
