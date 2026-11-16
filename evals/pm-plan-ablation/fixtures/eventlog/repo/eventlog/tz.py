from datetime import date, datetime, time, timedelta, timezone


def zone(offset_hours: float) -> timezone:
    return timezone(timedelta(hours=offset_hours))


def local_midnight(day: date, tz: timezone) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)
