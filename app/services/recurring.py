"""Recurring-rule engine: materialize due transactions / reminders."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from ..extensions import db
from ..models import RecurringRule, Transaction, Account
from ..money import money
from ..timeutil import today_ist
from .budget import default_budget_month
from .alerts import add_alert


def _clamp_day(year: int, month: int, day: int) -> date:
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def next_after(rule: RecurringRule, current: date) -> date:
    """The due date strictly after ``current`` for this rule's schedule."""
    if rule.frequency == "weekly":
        return current + timedelta(days=7)
    if rule.frequency == "monthly":
        y, m = current.year, current.month
        m += 1
        if m > 12:
            m = 1; y += 1
        return _clamp_day(y, m, rule.day_of_month or current.day)
    if rule.frequency == "yearly":
        return _clamp_day(current.year + 1, rule.month_of_year or current.month,
                          rule.day_of_month or current.day)
    return current + timedelta(days=30)


def record_from_rule(rule: RecurringRule, on: date | None = None) -> Transaction:
    """Create a real transaction from a rule's template."""
    d = on or rule.next_due_date or today_ist()
    tags = ", ".join(t for t in ["recurring", *(rule.tags or "").split(",")] if t.strip())
    t = Transaction(
        date=d, amount=money(rule.amount), type=rule.type,
        account_id=rule.account_id,
        transfer_account_id=rule.transfer_account_id if rule.type == "transfer" else None,
        category_id=rule.category_id if rule.type != "transfer" else None,
        payee=rule.payee, note=rule.note or "",
        tags=tags, budget_month=default_budget_month(d, rule.type),
    )
    db.session.add(t)
    return t


def materialize_rule(rule: RecurringRule, as_of: date | None = None,
                     max_catchup: int = 24) -> int:
    """Generate every occurrence of one rule due on/before ``as_of``.

    auto_create -> creates the transaction(s); remind_only -> creates an alert.
    Advances the rule's next_due_date past today. Does NOT commit. Returns the
    number of occurrences produced.
    """
    today = as_of or today_ist()
    due = rule.next_due_date
    if not rule.active or not due or due > today:
        return 0
    made = 0
    guard = 0
    while due and due <= today and guard < max_catchup:
        guard += 1
        if rule.mode == "auto_create":
            record_from_rule(rule, on=due)
        else:  # remind_only
            add_alert(
                "recurring",
                f"{rule.payee or 'Recurring'} — {money(rule.amount)} is due.",
                due_date=due, action="record", ref_id=rule.id,
                dedupe_key=f"recur:{rule.id}:{due.isoformat()}",
            )
        due = next_after(rule, due)
        made += 1
    rule.next_due_date = due
    return made


def materialize_due(as_of: date | None = None, max_catchup: int = 24) -> int:
    """Process every active rule whose next_due_date has arrived. Returns the
    number of rules touched."""
    today = as_of or today_ist()
    touched = 0
    for rule in RecurringRule.query.filter_by(active=True).all():
        if materialize_rule(rule, as_of=today, max_catchup=max_catchup):
            touched += 1
    db.session.commit()
    return touched


def upcoming(days: int = 14, as_of: date | None = None):
    """Rules due within the next ``days`` days (inclusive). Sorted by date."""
    today = as_of or today_ist()
    horizon = today + timedelta(days=days)
    rows = []
    for rule in RecurringRule.query.filter_by(active=True).all():
        if rule.next_due_date and rule.next_due_date <= horizon:
            rows.append(rule)
    rows.sort(key=lambda r: r.next_due_date or today)
    return rows
