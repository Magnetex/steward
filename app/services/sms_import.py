"""Read bank SMS from Termux and queue them for review.

The Flask process runs inside Termux on the phone, so it can call
``termux-sms-list`` directly rather than needing a separate script to post
messages in. Everything below the fetch is plain data, so the pipeline is
testable without a phone.

Nothing here ever writes to the ledger. Parsed messages become
``PendingImport`` rows; only an explicit confirmation creates a transaction.

Two guards keep re-scanning safe:

* a **watermark** — the timestamp of the newest message already handled, so
  each SMS is considered exactly once, no matter how often you scan;
* a **first-run cutoff** — the very first scan imports nothing and simply
  plants the watermark at "now", so enabling the feature never drags in a
  month of history or duplicates transactions already entered by hand.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime, timedelta

from ..extensions import db
from ..models import Account, PayeeMemory, PendingImport, Setting, Transaction
from ..money import money
from ..timeutil import now_ist
from . import sms_parse

log = logging.getLogger("steward.sms")

WATERMARK_KEY = "sms_watermark"      # newest message already processed
LAST_SCAN_KEY = "sms_last_scan"      # when a scan last ran, for the UI

FETCH_LIMIT = 100        # messages to pull per scan
DUPLICATE_WINDOW_DAYS = 3  # how far either side to look for a manual entry


class SMSUnavailable(Exception):
    """Termux:API isn't available — the app isn't on a phone, or it isn't set up."""


# --- fetching --------------------------------------------------------------
def termux_available() -> bool:
    return shutil.which("termux-sms-list") is not None


def fetch_messages(limit: int = FETCH_LIMIT) -> list[dict]:
    """Read the SMS inbox via Termux:API.

    Raises SMSUnavailable with a message worth showing the user, rather than
    surfacing a raw OSError from the missing binary.
    """
    if not termux_available():
        raise SMSUnavailable(
            "SMS scanning needs Termux:API. Install the Termux:API app, then "
            "run: pkg install termux-api")
    try:
        out = subprocess.run(
            ["termux-sms-list", "-l", str(limit), "-t", "inbox"],
            capture_output=True, text=True, timeout=60, check=True)
    except subprocess.TimeoutExpired as exc:
        raise SMSUnavailable("Reading SMS timed out.") from exc
    except subprocess.CalledProcessError as exc:
        raise SMSUnavailable(
            "Couldn't read SMS — grant the SMS permission to Termux:API in "
            f"Android settings. ({(exc.stderr or '').strip()[:120]})") from exc
    try:
        return json.loads(out.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SMSUnavailable("Termux returned something unreadable.") from exc


def _received_at(raw: dict) -> datetime | None:
    """Termux reports 'received' as 'YYYY-MM-DD HH:MM:SS'."""
    value = (raw.get("received") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def dedupe_hash(sender: str, body: str, received: datetime) -> str:
    raw = f"{sender}|{body}|{received.isoformat(timespec='seconds')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- watermark -------------------------------------------------------------
def get_watermark() -> datetime | None:
    raw = Setting.get(WATERMARK_KEY)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def last_scan_at() -> datetime | None:
    raw = Setting.get(LAST_SCAN_KEY)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# --- resolving against the user's accounts ---------------------------------
def _account_by_hint(hint: str) -> Account | None:
    """Match trailing digits from an SMS to an account.

    Compared as a suffix so "XXXXXXX458" still matches an account registered
    as "4458" — banks mask a varying number of digits between messages.
    """
    if not hint:
        return None
    digits = hint.strip()
    for acct in Account.query.filter_by(is_archived=False).all():
        for known in acct.sms_id_list:
            if digits.endswith(known) or known.endswith(digits):
                return acct
    return None


def _category_from_payee(payee: str, txn_type: str) -> int | None:
    """Reuse the payee memory the manual add-form already builds."""
    if not payee:
        return None
    pm = (PayeeMemory.query
          .filter(db.func.lower(PayeeMemory.payee) == payee.lower())
          .first())
    if pm and pm.last_category_id:
        return pm.last_category_id
    return None


def _find_possible_duplicate(account_id, amount, on, direction) -> Transaction | None:
    """An existing transaction that looks like this same spend, entered by hand.

    Amounts are compared in Python, not SQL: DecimalText stores money as TEXT,
    so ``amount == money(x)`` is a *string* comparison and "555" would fail to
    match "555.00". Narrow on the indexed columns, then compare as Decimals.
    """
    if not account_id:
        return None
    lo, hi = on - timedelta(days=DUPLICATE_WINDOW_DAYS), on + timedelta(days=DUPLICATE_WINDOW_DAYS)
    ttype = "expense" if direction == "debit" else "income"
    target = money(amount)
    candidates = (Transaction.query
                  .filter(Transaction.parent_id.is_(None))
                  .filter(Transaction.account_id == account_id)
                  .filter(Transaction.type.in_([ttype, "transfer"]))
                  .filter(Transaction.date.between(lo, hi))
                  .all())
    for t in candidates:
        if money(t.amount) == target:
            return t
    return None


def _build_pending(sender, body, received, parsed) -> PendingImport:
    account = _account_by_hint(parsed.account_hint)
    counterparty = _account_by_hint(parsed.counterparty_hint)

    # Both ends are the user's own accounts: one transfer, not an expense plus
    # an income, which would inflate both sides of the budget.
    if counterparty is not None and account is not None:
        ttype = "transfer"
    elif parsed.direction == "debit":
        ttype = "expense"
    else:
        ttype = "income"

    on = parsed.txn_date or received.date()
    row = PendingImport(
        source="sms", sender=sender, body=body[:1000], received_at=received,
        dedupe_hash=dedupe_hash(sender, body, received),
        bank=parsed.bank, direction=parsed.direction, amount=money(parsed.amount),
        txn_date=on, payee=parsed.payee, reference=parsed.reference,
        stated_balance=parsed.balance, is_reversal=parsed.is_reversal,
        account_id=account.id if account else None,
        transfer_account_id=counterparty.id if counterparty else None,
        suggested_type=ttype, status="pending",
    )
    if ttype != "transfer":
        row.category_id = _category_from_payee(parsed.payee, ttype)
    dup = _find_possible_duplicate(row.account_id, parsed.amount, on, parsed.direction)
    row.duplicate_of_id = dup.id if dup else None
    return row


# --- the scan --------------------------------------------------------------
def scan(messages: list[dict] | None = None) -> dict:
    """Import anything new. Returns a summary for the UI.

    ``messages`` is injectable so the pipeline can be tested without a phone;
    left as None it reads the real inbox.
    """
    started = now_ist().replace(tzinfo=None)
    first_run = get_watermark() is None

    if first_run:
        # Plant the watermark and import nothing: enabling the feature must not
        # pull in old messages, nor duplicate what's already entered by hand.
        Setting.set(WATERMARK_KEY, started.isoformat())
        Setting.set(LAST_SCAN_KEY, started.isoformat())
        db.session.commit()
        return {"first_run": True, "imported": 0, "skipped": 0, "scanned": 0,
                "message": "Ready — transactions from new bank SMS will appear here."}

    if messages is None:
        messages = fetch_messages()

    watermark = get_watermark()
    newest = watermark
    imported = skipped = 0

    for raw in messages:
        sender = (raw.get("sender") or raw.get("number") or "").strip()
        body = (raw.get("body") or "").strip()
        received = _received_at(raw)
        if received is None or not body:
            continue
        if watermark and received <= watermark:
            continue          # already handled on an earlier scan
        if newest is None or received > newest:
            newest = received
        if not sms_parse.is_known_sender(sender):
            continue          # not a bank we know: never even parsed

        parsed = sms_parse.parse(sender, body)
        if parsed is None:
            skipped += 1      # a bank message, but not a transaction alert
            continue

        row = _build_pending(sender, body, received, parsed)
        db.session.add(row)
        try:
            db.session.flush()
            imported += 1
        except Exception:     # noqa: BLE001 - unique dedupe_hash collision
            db.session.rollback()

    if newest:
        Setting.set(WATERMARK_KEY, newest.isoformat())
    Setting.set(LAST_SCAN_KEY, started.isoformat())
    db.session.commit()
    return {"first_run": False, "imported": imported, "skipped": skipped,
            "scanned": len(messages),
            "message": f"{imported} new transaction(s) found." if imported
                       else "No new transactions."}


def pending_count() -> int:
    return PendingImport.query.filter_by(status="pending").count()


def pending_rows():
    return (PendingImport.query.filter_by(status="pending")
            .order_by(PendingImport.txn_date.desc(), PendingImport.id.desc()).all())


# --- acting on the queue ---------------------------------------------------
def confirm(row: PendingImport, *, account_id=None, category_id=None,
            transfer_account_id=None, txn_type=None, payee=None,
            on=None) -> Transaction:
    """Turn a reviewed row into a real transaction.

    The caller passes whatever the user corrected in the queue; anything left
    out falls back to what was parsed.
    """
    from .transactions import _remember_payee
    from .budget import default_budget_month

    ttype = txn_type or row.suggested_type
    acct = account_id or row.account_id
    if not acct:
        raise ValueError("Choose an account before confirming.")

    when = on or row.txn_date
    txn = Transaction(
        date=when, amount=money(row.amount), type=ttype,
        account_id=acct,
        transfer_account_id=(transfer_account_id or row.transfer_account_id)
        if ttype == "transfer" else None,
        category_id=None if ttype == "transfer" else (category_id or row.category_id),
        payee=(payee if payee is not None else row.payee) or "",
        note=f"Imported from {row.bank.upper()} SMS",
        budget_month=default_budget_month(when, ttype),
    )
    db.session.add(txn)
    db.session.flush()

    if txn.payee:
        _remember_payee(txn)
    row.status = "confirmed"
    row.transaction_id = txn.id
    db.session.commit()
    return txn


def dismiss(row: PendingImport) -> None:
    row.status = "dismissed"
    db.session.commit()
