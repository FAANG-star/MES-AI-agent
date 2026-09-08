"""Window resolution — pure logic, no database.

The rule under test is the one most likely to be got wrong quietly: "this week"
means the hours still ahead, so a question asked on Thursday must not count
Monday's shifts as available capacity.
"""

from datetime import date

import pytest

from app.timewindow import FactoryClock, WindowError, resolve_window, week_end, week_start

TUESDAY = date(2026, 9, 8)  # ISO week 2026-09-07 (Mon) .. 2026-09-13 (Sun)
clock = FactoryClock("Asia/Tokyo").at(TUESDAY)


def test_week_boundaries_are_iso_monday_to_sunday():
    assert week_start(TUESDAY) == date(2026, 9, 7)
    assert week_end(TUESDAY) == date(2026, 9, 13)


def test_this_week_excludes_elapsed_days():
    w = resolve_window("this_week", clock)
    assert (w.start, w.end) == (TUESDAY, date(2026, 9, 13))
    assert w.days == 6
    assert "elapsed days are excluded" in w.basis


def test_full_week_keeps_elapsed_days():
    w = resolve_window("full_week", clock)
    assert (w.start, w.end) == (date(2026, 9, 7), date(2026, 9, 13))
    assert w.days == 7


def test_this_week_on_monday_covers_the_whole_week():
    w = resolve_window("this_week", clock.at(date(2026, 9, 7)))
    assert (w.start, w.end) == (date(2026, 9, 7), date(2026, 9, 13))


def test_this_week_on_sunday_is_a_single_day():
    w = resolve_window("this_week", clock.at(date(2026, 9, 13)))
    assert (w.start, w.end) == (date(2026, 9, 13), date(2026, 9, 13))
    assert w.days == 1


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("today", (TUESDAY, TUESDAY)),
        ("tomorrow", (date(2026, 9, 9), date(2026, 9, 9))),
        ("yesterday", (date(2026, 9, 7), date(2026, 9, 7))),
        ("next_week", (date(2026, 9, 14), date(2026, 9, 20))),
        ("last_week", (date(2026, 8, 31), date(2026, 9, 6))),
        ("last_7_days", (date(2026, 9, 1), date(2026, 9, 7))),
        ("last_30_days", (date(2026, 8, 9), date(2026, 9, 7))),
    ],
)
def test_keyword_windows(label, expected):
    w = resolve_window(label, clock)
    assert (w.start, w.end) == expected


def test_explicit_single_date_and_range():
    single = resolve_window("2026-09-01", clock)
    assert (single.start, single.end, single.days) == (date(2026, 9, 1), date(2026, 9, 1), 1)
    span = resolve_window("2026-09-01..2026-09-03", clock)
    assert (span.start, span.end, span.days) == (date(2026, 9, 1), date(2026, 9, 3), 3)


def test_default_is_used_when_no_window_given():
    assert resolve_window(None, clock, default="today").start == TUESDAY


def test_unknown_window_is_rejected_with_guidance():
    with pytest.raises(WindowError) as exc:
        resolve_window("next_quarter", clock)
    assert "this_week" in str(exc.value)


def test_backwards_range_is_rejected():
    with pytest.raises(WindowError):
        resolve_window("2026-09-10..2026-09-01", clock)


def test_window_reports_the_factory_timezone_not_the_server():
    assert resolve_window("today", clock).timezone == "Asia/Tokyo"
