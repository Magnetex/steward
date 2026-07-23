"""FD/RD summaries, total accrued value, and maturity reminders (30 & 7 days)."""
from __future__ import annotations

from decimal import Decimal

from ..extensions import db
from ..models import Deposit
from ..money import ZERO, money
from ..timeutil import today_ist
from .calculators import deposit_summary
from .alerts import add_alert


def all_summaries(as_of=None, include_closed=False):
    """Deposit summaries, ordered by start date.

    Closed deposits are excluded by default (their value has moved to cash and is
    no longer part of the "deposits" net-worth bucket). Pass ``include_closed`` to
    get every deposit, e.g. for a closed/matured history section.
    """
    as_of = as_of or today_ist()
    q = Deposit.query
    if not include_closed:
        q = q.filter(Deposit.closed_on.is_(None))
    return [deposit_summary(d, as_of) for d in q.order_by(Deposit.start_date).all()]


def total_accrued(as_of=None) -> Decimal:
    total = ZERO
    for s in all_summaries(as_of):
        total += s["accrued_value"]
    return money(total)


def total_maturity() -> Decimal:
    total = ZERO
    for s in all_summaries():
        total += s["maturity_value"]
    return money(total)


def sweep_maturity_alerts(as_of=None) -> int:
    """Create maturity reminders at 30 and 7 days before maturity."""
    as_of = as_of or today_ist()
    n = 0
    for s in all_summaries(as_of):
        d = s["deposit"]
        days = s["days_left"]
        for threshold in (30, 7):
            if 0 < days <= threshold:
                add_alert(
                    "maturity",
                    f"{d.kind} at {d.bank} matures in {days} day(s) "
                    f"— {s['maturity_value']} on {s['maturity_date'].strftime('%d %b %Y')}.",
                    due_date=s["maturity_date"],
                    dedupe_key=f"maturity:{d.id}:{threshold}",
                )
                n += 1
                break
    db.session.commit()
    return n
