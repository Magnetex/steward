"""SIP plans: recurring monthly mutual-fund investments with annual step-up.

A plan buys units in one MF holding every month from ``start_date``:

  * **backfill** (installments dated on/before today, at creation) records units
    only, priced at that month's historical NAV — asset-only, so past cash
    balances are never rewritten (matches the "backfill" convention elsewhere);
  * **future** installments (run by the scheduler) buy units at the day's NAV
    *and* debit the plan's "paid from" account via a net-worth-neutral savings
    transaction, so cash-out + units-up nets to zero.

``step_up_pct`` raises the monthly amount by that percent every 12 months from
``start_date`` (annual step-up SIP). Installment dates advance one month at a
time from ``start_date`` (day clamped to the month length).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import SIPPlan, MFTransaction, MutualFundHolding
from ..money import money, ZERO, quantize4, to_decimal
from ..timeutil import today_ist, add_months, months_between
from . import mf as mf_svc
from . import invest_link

_MAX_INSTALLMENTS = 600   # safety guard (50 years)


# ---------------------------------------------------------------------------
# Amount / pricing helpers
# ---------------------------------------------------------------------------
def stepped_amount(plan: SIPPlan, on: date) -> Decimal:
    """The monthly amount for an installment dated ``on`` after step-up.

    Rises by ``step_up_pct`` every completed 12 months since ``start_date``.
    """
    base = money(plan.amount)
    pct = to_decimal(plan.step_up_pct, ZERO)
    if pct <= 0:
        return base
    years = months_between(plan.start_date, on) // 12
    factor = (Decimal(1) + pct / Decimal(100)) ** years
    return money(base * factor)


def _price_on(history, scheme_code: str, on: date) -> Decimal | None:
    """NAV for an installment dated ``on`` — historical if available, else the
    latest cached NAV (keeps dev/offline usable)."""
    nav = mf_svc.nav_on(history, on)
    if nav is None:
        nav = mf_svc.current_nav(scheme_code)
    return nav if nav and nav > 0 else None


def _buy(plan: SIPPlan, on: date, amount: Decimal, history, *, with_cash: bool):
    """Create one SIP installment (an MF ``sip`` txn), optionally debiting cash.

    Returns the MFTransaction, or None if the installment couldn't be priced.
    """
    holding = plan.holding
    nav = _price_on(history, holding.scheme_code, on)
    if nav is None:
        return None
    amount = money(amount)
    units = quantize4(amount / nav)
    t = MFTransaction(holding_id=holding.id, date=on, type="sip",
                      amount=amount, units=units, nav=money(nav),
                      sip_plan_id=plan.id, tags="sip")
    db.session.add(t)
    db.session.flush()
    if with_cash and plan.account_id:
        invest_link.sync_cash("mf", t.id, account_id=plan.account_id,
                              amount=amount, on=on, flow="out",
                              note=f"SIP · {holding.scheme_name}")
    return t


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def create_plan(*, holding_id: int, amount, start_date: date, step_up_pct=ZERO,
                account_id=None, note: str = "") -> tuple[SIPPlan, dict]:
    """Create a SIP plan and backfill every installment already due.

    Returns (plan, summary) where summary has ``count`` and ``invested`` for the
    backfilled installments. Does not commit — the caller commits.
    """
    plan = SIPPlan(
        holding_id=holding_id, amount=money(amount),
        day_of_month=start_date.day, start_date=start_date,
        step_up_pct=to_decimal(step_up_pct, ZERO),
        account_id=int(account_id) if account_id else None,
        note=note, active=True, next_run_date=start_date,
    )
    db.session.add(plan)
    db.session.flush()
    summary = backfill(plan)
    return plan, summary


def backfill(plan: SIPPlan, as_of: date | None = None) -> dict:
    """Record every installment dated on/before ``as_of`` (asset-only), then set
    ``next_run_date`` to the first future installment. Returns a summary."""
    today = as_of or today_ist()
    history = mf_svc.nav_history(plan.holding.scheme_code)
    d = plan.start_date
    count = 0
    invested = ZERO
    priced = 0
    guard = 0
    while d <= today and guard < _MAX_INSTALLMENTS:
        guard += 1
        amt = stepped_amount(plan, d)
        t = _buy(plan, d, amt, history, with_cash=False)
        count += 1
        if t is not None:
            invested += money(t.amount)
            priced += 1
        d = add_months(d, 1)
    plan.next_run_date = d
    return {"count": count, "priced": priced, "invested": money(invested)}


def run_due(as_of: date | None = None, max_catchup: int = 36) -> int:
    """Process every active plan whose next_run_date has arrived (units + cash).

    Advances each plan's next_run_date past today. Commits. Returns the number of
    plans touched."""
    today = as_of or today_ist()
    touched = 0
    for plan in SIPPlan.query.filter_by(active=True).all():
        d = plan.next_run_date
        if not d or d > today:
            continue
        history = mf_svc.nav_history(plan.holding.scheme_code)
        guard = 0
        while d and d <= today and guard < max_catchup:
            guard += 1
            amt = stepped_amount(plan, d)
            _buy(plan, d, amt, history, with_cash=True)
            d = add_months(d, 1)
        plan.next_run_date = d
        touched += 1
    db.session.commit()
    return touched


def stop_plan(plan: SIPPlan) -> None:
    """Stop future installments; keep all past history. Does not commit."""
    plan.active = False


def delete_plan(plan: SIPPlan) -> None:
    """Delete the plan but keep the installments it already made (they are real
    invested money). Detaches them from the plan. Does not commit."""
    MFTransaction.query.filter_by(sip_plan_id=plan.id).update(
        {MFTransaction.sip_plan_id: None})
    db.session.delete(plan)


# ---------------------------------------------------------------------------
# Read model (for the UI)
# ---------------------------------------------------------------------------
def plan_summary(plan: SIPPlan) -> dict:
    """Display metrics for one plan."""
    txns = MFTransaction.query.filter_by(sip_plan_id=plan.id).all()
    invested = sum((money(t.amount) for t in txns), ZERO)
    return {
        "plan": plan,
        "holding": plan.holding,
        "installments": len(txns),
        "invested": money(invested),
        "current_amount": stepped_amount(plan, today_ist()),
        "base_amount": money(plan.amount),
        "step_up_pct": to_decimal(plan.step_up_pct, ZERO),
        "next_run_date": plan.next_run_date,
        "account": plan.account,
    }


def all_summaries(active_only: bool = False) -> list[dict]:
    q = SIPPlan.query
    if active_only:
        q = q.filter_by(active=True)
    plans = q.order_by(SIPPlan.active.desc(), SIPPlan.created_at.desc()).all()
    return [plan_summary(p) for p in plans]
