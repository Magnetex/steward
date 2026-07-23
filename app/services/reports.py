"""The four reports: spending by category, month-over-month, income/expense
trend (12 months), and top payees. All amounts Decimal, computed in Python."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import Transaction, Category
from ..money import ZERO, money
from ..timeutil import month_start, prev_month_start, add_months, month_label
from .budget import category_spent, income_received


def spending_by_category(month: date) -> list[dict]:
    spent = category_spent(month)
    cats = {c.id: c for c in Category.query.all()}
    rows = []
    for cid, amt in spent.items():
        if amt <= 0:
            continue
        c = cats.get(cid)
        rows.append({"name": c.name if c else "Uncategorised",
                     "icon": c.icon if c else "🔖", "amount": money(amt)})
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def month_over_month(month: date) -> dict:
    prev = prev_month_start(month)
    this_spent = category_spent(month)
    prev_spent = category_spent(prev)
    cats = {c.id: c for c in Category.query.all()}
    ids = set(this_spent) | set(prev_spent)
    rows = []
    for cid in ids:
        if cid is None:
            name, icon = "Uncategorised", "🔖"
        else:
            c = cats.get(cid)
            name, icon = (c.name, c.icon) if c else ("Uncategorised", "🔖")
        rows.append({"name": name, "icon": icon,
                     "this": money(this_spent.get(cid, ZERO)),
                     "prev": money(prev_spent.get(cid, ZERO))})
    rows.sort(key=lambda r: r["this"], reverse=True)
    return {"rows": rows, "this_label": month_label(month), "prev_label": month_label(prev)}


def income_expense_trend(month: date, months: int = 12) -> dict:
    labels, income, expense = [], [], []
    start = add_months(month, -(months - 1))
    m = month_start(start)
    for _ in range(months):
        labels.append(m.strftime("%b %y"))
        income.append(money(income_received(m)))
        exp = ZERO
        for amt in category_spent(m).values():
            exp += amt
        expense.append(money(exp))
        m = add_months(m, 1)
    return {"labels": labels, "income": income, "expense": expense}


def top_payees(month: date, limit: int = 8) -> list[dict]:
    from ..timeutil import month_end
    totals = defaultdict(lambda: ZERO)
    counts = defaultdict(int)
    rows = (Transaction.query
            .filter(Transaction.type == "expense", Transaction.parent_id.is_(None))
            .filter(Transaction.budget_month == month).all())
    for t in rows:
        payee = (t.payee or "").strip() or "—"
        totals[payee] += money(t.amount)
        counts[payee] += 1
    out = [{"payee": p, "amount": a, "count": counts[p]} for p, a in totals.items()]
    out.sort(key=lambda r: r["amount"], reverse=True)
    return out[:limit]
