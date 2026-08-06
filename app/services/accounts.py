"""Account balance computation — always derived from transactions."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from ..extensions import db
from ..models import Account, Transaction, CASH_LIKE_TYPES
from ..money import ZERO, money


def all_balances(as_of=None) -> dict[int, Decimal]:
    """Balance for every account in one pass (opening + inflows - outflows).

    Transfers move money: they subtract from ``account_id`` and add to
    ``transfer_account_id``. Split children are ignored (the parent already
    carries the full amount against its account).

    ``as_of`` stops at a date (inclusive), which is what reconciliation needs:
    a bank's stated balance is a fact about one moment, so it has to be
    compared against the ledger at that moment rather than today's.
    """
    balances: dict[int, Decimal] = {}
    for acc in Account.query.all():
        balances[acc.id] = money(acc.opening_balance or ZERO)

    # Only parent/standalone rows affect balances (parent_id IS NULL).
    q = Transaction.query.filter(Transaction.parent_id.is_(None))
    if as_of is not None:
        q = q.filter(Transaction.date <= as_of)
    rows = q.all()
    for t in rows:
        amt = money(t.amount)
        if t.type == "income":
            balances[t.account_id] = balances.get(t.account_id, ZERO) + amt
        elif t.type == "expense":
            balances[t.account_id] = balances.get(t.account_id, ZERO) - amt
        elif t.type == "savings":
            # A contribution ("out") leaves cash; a redemption ("in") returns it.
            delta = amt if t.flow == "in" else -amt
            balances[t.account_id] = balances.get(t.account_id, ZERO) + delta
        elif t.type == "transfer":
            balances[t.account_id] = balances.get(t.account_id, ZERO) - amt
            if t.transfer_account_id is not None:
                balances[t.transfer_account_id] = balances.get(t.transfer_account_id, ZERO) + amt
    return balances


def account_balance(account_id: int) -> Decimal:
    return all_balances().get(account_id, ZERO)


def available_total() -> Decimal:
    """Sum of balances across cash-like accounts (bank/wallet/cash), excludes funds."""
    balances = all_balances()
    total = ZERO
    for acc in Account.query.filter(Account.is_archived.is_(False)).all():
        if acc.type in CASH_LIKE_TYPES:
            total += balances.get(acc.id, ZERO)
    return total


def funds_total() -> Decimal:
    """Sum of balances across envelope 'fund' accounts."""
    balances = all_balances()
    total = ZERO
    for acc in Account.query.filter(Account.is_archived.is_(False)).all():
        if acc.type == "fund":
            total += balances.get(acc.id, ZERO)
    return total


def list_with_balances(include_archived: bool = False):
    """Accounts (ordered) paired with their computed balance."""
    balances = all_balances()
    q = Account.query
    if not include_archived:
        q = q.filter(Account.is_archived.is_(False))
    accounts = q.order_by(Account.is_archived, Account.sort_order, Account.name).all()
    return [(a, balances.get(a.id, ZERO)) for a in accounts]


def active_accounts():
    return Account.query.filter(Account.is_archived.is_(False)).order_by(
        Account.sort_order, Account.name).all()


def default_account_id():
    """Best guess for a new expense's account: the most-used cash-like account,
    falling back to the first one. Used to prefill the add-transaction form so
    the user isn't forced to pick an account on every entry."""
    cash = Account.query.filter(
        Account.is_archived.is_(False),
        Account.type.in_(CASH_LIKE_TYPES),
    ).order_by(Account.sort_order, Account.id).all()
    if not cash:
        first = Account.query.filter(Account.is_archived.is_(False)).order_by(
            Account.sort_order).first()
        return first.id if first else None
    cash_ids = {a.id for a in cash}
    counts = dict(
        db.session.query(Transaction.account_id, db.func.count(Transaction.id))
        .filter(Transaction.type != "transfer")
        .group_by(Transaction.account_id).all()
    )
    ranked = sorted(cash, key=lambda a: (-counts.get(a.id, 0), a.sort_order, a.id))
    return ranked[0].id
