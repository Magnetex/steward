"""Timezone-aware date helpers. Everything in the app runs on IST."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current timezone-aware datetime in IST."""
    return datetime.now(IST)


def today_ist() -> date:
    """Today's calendar date in IST."""
    return now_ist().date()


def month_start(d: date) -> date:
    """First day of the month containing ``d``."""
    return d.replace(day=1)


def next_month_start(d: date) -> date:
    """First day of the month after the one containing ``d``."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def prev_month_start(d: date) -> date:
    """First day of the month before the one containing ``d``."""
    first = month_start(d)
    return month_start(first - timedelta(days=1))


def month_end(d: date) -> date:
    """Last day of the month containing ``d``."""
    return next_month_start(d) - timedelta(days=1)


def days_in_month(d: date) -> int:
    return (next_month_start(d) - month_start(d)).days


def month_label(d: date) -> str:
    """'August 2026' for a date in that month."""
    return d.strftime("%B %Y")


def add_months(d: date, n: int) -> date:
    """Add ``n`` months to ``d`` (clamping day to the target month length)."""
    total = (d.year * 12 + (d.month - 1)) + n
    year, month = divmod(total, 12)
    month += 1
    from calendar import monthrange
    last = monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def months_between(a: date, b: date) -> int:
    """Whole months from ``a`` to ``b`` (b - a), floor to 0 if negative."""
    diff = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        diff -= 1
    return max(diff, 0)


def parse_date(value, default: date | None = None) -> date | None:
    """Parse an ISO 'YYYY-MM-DD' string into a date."""
    if not value:
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return default


def financial_year_bounds(d: date) -> tuple[date, date]:
    """Indian FY (Apr 1 - Mar 31) containing ``d``. Returns (start, end)."""
    if d.month >= 4:
        return date(d.year, 4, 1), date(d.year + 1, 3, 31)
    return date(d.year - 1, 4, 1), date(d.year, 3, 31)
