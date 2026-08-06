"""Check the ledger against the balance the bank itself stated.

Every bank alert carries a running balance, and the SMS parser has always
recorded it on the queued row (``PendingImport.stated_balance``) — it was just
never read. It is the only independent figure the app has about an account, so
it catches what a ledger cannot notice about itself: a message dismissed by
mistake, a spend entered twice, cash that was never recorded at all.

The comparison is anchored to the moment of the message, not to today: the
bank stated that balance after that transaction, so the ledger has to be
measured at the same point. Money is compared in Python — DecimalText stores
it as TEXT, where "555" and "555.00" are different strings.
"""
from __future__ import annotations

from ..extensions import db
from ..models import Account, PendingImport
from ..money import ZERO, fmt_inr, money
from . import accounts as acc_svc


def latest_statements() -> dict[int, PendingImport]:
    """The newest message per account that quoted a balance.

    Status is not filtered: whether the row was confirmed, dismissed or is
    still waiting, the balance the bank quoted is a fact either way. What a
    still-pending row does mean is that the ledger is knowingly behind, which
    ``account_checks`` reports separately rather than calling a discrepancy.
    """
    rows = (PendingImport.query
            .filter(PendingImport.stated_balance.isnot(None))
            .filter(PendingImport.account_id.isnot(None))
            .order_by(PendingImport.received_at.desc(), PendingImport.id.desc())
            .all())
    newest: dict[int, PendingImport] = {}
    for row in rows:
        newest.setdefault(row.account_id, row)
    return newest


def _pending_before(account_id: int, on) -> int:
    """Imports still awaiting review that the stated balance already includes."""
    return (PendingImport.query
            .filter_by(account_id=account_id, status="pending")
            .filter(PendingImport.txn_date <= on)
            .count())


def account_checks() -> list[dict]:
    """One row per account the bank has quoted a balance for."""
    statements = latest_statements()
    if not statements:
        return []

    out = []
    for acc in (Account.query.filter(Account.is_archived.is_(False))
                .order_by(Account.sort_order, Account.name).all()):
        row = statements.get(acc.id)
        if row is None:
            continue
        stated = money(row.stated_balance)
        ledger = acc_svc.all_balances(as_of=row.txn_date).get(acc.id, ZERO)
        difference = money(ledger - stated)
        waiting = _pending_before(acc.id, row.txn_date)
        out.append({
            "account": acc,
            "stated": stated,
            "ledger": ledger,
            "difference": difference,
            "on": row.txn_date,
            "bank": row.bank,
            "waiting": waiting,
            # A gap the user can act on: everything the bank counted is in the
            # ledger, and the two still disagree.
            "matched": difference == ZERO,
            "explained": difference != ZERO and waiting > 0,
        })
    return out


def summary() -> dict:
    checks = account_checks()
    return {
        "checks": checks,
        "off": [c for c in checks if not c["matched"] and not c["explained"]],
        "waiting": [c for c in checks if c["explained"]],
    }


def sweep_reconciliation_alerts() -> None:
    """Raise an alert per account whose ledger disagrees with its bank.

    Only for unexplained gaps — when imports are still queued the difference is
    expected, and the review queue already says so.
    """
    from .alerts import add_alert

    for check in summary()["off"]:
        acc = check["account"]
        diff = check["difference"]
        direction = "more" if diff > 0 else "less"
        add_alert(
            "reminder",
            f"{acc.icon} {acc.name}: {check['bank'].upper()} stated "
            f"{_inr(check['stated'])} on {check['on'].strftime('%d %b')}, but the "
            f"ledger says {_inr(check['ledger'])} — {_inr(abs(diff))} {direction} "
            "than the bank counted.",
            dedupe_key=f"reconcile-{acc.id}-{check['on'].isoformat()}",
            action="/accounts/",
            ref_id=acc.id,
        )
    db.session.commit()


def _inr(value) -> str:
    return fmt_inr(value, paise=False)
