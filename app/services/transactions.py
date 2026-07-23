"""Transaction create/update/delete, splits, transfers, payee memory, filters."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import Transaction, PayeeMemory, Category, Account
from ..money import money, ZERO
from ..timeutil import parse_date, today_ist, month_start, month_end
from .budget import default_budget_month


class TxnError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Parsing a submitted form into a normalized dict
# ---------------------------------------------------------------------------
def parse_form(form) -> dict:
    ttype = form.get("type", "expense")
    if ttype not in ("expense", "income", "transfer", "savings"):
        ttype = "expense"
    txn_date = parse_date(form.get("date"), today_ist())

    data = {
        "type": ttype,
        "date": txn_date,
        "amount": money(form.get("amount")),
        "account_id": _int(form.get("account_id")),
        "transfer_account_id": _int(form.get("transfer_account_id")) if ttype == "transfer" else None,
        "category_id": _int(form.get("category_id")) if ttype != "transfer" else None,
        # Savings direction; manual entries default to a contribution ("out").
        "flow": (form.get("flow") if form.get("flow") in ("out", "in") else "out"),
        "payee": (form.get("payee") or "").strip(),
        "note": (form.get("note") or "").strip(),
        "tags": _clean_tags(form.get("tags")),
    }

    # Budget month: explicit override or salary-rule default.
    bm = form.get("budget_month")
    if bm:
        data["budget_month"] = parse_date(bm if len(bm) > 7 else bm + "-01", default_budget_month(txn_date, ttype))
    else:
        data["budget_month"] = default_budget_month(txn_date, ttype)

    # Splits (expense only): parallel arrays split_category[] / split_amount[]
    splits = []
    if ttype == "expense" and hasattr(form, "getlist"):
        cats = form.getlist("split_category")
        amts = form.getlist("split_amount")
        for c, a in zip(cats, amts):
            amt = money(a)
            if amt > 0:
                splits.append({"category_id": _int(c), "amount": amt})
    data["splits"] = splits
    return data


def validate(data: dict) -> None:
    if data["amount"] <= 0:
        raise TxnError("Enter an amount greater than zero.")
    if not data["account_id"]:
        raise TxnError("Choose an account.")
    if data["type"] == "transfer":
        if not data["transfer_account_id"]:
            raise TxnError("Choose a destination account for the transfer.")
        if data["transfer_account_id"] == data["account_id"]:
            raise TxnError("Transfer accounts must be different.")
    if data["splits"]:
        total = sum((s["amount"] for s in data["splits"]), ZERO)
        if total != data["amount"]:
            raise TxnError(f"Splits add up to {total}, but the total is {data['amount']}.")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def create(form) -> Transaction:
    data = parse_form(form)
    validate(data)
    t = Transaction(
        date=data["date"], amount=data["amount"], type=data["type"],
        account_id=data["account_id"], transfer_account_id=data["transfer_account_id"],
        category_id=None if data["splits"] else data["category_id"],
        flow=data["flow"] if data["type"] == "savings" else "out",
        payee=data["payee"], note=data["note"], tags=data["tags"],
        budget_month=data["budget_month"],
    )
    db.session.add(t)
    db.session.flush()
    _apply_splits(t, data["splits"])
    _remember_payee(t)
    db.session.commit()
    return t


def update(t: Transaction, form) -> Transaction:
    data = parse_form(form)
    validate(data)
    t.date = data["date"]
    t.amount = data["amount"]
    t.type = data["type"]
    t.account_id = data["account_id"]
    t.transfer_account_id = data["transfer_account_id"]
    t.category_id = None if data["splits"] else data["category_id"]
    t.flow = data["flow"] if data["type"] == "savings" else "out"
    t.payee = data["payee"]
    t.note = data["note"]
    t.tags = data["tags"]
    t.budget_month = data["budget_month"]
    # rebuild splits
    for child in list(t.splits):
        db.session.delete(child)
    db.session.flush()
    _apply_splits(t, data["splits"])
    _remember_payee(t)
    db.session.commit()
    return t


def delete(t: Transaction) -> None:
    db.session.delete(t)
    db.session.commit()


def _apply_splits(parent: Transaction, splits: list[dict]) -> None:
    for s in splits:
        db.session.add(Transaction(
            parent_id=parent.id, date=parent.date, amount=s["amount"], type="expense",
            account_id=parent.account_id, category_id=s["category_id"],
            payee=parent.payee, budget_month=parent.budget_month,
        ))


def _remember_payee(t: Transaction) -> None:
    if not t.payee or t.type in ("transfer", "savings"):
        return
    pm = PayeeMemory.query.filter_by(payee=t.payee).first()
    cat_id = t.category_id
    if cat_id is None and t.splits:
        cat_id = t.splits[0].category_id
    if pm is None:
        pm = PayeeMemory(payee=t.payee, last_category_id=cat_id,
                         last_account_id=t.account_id, last_type=t.type, uses=1)
        db.session.add(pm)
    else:
        pm.last_category_id = cat_id or pm.last_category_id
        pm.last_account_id = t.account_id
        pm.last_type = t.type
        pm.uses = (pm.uses or 0) + 1


def payee_suggestions(q: str, limit: int = 6):
    q = (q or "").strip()
    query = PayeeMemory.query
    if q:
        query = query.filter(PayeeMemory.payee.ilike(f"%{q}%"))
    return query.order_by(PayeeMemory.uses.desc(), PayeeMemory.updated_at.desc()).limit(limit).all()


def recent_payees(type_: str = "expense", limit: int = 5):
    """Most-used payees for a given transaction type, for the add-form chips."""
    return (PayeeMemory.query
            .filter(PayeeMemory.last_type == type_)
            .order_by(PayeeMemory.uses.desc(), PayeeMemory.updated_at.desc())
            .limit(limit).all())


def recent_amounts(type_: str = "expense", limit: int = 5):
    """Distinct recently-entered amounts for a type (newest first), as strings."""
    rows = (Transaction.query
            .filter(Transaction.parent_id.is_(None))
            .filter(Transaction.type == type_)
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(80).all())
    seen: list[str] = []
    for t in rows:
        a = str(t.amount)
        if a not in seen:
            seen.append(a)
        if len(seen) >= limit:
            break
    return seen


# ---------------------------------------------------------------------------
# Filtering the transactions page
# ---------------------------------------------------------------------------
def filter_transactions(args, page: int = 1, page_size: int = 50) -> dict:
    """Apply filters from request.args, return one page of rows + running totals.

    Totals (income/expense/net) are computed across the *entire* filtered set,
    not just the current page, so the summary strip always reflects everything
    the filters match.
    """
    q = Transaction.query.filter(Transaction.parent_id.is_(None))

    month = args.get("month")
    if month:
        m = parse_date(month + "-01" if len(month) == 7 else month)
        if m:
            q = q.filter(Transaction.date >= month_start(m),
                         Transaction.date <= month_end(m))

    if args.get("account"):
        acc = _int(args.get("account"))
        q = q.filter(db.or_(Transaction.account_id == acc,
                            Transaction.transfer_account_id == acc))
    if args.get("category"):
        q = q.filter(Transaction.category_id == _int(args.get("category")))
    if args.get("type") in ("income", "expense", "transfer", "savings"):
        q = q.filter(Transaction.type == args.get("type"))
    if args.get("tag"):
        q = q.filter(Transaction.tags.ilike(f"%{args.get('tag').strip()}%"))
    if args.get("payee"):
        q = q.filter(Transaction.payee.ilike(f"%{args.get('payee').strip()}%"))
    if args.get("q"):
        term = f"%{args.get('q').strip()}%"
        q = q.filter(db.or_(Transaction.payee.ilike(term), Transaction.note.ilike(term),
                            Transaction.tags.ilike(term)))

    all_rows = q.order_by(Transaction.date.desc(), Transaction.id.desc()).all()

    income = sum((money(t.amount) for t in all_rows if t.type == "income"), ZERO)
    expense = sum((money(t.amount) for t in all_rows if t.type == "expense"), ZERO)
    transfer = sum((money(t.amount) for t in all_rows if t.type == "transfer"), ZERO)
    # Net savings = contributions out minus redemptions in.
    savings = sum((t.signed_amount for t in all_rows if t.type == "savings"), ZERO) * -1

    page = max(1, page)
    start = (page - 1) * page_size
    page_rows = all_rows[start:start + page_size]
    total = len(all_rows)
    return {
        "rows": page_rows, "count": total,
        "income": income, "expense": expense, "transfer": transfer, "savings": savings,
        "net": income - expense,
        "page": page, "page_size": page_size,
        "shown": min(start + page_size, total),
        "has_more": start + page_size < total,
    }


def _int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _clean_tags(raw: str | None) -> str:
    if not raw:
        return ""
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    # de-dup, keep order
    seen, out = set(), []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return ", ".join(out)
