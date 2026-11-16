import unittest
from datetime import datetime, timedelta, timezone

from eventlog import Event, retained

NOW = datetime(2026, 3, 10, 6, 0, tzinfo=timezone.utc)


class RetentionTest(unittest.TestCase):
    def test_keeps_recent_drops_old(self):
        recent = Event(NOW - timedelta(days=1), "login")
        old = Event(NOW - timedelta(days=8), "login")
        self.assertEqual(retained([recent, old], NOW, keep_days=7), [recent])

    def test_event_at_now_is_kept(self):
        fresh = Event(NOW, "login")
        self.assertEqual(retained([fresh], NOW, keep_days=7), [fresh])

    def test_event_at_cutoff_is_kept(self):
        edge = Event(NOW - timedelta(days=7), "login")
        self.assertEqual(retained([edge], NOW, keep_days=7), [edge])
