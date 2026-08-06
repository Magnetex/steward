"""Checking the ledger against the balance the bank quoted in its SMS.

The balance was already being captured on every imported row and never read.
These cover what it now catches, and what it must not cry wolf about.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Account, Alert, PendingImport, Transaction
from app.services import reconcile

D = Decimal


@pytest.fixture
def bank(app):
    """One account at 1,00,000 with a 555 spend on 26 Jul."""
    with app.app_context():
        acc = Account(name="HDFC Savings", type="savings_bank", icon="🏦",
                      opening_balance=D("100000"), sms_identifiers="4458")
        db.session.add(acc)
        db.session.flush()
        db.session.add(Transaction(date=date(2026, 7, 26), amount=D("555"),
                                   type="expense", account_id=acc.id,
                                   budget_month=date(2026, 7, 1)))
        db.session.commit()
    yield app


def _statement(balance, on=date(2026, 7, 26), status="confirmed", account_id=1,
               received=None, dedupe="x"):
    row = PendingImport(
        source="sms", sender="VM-HDFCBK", body="…", bank="hdfc",
        received_at=received or datetime(2026, 7, 26, 22, 1),
        dedupe_hash=dedupe, direction="debit", amount=D("555"), txn_date=on,
        stated_balance=D(str(balance)), account_id=account_id, status=status,
        suggested_type="expense")
    db.session.add(row)
    db.session.commit()
    return row


def test_no_statements_means_nothing_to_show(bank):
    with bank.app_context():
        assert reconcile.account_checks() == []


def test_a_ledger_that_agrees_with_the_bank_is_matched(bank):
    with bank.app_context():
        _statement("99445")                       # 100000 - 555
        check, = reconcile.account_checks()

        assert check["matched"] is True
        assert check["difference"] == D("0.00")
        assert check["stated"] == D("99445.00")
        assert check["ledger"] == D("99445.00")


def test_a_missing_transaction_shows_as_a_difference(bank):
    """The ledger thinks there's more money than the bank counted."""
    with bank.app_context():
        _statement("99000")
        check, = reconcile.account_checks()

        assert check["matched"] is False
        assert check["explained"] is False
        assert check["difference"] == D("445.00")


def test_the_comparison_is_anchored_to_the_message_not_today(bank):
    """A spend after the message must not read as a discrepancy."""
    with bank.app_context():
        db.session.add(Transaction(date=date(2026, 7, 30), amount=D("2000"),
                                   type="expense", account_id=1,
                                   budget_month=date(2026, 7, 1)))
        db.session.commit()
        _statement("99445")

        check, = reconcile.account_checks()
        assert check["matched"] is True, "the later spend is outside the comparison"


def test_the_newest_statement_wins(bank):
    with bank.app_context():
        _statement("99445", dedupe="older")
        _statement("90000", on=date(2026, 7, 28),
                   received=datetime(2026, 7, 28, 9, 0), dedupe="newer")

        check, = reconcile.account_checks()
        assert check["on"] == date(2026, 7, 28)
        assert check["stated"] == D("90000.00")


def test_imports_still_in_the_queue_explain_the_gap(bank):
    """Not a discrepancy — the ledger is knowingly behind."""
    with bank.app_context():
        _statement("99000", status="pending")

        check, = reconcile.account_checks()
        assert check["matched"] is False
        assert check["explained"] is True
        assert check["waiting"] == 1


def test_an_unexplained_gap_raises_one_alert(bank):
    with bank.app_context():
        _statement("99000")
        reconcile.sweep_reconciliation_alerts()

        alerts = Alert.query.all()
        assert len(alerts) == 1
        assert "HDFC" in alerts[0].message and "445" in alerts[0].message

        reconcile.sweep_reconciliation_alerts()      # deduped while unread
        assert Alert.query.count() == 1


def test_a_matching_account_raises_no_alert(bank):
    with bank.app_context():
        _statement("99445")
        reconcile.sweep_reconciliation_alerts()
        assert Alert.query.count() == 0


def test_a_queue_backlog_raises_no_alert(bank):
    """The review queue already says so; a second nag helps nobody."""
    with bank.app_context():
        _statement("99000", status="pending")
        reconcile.sweep_reconciliation_alerts()
        assert Alert.query.count() == 0


def test_the_accounts_page_shows_the_comparison(bank):
    with bank.app_context():
        _statement("99000")
    html = bank.test_client().get("/accounts/").get_data(as_text=True)
    assert "Against your bank" in html
    assert "HDFC stated" in html
    assert "to check" in html
