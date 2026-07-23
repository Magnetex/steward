"""Closing a deposit — early (manual) or automatically at maturity.

When an FD/RD is closed, its current value is **deposited back into a cash
account** (a ``savings`` "in" transaction) and the deposit leaves the net-worth
"deposits" bucket (closed deposits are excluded from valuation). Because cash
gains exactly what the bucket loses, **net worth is unchanged** by a close.

  * **Early manual close**  → proceeds = accrued value *today*.
  * **Automatic at maturity** → proceeds = full maturity value, dated on the
    maturity date (run by the scheduler).

Any sinking-fund earmarks that pointed at the deposit are **re-pointed to the
cash account** the proceeds landed in, so goals keep their progress instead of
silently dropping when a backing deposit is closed.
"""
from __future__ import annotations

from datetime import date

from ..extensions import db
from ..money import money
from ..timeutil import today_ist
from .calculators import deposit_summary
from . import invest_link


def bank_account_for(deposit) -> int | None:
    """The cash account a deposit's proceeds should return to: its own "Paid
    from"/bank account, else the app's default cash account."""
    if deposit.account_id:
        return deposit.account_id
    from .accounts import default_account_id
    return default_account_id()


def _reassign_earmarks(deposit, account_id) -> None:
    """Re-point every earmark on this deposit to ``account_id`` (now cash)."""
    if not account_id:
        return
    from ..models import FundAllocation
    for a in FundAllocation.query.filter_by(source_kind="deposit",
                                             source_ref_id=deposit.id).all():
        a.source_kind = "cash"
        a.source_ref_id = int(account_id)


def close_deposit(deposit, *, on: date, proceeds, account_id):
    """Close a deposit: record its proceeds back to a cash account. No commit.

    Returns the credit :class:`Transaction` (or None if nothing was credited).
    Idempotent-ish: a deposit that is already closed is left untouched.
    """
    if deposit.is_closed:
        return None
    account_id = int(account_id) if account_id else None
    deposit.closed_on = on
    deposit.closed_value = money(proceeds)
    deposit.close_account_id = account_id
    txn = invest_link.credit_cash(
        "deposit", deposit.id, account_id=account_id, amount=proceeds, on=on,
        payee=f"{deposit.kind} · {deposit.bank}".strip(" ·"),
        note=f"{deposit.kind} closed · {deposit.bank}".strip(" ·"))
    _reassign_earmarks(deposit, account_id)
    return txn


def close_matured(as_of: date | None = None) -> int:
    """Auto-close every active deposit that has reached maturity. Commits.

    Deposits the full maturity value into the bank account (dated the maturity
    date) and records a transaction. Returns the number closed."""
    from ..models import Deposit
    today = as_of or today_ist()
    closed = 0
    for dep in Deposit.query.filter(Deposit.closed_on.is_(None)).all():
        s = deposit_summary(dep, today)
        if s["days_left"] > 0:
            continue
        close_deposit(dep, on=s["maturity_date"], proceeds=s["maturity_value"],
                      account_id=bank_account_for(dep))
        closed += 1
    db.session.commit()
    return closed
