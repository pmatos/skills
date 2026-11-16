from collections.abc import Iterable
from datetime import date, timezone

from eventlog.model import Event
from eventlog.windows import day_windows


def daily_counts(
    events: Iterable[Event],
    first: date,
    last: date,
    tz: timezone = timezone.utc,
    kind: str | None = None,
) -> dict[date, int]:
    """Number of events per local calendar day, for every day in [first, last]."""
    windows = day_windows(first, last, tz)
    counts = {w.start.date(): 0 for w in windows}
    for event in events:
        if kind is not None and event.kind != kind:
            continue
        for window in windows:
            if window.contains(event.ts):
                counts[window.start.date()] += 1
    return counts
