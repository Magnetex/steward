"""Link investment purchases/redemptions to cash movements.

Buying an investment optionally debits a cash account via a ``savings``
transaction (``flow="out"``); selling credits it back (``flow="in"``). Each such
transaction carries ``invest_kind`` + ``invest_ref_id`` so it can be found and
removed when the underlying investment record changes. The funded asset is
valued in its own net-worth bucket, so cash-out + bucket-up nets to zero.
"""
from __future__ import annotations

from datetime import date

from ..extensions import db
from ..models import Transaction, Category
from ..money import money, ZERO
from .budget import default_budget_month

# Fixed savings category per investment kind: (name, icon, sort_order). One tab
# in the Savings page maps to exactly one of these categories, so every funded
# entry lands under a predictable budget label. This set is static — the
# Category-management UI does not let you add/remove savings categories.
SAVINGS_CATEGORIES = {
    "mf": ("Mutual Funds", "📈", 1),
    "gold": ("Gold", "🪙", 2),
    "deposit": ("Deposits", "🏦", 3),
    "epf": ("EPF", "🏛️", 4),
    "stock": ("Stocks", "📊", 5),
}

# The canonical names, for the UI to recognise (and lock) these categories.
SAVINGS_CATEGORY_NAMES = {name for name, _icon, _order in SAVINGS_CATEGORIES.values()}


def savings_category_id(kind: str) -> int | None:
    """Get — creating if needed — the savings category for an investment kind."""
    spec = SAVINGS_CATEGORIES.get(kind)
    if not spec:
        return None
    name, icon, order = spec
    cat = Category.query.filter_by(kind="savings", name=name).first()
    if cat is None:
        cat = Category(name=name, kind="savings", icon=icon, group="Savings",
                       sort_order=order)
        db.session.add(cat)
        db.session.flush()
    return cat.id


def ensure_savings_categories() -> None:
    """Idempotently create the five static savings categories if missing.

    Safe to call from a read view — creates only what's absent, then commits.
    """
    changed = False
    for name, icon, order in SAVINGS_CATEGORIES.values():
        if Category.query.filter_by(kind="savings", name=name).first() is None:
            db.session.add(Category(name=name, kind="savings", icon=icon,
                                    group="Savings", sort_order=order))
            changed = True
    if changed:
        db.session.commit()


def sync_cash(kind: str, ref_id: int, *, account_id, amount, on: date,
              flow: str = "out", payee: str = "", note: str = "") -> Transaction | None:
    """Create/replace the linked cash transaction for an investment record.

    Idempotent: any existing link for (kind, ref_id) is removed first, so this
    doubles as the edit path. A falsy ``account_id`` (or non-positive amount)
    means "no cash effect" — e.g. backfilling a holding already funded — and
    leaves no linked transaction behind.
    """
    unlink_cash(kind, ref_id)
    if not account_id or money(amount) <= 0:
        return None
    t = Transaction(
        date=on, amount=money(amount), type="savings", flow=flow,
        account_id=int(account_id), category_id=savings_category_id(kind),
        payee=payee, note=note, invest_kind=kind, invest_ref_id=ref_id,
        budget_month=default_budget_month(on, "savings"),
    )
    db.session.add(t)
    return t


def credit_cash(kind: str, ref_id: int, *, account_id, amount, on: date,
                payee: str = "", note: str = "") -> Transaction | None:
    """Append a redemption ("in") cash credit WITHOUT removing existing links.

    Unlike :func:`sync_cash` (which unlinks first, so it can only hold a single
    linked movement), this *adds* a credit alongside the existing contribution
    transactions. Used when a deposit is closed/matured: its original principal /
    installment out-flows are real past cash and must stay; this records the
    proceeds coming back to cash. A falsy ``account_id`` / non-positive amount is
    a no-op.
    """
    if not account_id or money(amount) <= 0:
        return None
    t = Transaction(
        date=on, amount=money(amount), type="savings", flow="in",
        account_id=int(account_id), category_id=savings_category_id(kind),
        payee=payee, note=note, invest_kind=kind, invest_ref_id=ref_id,
        budget_month=default_budget_month(on, "savings"),
    )
    db.session.add(t)
    return t


def unlink_cash(kind: str, ref_id: int) -> int:
    """Delete any linked cash transaction(s) for (kind, ref_id). Returns count."""
    rows = Transaction.query.filter_by(invest_kind=kind, invest_ref_id=ref_id).all()
    for t in rows:
        db.session.delete(t)
    return len(rows)


def _remove_invest_rules(kind: str, ref_id: int) -> int:
    """Delete recurring rules auto-created for (kind, ref_id). Returns count.

    Only future occurrences stop — already-generated installments are real past
    cash movements and are left in place.
    """
    from ..models import RecurringRule
    rows = RecurringRule.query.filter_by(invest_kind=kind, invest_ref_id=ref_id).all()
    for r in rows:
        db.session.delete(r)
    return len(rows)


def sync_deposit_cash(deposit, account_id) -> None:
    """Fund a deposit from cash. Does not commit.

    FD = one principal outflow (idempotent: replaced on edit). RD = a monthly
    auto-contribution handled by ``services.rd`` (its own engine, NOT a recurring
    rule — so RDs never show on the Recurring page); past installments stay
    asset-only, future ones debit the account. RD edits must NOT wipe already-run
    installments, so only the FD path clears prior links.
    """
    _remove_invest_rules("deposit", deposit.id)   # drop any legacy RD rule

    if deposit.kind == "FD":
        unlink_cash("deposit", deposit.id)        # one-shot: safe to replace
        if account_id:
            sync_cash("deposit", deposit.id, account_id=account_id,
                      amount=deposit.principal, on=deposit.start_date, flow="out",
                      note=f"FD · {deposit.bank}".strip(" ·"))
        deposit.account_id = int(account_id) if account_id else None
        return

    # RD: delegate to the dedicated auto-contribution engine.
    from .rd import sync_rd_plan
    sync_rd_plan(deposit, account_id)
