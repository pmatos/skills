import unittest
from datetime import date, datetime, timezone

from eventlog import Event, daily_counts
from eventlog.tz import zone

UTC = timezone.utc


def at(y, mo, d, h=12, mi=0, tz=UTC):
    return datetime(y, mo, d, h, mi, tzinfo=tz)


class DailyCountsTest(unittest.TestCase):
    def test_counts_per_day(self):
        events = [
            Event(at(2026, 3, 1, 9), "login"),
            Event(at(2026, 3, 1, 17), "login"),
            Event(at(2026, 3, 2, 8), "login"),
        ]
        self.assertEqual(
            daily_counts(events, date(2026, 3, 1), date(2026, 3, 3)),
            {date(2026, 3, 1): 2, date(2026, 3, 2): 1, date(2026, 3, 3): 0},
        )

    def test_kind_filter(self):
        events = [Event(at(2026, 3, 1), "login"), Event(at(2026, 3, 1), "error")]
        self.assertEqual(
            daily_counts(events, date(2026, 3, 1), date(2026, 3, 1), kind="error"),
            {date(2026, 3, 1): 1},
        )

    def test_local_timezone(self):
        lisbon_summer = zone(1)
        # 23:30 UTC on the 1st is 00:30 on the 2nd in UTC+1.
        events = [Event(at(2026, 6, 1, 23, 30), "login")]
        self.assertEqual(
            daily_counts(events, date(2026, 6, 1), date(2026, 6, 2), tz=lisbon_summer),
            {date(2026, 6, 1): 0, date(2026, 6, 2): 1},
        )

    def test_out_of_range_ignored(self):
        events = [Event(at(2026, 2, 27), "login")]
        self.assertEqual(
            daily_counts(events, date(2026, 3, 1), date(2026, 3, 1)),
            {date(2026, 3, 1): 0},
        )
