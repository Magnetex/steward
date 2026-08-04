"""The ingest pipeline: watermark, dedupe, matching, transfers, duplicates.

Messages are injected rather than read from a phone, so everything below the
Termux fetch is exercised here.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import (Account, Category, PayeeMemory, PendingImport, Setting,
                        Transaction)
from app.services import sms_import as si
from tests.test_sms_parse import (HDFC_CARD, HDFC_UPI_SENT, HDFC_SALARY,
                                  RNSB_IMPS_OUT, PLUXEE_FEE)

D = Decimal


def _msg(sender, body, when):
    return {"sender": sender, "body": body,
            "received": when.strftime("%Y-%m-%d %H:%M:%S")}


@pytest.fixture
def ledger(app):
    """A ledger with SMS identifiers registered, past the first-run guard."""
    with app.app_context():
        hdfc = Account(name="HDFC Savings", type="savings_bank",
                       opening_balance=D("100000"), sms_identifiers="4458,8876")
        rnsb = Account(name="RNSB", type="savings_bank",
                       opening_balance=D("50000"), sms_identifiers="7655")
        pluxee = Account(name="Pluxee Meal", type="wallet",
                         opening_balance=D("5000"), sms_identifiers="7803")
        db.session.add_all([hdfc, rnsb, pluxee])
        db.session.add(Category(name="Food", kind="expense", icon="🍽️"))
        # Past the first run, so scans actually import.
        Setting.set(si.WATERMARK_KEY, (datetime(2026, 7, 1)).isoformat())
        db.session.commit()
    yield app


def test_first_scan_imports_nothing_and_plants_the_watermark(app):
    """Enabling the feature must not drag in the existing inbox."""
    with app.app_context():
        old = _msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 6, 1, 10, 0))
        result = si.scan([old])

        assert result["first_run"] is True
        assert result["imported"] == 0
        assert PendingImport.query.count() == 0
        assert si.get_watermark() is not None


def test_imports_a_new_message(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])

        row = PendingImport.query.one()
        assert row.amount == D("555")
        assert row.direction == "debit"
        assert row.suggested_type == "expense"
        assert row.payee == "BHATTA S FOODS PRIVATE"
        assert row.account.name == "HDFC Savings", "card digits should map to the account"
        assert row.status == "pending"


def test_rescanning_the_same_message_imports_it_once(ledger):
    """The inbox is re-read every scan; the watermark must make that a no-op."""
    msg = _msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0))
    with ledger.app_context():
        si.scan([msg])
        si.scan([msg])
        si.scan([msg])
        assert PendingImport.query.count() == 1


def test_messages_older_than_the_watermark_are_ignored(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 6, 1, 10, 0))])
        assert PendingImport.query.count() == 0


def test_non_bank_senders_are_never_parsed(ledger):
    with ledger.app_context():
        si.scan([
            _msg("MOM", "Call me when you're free", datetime(2026, 7, 27, 8, 0)),
            _msg("DM-AMAZON", "Rs.500 off your next order!", datetime(2026, 7, 27, 9, 0)),
        ])
        assert PendingImport.query.count() == 0


def test_self_transfer_becomes_one_transfer(ledger):
    """RNSB -> HDFC must not post as an expense *and* an income."""
    with ledger.app_context():
        si.scan([_msg("VM-RNSBNK", RNSB_IMPS_OUT, datetime(2026, 7, 24, 12, 0))])

        row = PendingImport.query.one()
        assert row.suggested_type == "transfer"
        assert row.account.name == "RNSB"
        assert row.transfer_account.name == "HDFC Savings"
        assert row.category_id is None, "transfers carry no category"


def test_flags_a_transaction_already_entered_by_hand(ledger):
    with ledger.app_context():
        acct = Account.query.filter_by(name="HDFC Savings").one()
        cat = Category.query.first()
        db.session.add(Transaction(
            date=datetime(2026, 7, 26).date(), amount=D("555"), type="expense",
            account_id=acct.id, category_id=cat.id, payee="Bhatta Foods",
            budget_month=datetime(2026, 7, 1).date()))
        db.session.commit()

        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])
        row = PendingImport.query.one()
        assert row.duplicate_of_id is not None, "should warn about the manual entry"


def test_unmatched_account_still_queues_for_manual_choice(app):
    """An unknown card shouldn't drop the message on the floor."""
    with app.app_context():
        Setting.set(si.WATERMARK_KEY, datetime(2026, 7, 1).isoformat())
        db.session.commit()
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])

        row = PendingImport.query.one()
        assert row.account_id is None
        assert row.status == "pending"


def test_message_without_a_date_falls_back_to_when_it_arrived(ledger):
    with ledger.app_context():
        si.scan([_msg("AX-PLUXEE", PLUXEE_FEE, datetime(2026, 7, 28, 15, 30))])
        assert PendingImport.query.one().txn_date == datetime(2026, 7, 28).date()


def test_nothing_reaches_the_ledger_until_confirmed(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])
        assert Transaction.query.count() == 0, "scanning must never post"


def test_confirm_creates_the_transaction(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0))])
        row = PendingImport.query.one()
        cat = Category.query.first()

        txn = si.confirm(row, category_id=cat.id)

        assert txn.amount == D("738.00")
        assert txn.type == "expense"
        assert txn.payee == "Swiggy Limited"
        assert txn.category_id == cat.id
        assert row.status == "confirmed"
        assert row.transaction_id == txn.id
        assert si.pending_count() == 0


def test_confirm_can_override_what_was_parsed(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_SALARY, datetime(2026, 7, 29, 10, 0))])
        row = PendingImport.query.one()
        rnsb = Account.query.filter_by(name="RNSB").one()

        txn = si.confirm(row, account_id=rnsb.id, payee="Corrected payee")
        assert txn.account_id == rnsb.id
        assert txn.payee == "Corrected payee"


def test_confirm_without_an_account_is_refused(app):
    with app.app_context():
        Setting.set(si.WATERMARK_KEY, datetime(2026, 7, 1).isoformat())
        db.session.commit()
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])
        row = PendingImport.query.one()

        with pytest.raises(ValueError):
            si.confirm(row)
        assert Transaction.query.count() == 0


def test_dismiss_leaves_the_ledger_alone(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])
        row = PendingImport.query.one()
        si.dismiss(row)

        assert row.status == "dismissed"
        assert Transaction.query.count() == 0
        assert si.pending_count() == 0


def test_confirmed_income_is_typed_as_income(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_SALARY, datetime(2026, 7, 29, 10, 0))])
        row = PendingImport.query.one()
        assert row.suggested_type == "income"
        assert si.confirm(row).type == "income"


def test_last_scan_timestamp_updates(ledger):
    with ledger.app_context():
        assert si.last_scan_at() is None
        si.scan([])
        assert si.last_scan_at() is not None


def test_review_page_renders(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])
    html = ledger.test_client().get("/imports/").get_data(as_text=True)
    assert "BHATTA S FOODS PRIVATE" in html
    assert "555" in html


# --- what happens when the accounts aren't registered ----------------------
def test_unmatched_row_records_the_digits_it_saw(app):
    """So the warning can name them instead of sending you to the raw SMS."""
    with app.app_context():
        Setting.set(si.WATERMARK_KEY, datetime(2026, 7, 1).isoformat())
        db.session.commit()
        si.scan([_msg("VM-RNSBNK", RNSB_IMPS_OUT, datetime(2026, 7, 24, 12, 0))])

        row = PendingImport.query.one()
        assert row.account_id is None
        assert row.account_hint == "7655"
        assert row.counterparty_hint == "458"


def test_transfer_degrades_to_expense_when_accounts_are_unknown(app):
    """Documented degradation: without both accounts it cannot be a transfer."""
    with app.app_context():
        Setting.set(si.WATERMARK_KEY, datetime(2026, 7, 1).isoformat())
        db.session.commit()
        si.scan([_msg("VM-RNSBNK", RNSB_IMPS_OUT, datetime(2026, 7, 24, 12, 0))])
        assert PendingImport.query.one().suggested_type == "expense"


def test_transfer_needs_both_sides_registered(app):
    """Only one side known is still not enough to call it a transfer."""
    with app.app_context():
        db.session.add(Account(name="RNSB", type="savings_bank",
                               opening_balance=D("0"), sms_identifiers="7655"))
        Setting.set(si.WATERMARK_KEY, datetime(2026, 7, 1).isoformat())
        db.session.commit()
        si.scan([_msg("VM-RNSBNK", RNSB_IMPS_OUT, datetime(2026, 7, 24, 12, 0))])

        row = PendingImport.query.one()
        assert row.account.name == "RNSB"
        assert row.transfer_account_id is None
        assert row.suggested_type == "expense"
        assert row.counterparty_hint == "458", "still tells you what to register"


def test_unmatched_page_names_the_digits_to_register(app):
    with app.app_context():
        Setting.set(si.WATERMARK_KEY, datetime(2026, 7, 1).isoformat())
        db.session.commit()
        si.scan([_msg("VM-HDFCBK", HDFC_CARD, datetime(2026, 7, 26, 22, 1))])

    html = app.test_client().get("/imports/").get_data(as_text=True)
    assert "8876" in html, "should name the digits the SMS quoted"
    assert "No account registered" in html


# --- category memory -------------------------------------------------------
def test_repeated_payee_preselects_the_category(ledger):
    """The second SMS from a merchant arrives already categorised."""
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0))])
        food = Category.query.filter_by(name="Food").one()
        si.confirm(PendingImport.query.one(), category_id=food.id)

        # A second, identical-merchant message a day later.
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT.replace("01/08/26", "02/08/26"),
                      datetime(2026, 8, 2, 9, 0))])
        row = PendingImport.query.filter_by(status="pending").one()
        assert row.category_id == food.id


def test_payee_match_survives_a_changing_order_reference(ledger):
    """Merchant strings carry refs that differ every time; still one payee."""
    with ledger.app_context():
        food = Category.query.filter_by(name="Food").one()
        db.session.add(PayeeMemory(payee="SWIGGY*ORD123", last_category_id=food.id,
                                   last_type="expense", uses=3))
        db.session.commit()

        assert si.suggest_category("SWIGGY*ORD98765") == food.id
        assert si.suggest_category("Swiggy") == food.id
        assert si.suggest_category("BigBasket") is None


def test_a_short_payee_is_not_matched(ledger):
    """Too few characters to pair on without inventing a link."""
    with ledger.app_context():
        food = Category.query.filter_by(name="Food").one()
        db.session.add(PayeeMemory(payee="AB", last_category_id=food.id,
                                   last_type="expense", uses=9))
        db.session.commit()
        assert si.suggest_category("AB") is None


def test_queued_rows_pick_up_a_category_learned_later(ledger):
    """Categorising one row helps the rows already waiting, not just later scans."""
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0)),
                 _msg("VM-HDFCBK", HDFC_UPI_SENT.replace("01/08/26", "02/08/26"),
                      datetime(2026, 8, 2, 9, 0))])
        rows = si.pending_rows()
        assert len(rows) == 2
        assert all(r.suggested_category_id is None for r in rows)

        food = Category.query.filter_by(name="Food").one()
        si.confirm(rows[0], category_id=food.id)

        still_waiting = si.pending_rows()
        assert [r.suggested_category_id for r in still_waiting] == [food.id]
        assert db.session.get(PendingImport, still_waiting[0].id).category_id is None, \
            "a suggestion is not written to the row"


# --- splitting an imported spend ------------------------------------------
def test_confirm_splits_across_categories(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0))])
        row = PendingImport.query.one()
        food = Category.query.filter_by(name="Food").one()
        misc = Category(name="Misc", kind="expense", icon="📦")
        db.session.add(misc)
        db.session.commit()

        txn = si.confirm(row, splits=[{"category_id": food.id, "amount": D("500")},
                                      {"category_id": misc.id, "amount": D("238")}])

        assert txn.amount == D("738.00")
        assert txn.category_id is None, "the parent holds no category once split"
        assert sorted(c.amount for c in txn.splits) == [D("238.00"), D("500.00")]
        assert {c.category_id for c in txn.splits} == {food.id, misc.id}
        assert all(c.type == "expense" and c.account_id == txn.account_id
                   for c in txn.splits)


def test_splits_must_add_up_to_the_amount_the_bank_stated(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0))])
        row = PendingImport.query.one()
        food = Category.query.filter_by(name="Food").one()

        with pytest.raises(ValueError):
            si.confirm(row, splits=[{"category_id": food.id, "amount": D("100")}])
        assert row.status == "pending"


def test_splits_are_ignored_on_a_non_expense(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_SALARY, datetime(2026, 7, 29, 10, 0))])
        row = PendingImport.query.one()
        food = Category.query.filter_by(name="Food").one()

        txn = si.confirm(row, splits=[{"category_id": food.id, "amount": D("1")}])
        assert txn.type == "income"
        assert txn.splits == []


def test_split_posted_through_the_review_form(ledger):
    with ledger.app_context():
        si.scan([_msg("VM-HDFCBK", HDFC_UPI_SENT, datetime(2026, 8, 1, 9, 0))])
        row_id = PendingImport.query.one().id
        food = Category.query.filter_by(name="Food").one()
        misc = Category(name="Misc", kind="expense", icon="📦")
        db.session.add(misc)
        db.session.commit()
        food_id, misc_id = food.id, misc.id

    ledger.test_client().post(f"/imports/{row_id}/confirm", data={
        "type": "expense",
        "split_category": [str(food_id), str(misc_id), ""],
        "split_amount": ["600", "138", ""],
    })

    with ledger.app_context():
        parent = Transaction.query.filter(Transaction.parent_id.is_(None)).one()
        assert parent.category_id is None
        assert sorted(c.amount for c in parent.splits) == [D("138.00"), D("600.00")]
