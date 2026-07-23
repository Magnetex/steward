"""Recurring-deposit auto-contributions — same shape as SIP, minus step-up.

An RD contributes a fixed installment every month from ``start_date`` for
``tenure_months`` months. Its accrued value is computed from the schedule
(`calculators.rd_accrued`), so past months are already reflected in net worth
regardless of any transactions. Therefore, like a SIP:

  * **backfill** (installments dated on/before today) is asset-only — no cash is
    debited (that money left before you started tracking);
  * **future** installments each create a ``savings`` cash-out from the "paid
    from" account, net-worth-neutral (cash −X, RD bucket +X as time passes).

RDs are NOT recurring rules, so they never appear on the Recurring page. This
engine (run by the scheduler / "Run due now") advances each RD's
``next_run_date`` and stops at maturity.
"""
from __future__ import annotations

from datetime import date

from ..extensions import db
from ..money import money, ZERO
from ..timeutil import today_ist, add_months
from .budget import default_budget_month
from .invest_link import savings_category_id


def _last_installment(deposit) -> date:
    """Date of the final (tenure-th) installment."""
    return add_months(deposit.start_date, deposit.tenure_months - 1)


def first_future_run(deposit, as_of: date) -> date | None:
    """First installment strictly after ``as_of`` that's still within tenure."""
    last = _last_installment(deposit)
    d = deposit.start_date
    guard = 0
    while d <= as_of and guard <= deposit.tenure_months:
        d = add_months(d, 1)
        guard += 1
    return d if d <= last else None


def sync_rd_plan(deposit, account_id) -> None:
    """Set up / update the RD's auto-contribution. Does not commit.

    Called only on create, or on edit when an account is chosen (a blank account
    on edit is left alone upstream, so we never silently stop a running RD).
    Past installments stay asset-only; future ones debit ``account_id``.
    """
    if account_id:
        deposit.account_id = int(account_id)
        if deposit.next_run_date is None:      # not already running -> start ahead
            deposit.next_run_date = first_future_run(deposit, today_ist())
    else:
        deposit.account_id = None
        deposit.next_run_date = None


def _contribute(deposit, on: date):
    """Create one RD installment as a savings cash-out (idempotent per date)."""
    from ..models import Transaction
    if Transaction.query.filter_by(invest_kind="deposit", invest_ref_id=deposit.id,
                                   date=on).first():
        return None
    t = Transaction(
        date=on, amount=money(deposit.installment), type="savings", flow="out",
        account_id=deposit.account_id, category_id=savings_category_id("deposit"),
        payee=f"RD · {deposit.bank}".strip(" ·"),
        note=f"RD installment · {deposit.bank}".strip(" ·"),
        invest_kind="deposit", invest_ref_id=deposit.id,
        budget_month=default_budget_month(on, "savings"),
    )
    db.session.add(t)
    return t


def run_due(as_of: date | None = None, max_catchup: int = 36) -> int:
    """Create every due future installment for all funded RDs. Commits.

    Returns the number of installment transactions created."""
    from ..models import Deposit
    today = as_of or today_ist()
    made = 0
    for dep in Deposit.query.filter_by(kind="RD").all():
        if not dep.account_id or dep.closed_on:
            continue
        last = _last_installment(dep)
        d = dep.next_run_date or first_future_run(dep, today)
        guard = 0
        while d and d <= today and d <= last and guard < max_catchup:
            guard += 1
            if _contribute(dep, d) is not None:
                made += 1
            nxt = add_months(d, 1)
            d = nxt if nxt <= last else None
        dep.next_run_date = d
    db.session.commit()
    return made
