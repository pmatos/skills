from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from eventlog.tz import local_midnight


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def contains(self, ts: datetime) -> bool:
        return self.start <= ts <= self.end

    def duration(self) -> timedelta:
        return self.end - self.start


def day_window(day: date, tz: timezone) -> Window:
    start = local_midnight(day, tz)
    return Window(start, start + timedelta(days=1))


def day_windows(first: date, last: date, tz: timezone) -> list[Window]:
    days = (last - first).days + 1
    return [day_window(first + timedelta(days=i), tz) for i in range(days)]


def trailing_window(now: datetime, keep: timedelta) -> Window:
    return Window(now - keep, now)
