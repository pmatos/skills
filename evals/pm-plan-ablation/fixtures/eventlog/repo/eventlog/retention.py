from collections.abc import Iterable
from datetime import datetime, timedelta

from eventlog.model import Event
from eventlog.windows import trailing_window


def retained(events: Iterable[Event], now: datetime, keep_days: int) -> list[Event]:
    """Events to keep: anything from the last keep_days, both ends inclusive.

    An event stamped exactly `now` is kept (it was just written), and so is one
    stamped exactly at the cutoff, so a sweep never races the writer.
    """
    window = trailing_window(now, timedelta(days=keep_days))
    return [e for e in events if window.contains(e.ts)]
