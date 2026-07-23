"""Budget aggregation and the month-end salary rule.

Spent is always computed from transactions (never stored). Split transactions
attribute each child's amount to its own category; childless expenses use the
parent's category.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import Transaction, BudgetLine, Category
from ..money import ZERO, money
from ..timeutil import month_start, month_end, next_month_start
from .settings import salary_window_days

# Overshoot thresholds are fixed by the spec.
WARN_THRESHOLD = Decimal("0.80")
OVER_THRESHOLD = Decimal("1.00")


def default_budget_month(txn_date: date, txn_type: str) -> date:
    """Where an income/expense lands by default.

    Income dated in the last N days of a month rolls into next month's budget
    (N = the 'salary_rule_window' setting). Everything else lands in its own
    calendar month.
    """
    if txn_type == "income":
        window = salary_window_days()
        if (month_end(txn_date) - txn_date).days < window:
            return next_month_start(txn_date)
    return month_start(txn_date)


def is_salary_rule_shifted(txn_date: date, budget_month: date) -> bool:
    return month_start(txn_date) != budget_month


def _expense_rows(month: date):
    return (
        Transaction.query
        .filter(Transaction.type == "expense")
        .filter(Transaction.parent_id.is_(None))
        .filter(Transaction.budget_month == month)
        .all()
    )


def category_spent(month: date) -> dict[int | None, Decimal]:
    """category_id -> total spent in ``month``'s budget. Splits expanded.

    Key ``None`` collects uncategorised expenses.
    """
    out: dict[int | None, Decimal] = defaultdict(lambda: ZERO)
    for t in _expense_rows(month):
        if t.splits:
            for s in t.splits:
                out[s.category_id] += money(s.amount)
        else:
            out[t.category_id] += money(t.amount)
    return dict(out)


def income_received(month: date) -> Decimal:
    total = ZERO
    rows = (
        Transaction.query
        .filter(Transaction.type == "income")
        .filter(Transaction.parent_id.is_(None))
        .filter(Transaction.budget_month == month)
        .all()
    )
    for t in rows:
        total += money(t.amount)
    return total


def income_received_by_category(month: date) -> dict[int | None, Decimal]:
    out: dict[int | None, Decimal] = defaultdict(lambda: ZERO)
    rows = (
        Transaction.query
        .filter(Transaction.type == "income")
        .filter(Transaction.parent_id.is_(None))
        .filter(Transaction.budget_month == month)
        .all()
    )
    for t in rows:
        out[t.category_id] += money(t.amount)
    return dict(out)


def compute_income(month: date) -> dict:
    """Income section: per-category planned vs received, plus totals."""
    received_map = income_received_by_category(month)
    lines = {ln.category_id: ln for ln in
             BudgetLine.query.filter_by(budget_month=month).all()}
    cats = Category.query.filter_by(kind="income", is_archived=False).order_by(
        Category.sort_order, Category.name).all()
    rows = []
    total_planned = ZERO
    total_received = ZERO
    shown = set()
    for cat in cats:
        line = lines.get(cat.id)
        received = received_map.get(cat.id, ZERO)
        planned = money(line.planned_amount) if line else ZERO
        if line is None and received == 0:
            continue
        shown.add(cat.id)
        rows.append({"category": cat, "planned": planned, "received": received,
                     "has_line": line is not None})
        total_planned += planned
        total_received += received
    # uncategorised / archived income
    extra = ZERO
    for cid, amt in received_map.items():
        if cid not in shown:
            extra += amt
    return {
        "rows": rows, "total_planned": total_planned,
        "total_received": total_received, "extra": extra,
    }


def savings_saved_by_category(month: date) -> dict[int | None, Decimal]:
    """category_id -> net saved (contributions out minus redemptions in) in
    ``month``'s budget for savings transactions."""
    out: dict[int | None, Decimal] = defaultdict(lambda: ZERO)
    rows = (
        Transaction.query
        .filter(Transaction.type == "savings")
        .filter(Transaction.parent_id.is_(None))
        .filter(Transaction.budget_month == month)
        .all()
    )
    for t in rows:
        out[t.category_id] += money(t.amount) if t.flow != "in" else -money(t.amount)
    return dict(out)


def compute_savings(month: date) -> dict:
    """Savings section: per-category planned vs actually-saved, plus totals."""
    saved_map = savings_saved_by_category(month)
    lines = {ln.category_id: ln for ln in
             BudgetLine.query.filter_by(budget_month=month).all()}
    cats = Category.query.filter_by(kind="savings", is_archived=False).order_by(
        Category.sort_order, Category.name).all()
    rows = []
    total_planned = ZERO
    total_saved = ZERO
    shown = set()
    for cat in cats:
        line = lines.get(cat.id)
        saved = saved_map.get(cat.id, ZERO)
        planned = money(line.planned_amount) if line else ZERO
        if line is None and saved == 0:
            continue
        shown.add(cat.id)
        rows.append({"category": cat, "planned": planned, "saved": saved,
                     "state": bar_state(saved, planned), "pct": _pct(saved, planned),
                     "has_line": line is not None,
                     "line_id": line.id if line else None})
        total_planned += planned
        total_saved += saved
    extra = ZERO
    for cid, amt in saved_map.items():
        if cid not in shown:
            extra += amt
    return {
        "rows": rows, "total_planned": total_planned,
        "total_saved": money(total_saved), "extra": money(extra),
    }


def savings_planned(month: date) -> Decimal:
    """Planned savings = budget lines for savings categories."""
    total = ZERO
    lines = (
        db.session.query(BudgetLine, Category)
        .join(Category, Category.id == BudgetLine.category_id)
        .filter(BudgetLine.budget_month == month, Category.kind == "savings")
        .all()
    )
    for line, _cat in lines:
        total += money(line.planned_amount)
    return total


def income_planned(month: date) -> Decimal:
    """Planned income = budget lines for income categories."""
    total = ZERO
    lines = (
        db.session.query(BudgetLine, Category)
        .join(Category, Category.id == BudgetLine.category_id)
        .filter(BudgetLine.budget_month == month, Category.kind == "income")
        .all()
    )
    for line, _cat in lines:
        total += money(line.planned_amount)
    return total


def bar_state(spent: Decimal, planned: Decimal) -> str:
    """'none' | 'ok' | 'warn' | 'over' — drives the progress-bar colour."""
    if planned <= 0:
        return "over" if spent > 0 else "none"
    ratio = spent / planned
    if ratio > OVER_THRESHOLD:
        return "over"
    if ratio >= WARN_THRESHOLD:
        return "warn"
    return "ok"


def compute_budget(month: date) -> dict:
    """Full budget view for ``month``: grouped rows, totals, unbudgeted row."""
    spent_map = category_spent(month)

    lines = (
        db.session.query(BudgetLine)
        .filter(BudgetLine.budget_month == month)
        .all()
    )
    line_by_cat = {ln.category_id: ln for ln in lines}

    # Expense categories that either have a budget line OR have spending.
    cats = Category.query.filter_by(kind="expense").order_by(
        Category.group, Category.sort_order, Category.name
    ).all()

    groups: dict[str, list] = defaultdict(list)
    total_planned = ZERO
    total_spent = ZERO

    budgeted_cat_ids = set()
    for cat in cats:
        line = line_by_cat.get(cat.id)
        if line is None:
            continue  # no budget line -> spending (if any) lands in Unbudgeted
        spent = spent_map.get(cat.id, ZERO)
        planned = money(line.planned_amount)
        budgeted_cat_ids.add(cat.id)
        remaining = planned - spent
        row = {
            "category": cat,
            "planned": planned,
            "spent": spent,
            "remaining": remaining,
            "state": bar_state(spent, planned),
            "pct": _pct(spent, planned),
            "has_line": True,
            "line_id": line.id,
        }
        groups[cat.group or "Other"].append(row)
        total_planned += planned
        total_spent += spent

    # Unbudgeted spending: every expense in a category with no budget line for
    # this month, plus uncategorised spending (spec: a single catch-all row).
    unbudgeted = ZERO
    unbudgeted_rows = []
    cat_by_id = {c.id: c for c in cats}
    for cat_id, amt in spent_map.items():
        if cat_id in budgeted_cat_ids or amt <= 0:
            continue
        unbudgeted += amt
        c = cat_by_id.get(cat_id)
        unbudgeted_rows.append({
            "name": c.name if c else "Uncategorised",
            "icon": c.icon if c else "🔖",
            "category_id": cat_id, "amount": money(amt),
        })
    unbudgeted_rows.sort(key=lambda r: r["amount"], reverse=True)

    grouped = []
    for gname in _ordered_groups(groups.keys()):
        rows = groups[gname]
        grouped.append({
            "name": gname,
            "rows": rows,
            "planned": sum((r["planned"] for r in rows), ZERO),
            "spent": sum((r["spent"] for r in rows), ZERO),
        })

    savings = compute_savings(month)
    return {
        "month": month,
        "groups": grouped,
        "total_planned": total_planned,
        "total_spent": total_spent,
        "total_remaining": total_planned - total_spent,
        "unbudgeted": money(unbudgeted),
        "unbudgeted_rows": unbudgeted_rows,
        "income_planned": income_planned(month),
        "income_received": income_received(month),
        "savings": savings,
        "savings_planned": savings["total_planned"],
        "savings_saved": savings["total_saved"],
    }


_GROUP_ORDER = ["Essentials", "Lifestyle", "Giving", "Savings", "Other"]


def _ordered_groups(names):
    known = [g for g in _GROUP_ORDER if g in names]
    rest = sorted(n for n in names if n not in _GROUP_ORDER)
    return known + rest


def _pct(spent: Decimal, planned: Decimal) -> int:
    if planned <= 0:
        return 100 if spent > 0 else 0
    return int((spent / planned * 100).to_integral_value())


# ---------------------------------------------------------------------------
# Budget-line editing
# ---------------------------------------------------------------------------
def upsert_line(month: date, category_id: int, planned_amount) -> BudgetLine:
    line = BudgetLine.query.filter_by(budget_month=month, category_id=category_id).first()
    if line is None:
        line = BudgetLine(budget_month=month, category_id=category_id)
        db.session.add(line)
    line.planned_amount = money(planned_amount)
    db.session.commit()
    return line


def remove_line(month: date, category_id: int) -> None:
    BudgetLine.query.filter_by(budget_month=month, category_id=category_id).delete()
    db.session.commit()


def copy_from_previous(month: date) -> int:
    """Copy the previous month's planned amounts into ``month`` (skip existing)."""
    from ..timeutil import prev_month_start
    prev = prev_month_start(month)
    existing = {ln.category_id for ln in BudgetLine.query.filter_by(budget_month=month)}
    n = 0
    for ln in BudgetLine.query.filter_by(budget_month=prev).all():
        if ln.category_id in existing:
            continue
        db.session.add(BudgetLine(budget_month=month, category_id=ln.category_id,
                                  planned_amount=ln.planned_amount))
        n += 1
    db.session.commit()
    return n


def check_overshoots(month: date, only_categories: set | None = None) -> list[dict]:
    """Return rows over 100% and (de-duplicated) create alerts for them."""
    from .alerts import add_alert
    from ..timeutil import month_label
    from ..money import fmt_inr
    data = compute_budget(month)
    over = []
    for group in data["groups"]:
        for row in group["rows"]:
            if row["state"] == "over" and row["planned"] > 0:
                over.append(row)
                if only_categories is None or row["category"].id in only_categories:
                    add_alert(
                        "overshoot",
                        f"{row['category'].name} is over budget for {month_label(month)} "
                        f"— {fmt_inr(row['spent'])} of {fmt_inr(row['planned'])}",
                        dedupe_key=f"overshoot:{month.isoformat()}:{row['category'].id}",
                    )
    db.session.commit()
    return over
