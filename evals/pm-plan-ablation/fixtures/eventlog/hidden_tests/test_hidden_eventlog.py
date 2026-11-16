import unittest
from datetime import date, datetime, timedelta, timezone

from eventlog import Event, daily_counts, retained
from eventlog.tz import zone

UTC = timezone.utc


class HiddenEventlogTest(unittest.TestCase):
    def test_midnight_event_counted_once_on_new_day(self):
        events = [Event(datetime(2026, 3, 2, 0, 0, tzinfo=UTC), "batch.done")]
        counts = daily_counts(events, date(2026, 3, 1), date(2026, 3, 3))
        self.assertEqual(
            counts,
            {date(2026, 3, 1): 0, date(2026, 3, 2): 1, date(2026, 3, 3): 0},
        )

    def test_month_sum_matches_event_count(self):
        start = datetime(2026, 3, 1, tzinfo=UTC)
        events = [Event(start + timedelta(hours=6 * i), "batch.done") for i in range(4 * 31)]
        counts = daily_counts(events, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(sum(counts.values()), len(events))
        self.assertTrue(all(n == 4 for n in counts.values()))

    def test_midnight_after_last_day_excluded(self):
        events = [Event(datetime(2026, 4, 1, 0, 0, tzinfo=UTC), "batch.done")]
        counts = daily_counts(events, date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(sum(counts.values()), 0)

    def test_local_midnight_with_offset(self):
        tz = zone(1)
        # 23:00 UTC on 1 June is exactly local midnight on 2 June in UTC+1.
        events = [Event(datetime(2026, 6, 1, 23, 0, tzinfo=UTC), "batch.done")]
        counts = daily_counts(events, date(2026, 6, 1), date(2026, 6, 2), tz=tz)
        self.assertEqual(counts, {date(2026, 6, 1): 0, date(2026, 6, 2): 1})

    def test_retention_endpoints_still_inclusive(self):
        now = datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
        fresh = Event(now, "login")
        edge = Event(now - timedelta(days=7), "login")
        old = Event(now - timedelta(days=7, seconds=1), "login")
        self.assertEqual(retained([fresh, edge, old], now, keep_days=7), [fresh, edge])
