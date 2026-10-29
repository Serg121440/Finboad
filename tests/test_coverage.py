"""Which days of a report period are loaded."""

from datetime import date

from dashboard.common import merge_intervals, missing_days


def test_gap_between_loads_is_reported():
    loads = [(date(2026, 9, 1), date(2026, 9, 5)), (date(2026, 9, 25), date(2026, 9, 30))]
    assert missing_days(loads, date(2026, 9, 1), date(2026, 9, 30)) == 19


def test_overlapping_and_adjacent_loads_join():
    loads = [(date(2026, 9, 10), date(2026, 9, 20)), (date(2026, 9, 1), date(2026, 9, 12)),
             (date(2026, 9, 21), date(2026, 9, 30))]
    assert merge_intervals(loads) == [(date(2026, 9, 1), date(2026, 9, 30))]
    assert missing_days(loads, date(2026, 9, 1), date(2026, 9, 30)) == 0
    assert missing_days(loads, date(2026, 8, 30), date(2026, 9, 2)) == 2
