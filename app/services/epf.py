"""EPF: running balance from entries, and a yearly interest-crediting helper."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import EPFAccount, EPFEntry
from ..money import ZERO, money, to_decimal
from ..timeutil import financial_year_bounds, today_ist
from .settings import get_decimal


def entry_amount(e: EPFEntry) -> Decimal:
    if e.entry_type == "interest":
        return money(e.interest_amount)
    return money(to_decimal(e.employee_share, ZERO) + to_decimal(e.employer_share, ZERO))


def running_series(account: EPFAccount):
    """Entries in month order, each with a running balance."""
    rows = []
    bal = ZERO
    for e in sorted(account.entries, key=lambda x: (x.month, x.id)):
        bal += entry_amount(e)
        rows.append({"entry": e, "amount": entry_amount(e), "balance": money(bal)})
    return rows


def account_balance(account: EPFAccount) -> Decimal:
    return money(sum((entry_amount(e) for e in account.entries), ZERO))


def total_balance() -> Decimal:
    return money(sum((account_balance(a) for a in EPFAccount.query.all()), ZERO))


def employee_contrib_for_fy(as_of: date | None = None) -> Decimal:
    """Total employee EPF contribution in the financial year (for 80C)."""
    as_of = as_of or today_ist()
    start, end = financial_year_bounds(as_of)
    total = ZERO
    for a in EPFAccount.query.all():
        for e in a.entries:
            if e.entry_type == "contribution" and start <= e.month <= end:
                total += to_decimal(e.employee_share, ZERO)
    return money(total)


def add_interest_entry(account: EPFAccount, on: date | None = None,
                       rate_pct: Decimal | None = None) -> EPFEntry:
    """Credit one year's interest at the configured rate on the running balance."""
    on = on or today_ist()
    rate = rate_pct if rate_pct is not None else get_decimal("epf_interest_rate", Decimal("8.25"))
    balance = account_balance(account)
    interest = money(balance * (rate or ZERO) / Decimal(100))
    e = EPFEntry(account_id=account.id, month=on.replace(day=1), entry_type="interest",
                 interest_amount=interest, note=f"Interest @ {rate}%")
    db.session.add(e)
    db.session.commit()
    return e
