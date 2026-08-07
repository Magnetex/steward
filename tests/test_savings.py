"""Savings transaction type + investment cash-linking.

The core fix: funding an investment now moves real money out of a cash account,
so net worth no longer inflates when you buy. Backfilling a past holding (no
account chosen) still leaves cash untouched.
"""
from decimal import Decimal

import pytest


def _hdfc_id(app):
    from app.models import Account
    return Account.query.filter_by(type="savings_bank").first().id


def _ppfas(app):
    from app.models import MutualFundHolding
    return MutualFundHolding.query.filter(
        MutualFundHolding.scheme_name.ilike("%Parag Parikh%")).first()


# ---------------------------------------------------------------------------
# The savings transaction type
# ---------------------------------------------------------------------------
def test_savings_out_reduces_cash(seeded):
    from app.services import accounts as acc
    from app.services import invest_link
    from app.extensions import db
    from app.timeutil import today_ist
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.account_balance(aid)
        invest_link.sync_cash("mf", 999999, account_id=aid, amount=Decimal("3000"),
                              on=today_ist(), flow="out")
        db.session.commit()
        assert acc.account_balance(aid) == before - Decimal("3000")


def test_savings_in_credits_cash(seeded):
    from app.services import accounts as acc
    from app.services import invest_link
    from app.extensions import db
    from app.timeutil import today_ist
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.account_balance(aid)
        invest_link.sync_cash("gold", 888888, account_id=aid, amount=Decimal("2000"),
                              on=today_ist(), flow="in")
        db.session.commit()
        assert acc.account_balance(aid) == before + Decimal("2000")


# ---------------------------------------------------------------------------
# MF buy/sell through the route
# ---------------------------------------------------------------------------
def test_funded_buy_moves_cash_and_links(seeded):
    from app.services import accounts as acc
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        hid = _ppfas(seeded).id
        before = acc.available_total()

    r = client.post("/savings/mf/txn/save", data={
        "holding_id": hid, "type": "buy", "date": "2026-07-10",
        "amount": "5000", "nav": "80", "units": "62.5", "account_id": aid})
    assert r.status_code == 204

    with seeded.app_context():
        # cash dropped by exactly the buy amount
        assert acc.available_total() == before - Decimal("5000")
        # a linked savings transaction exists
        link = Transaction.query.filter_by(invest_kind="mf").order_by(
            Transaction.id.desc()).first()
        assert link is not None and link.type == "savings" and link.flow == "out"
        assert link.amount == Decimal("5000") and link.account_id == aid


def test_backfill_buy_leaves_cash_untouched(seeded):
    from app.services import accounts as acc
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        hid = _ppfas(seeded).id
        before = acc.available_total()
        links_before = Transaction.query.filter_by(invest_kind="mf").count()

    r = client.post("/savings/mf/txn/save", data={
        "holding_id": hid, "type": "buy", "date": "2020-01-01",
        "amount": "5000", "nav": "60", "units": "83.33"})  # no account_id
    assert r.status_code == 204

    with seeded.app_context():
        assert acc.available_total() == before          # unchanged — backfill
        assert Transaction.query.filter_by(invest_kind="mf").count() == links_before


def test_delete_mf_txn_removes_cash_link(seeded):
    from app.services import accounts as acc
    from app.models import Transaction, MFTransaction
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        hid = _ppfas(seeded).id
        before = acc.available_total()

    client.post("/savings/mf/txn/save", data={
        "holding_id": hid, "type": "buy", "date": "2026-07-10",
        "amount": "5000", "nav": "80", "units": "62.5", "account_id": aid})

    with seeded.app_context():
        link = Transaction.query.filter_by(invest_kind="mf").order_by(
            Transaction.id.desc()).first()
        txn_id = MFTransaction.query.order_by(MFTransaction.id.desc()).first().id

    client.post(f"/savings/mf/txn/{txn_id}/delete")

    with seeded.app_context():
        assert acc.available_total() == before          # cash restored
        assert Transaction.query.filter_by(invest_kind="mf",
                                           invest_ref_id=txn_id).count() == 0


def test_sell_credits_cash(seeded):
    from app.services import accounts as acc
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        hid = _ppfas(seeded).id
        before = acc.available_total()

    r = client.post("/savings/mf/txn/save", data={
        "holding_id": hid, "type": "sell", "date": "2026-07-12",
        "amount": "9000", "nav": "82", "units": "109.75", "account_id": aid})
    assert r.status_code == 204

    with seeded.app_context():
        assert acc.available_total() == before + Decimal("9000")
        link = Transaction.query.filter_by(invest_kind="mf").order_by(
            Transaction.id.desc()).first()
        assert link.type == "savings" and link.flow == "in"


# ---------------------------------------------------------------------------
# Deposits: FD one-shot, RD recurring
# ---------------------------------------------------------------------------
def test_gold_buy_derives_grams_from_amount(seeded):
    """The gold form asks for the rupee amount; grams come from the gold value."""
    from app.models import GoldTransaction
    client = seeded.test_client()
    # No grams sent — the backend must derive them from amount and price.
    r = client.post("/savings/gold/txn/save", data={
        "type": "buy", "date": "2026-07-10", "gst_pct": "0",
        "amount": "5000", "price_per_gram": "10000"})
    assert r.status_code == 204
    with seeded.app_context():
        t = GoldTransaction.query.order_by(GoldTransaction.id.desc()).first()
        assert t.type == "buy"
        assert t.amount == Decimal("5000.00")
        assert t.grams == Decimal("0.5000")        # 5000 / 10000

    # Missing amount is rejected (not silently zero-gram).
    r2 = client.post("/savings/gold/txn/save", data={
        "type": "buy", "price_per_gram": "10000"})
    assert r2.status_code == 200                    # toast error, no 204 create


# ---------------------------------------------------------------------------
# Digital gold is bought GST-inclusive (3%): the bank debits the round figure,
# and part of it is tax rather than metal.
# ---------------------------------------------------------------------------
def test_gold_buy_splits_gst_out_of_the_amount_paid(seeded):
    from app.models import GoldTransaction
    client = seeded.test_client()
    r = client.post("/savings/gold/txn/save", data={
        "type": "buy", "date": "2026-07-10",
        "amount": "5000", "price_per_gram": "10000"})   # no gst_pct -> default 3%
    assert r.status_code == 204
    with seeded.app_context():
        t = GoldTransaction.query.order_by(GoldTransaction.id.desc()).first()
        assert t.amount == Decimal("4854.37"), "gold value is 5000 / 1.03"
        assert t.gst_amount == Decimal("145.63")
        assert t.paid == Decimal("5000.00"), "what the bank actually debited"
        assert t.amount + t.gst_amount == Decimal("5000.00")
        assert t.grams == Decimal("0.4854"), "grams buy the metal, not the tax"


def test_gold_buy_deducts_the_whole_debit_from_cash(seeded):
    """Cash has to match the bank statement, GST included."""
    from app.services import accounts as acc
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.account_balance(aid)

    client.post("/savings/gold/txn/save", data={
        "type": "buy", "date": "2026-07-10", "amount": "5000",
        "price_per_gram": "10000", "account_id": str(aid)})

    with seeded.app_context():
        assert acc.account_balance(aid) == before - Decimal("5000.00")


def test_gold_buy_drops_net_worth_by_exactly_the_gst(seeded):
    """The tax is money genuinely gone — not a neutral asset swap."""
    from app.services import networth as nw
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        # A fixed manual rate, so the valuation can't drift under the test.
        from app.models import Setting
        from app.extensions import db
        Setting.set("gold_manual_rate", "10000")
        db.session.commit()
        before = nw.current_total()

    client.post("/savings/gold/txn/save", data={
        "type": "buy", "date": "2026-07-10", "amount": "5000",
        "price_per_gram": "10000", "account_id": str(aid)})

    with seeded.app_context():
        # cash -5000, gold +4854 (0.4854 g at 10000). Grams are stored at 4dp,
        # as the platforms quote them, so the drop lands on the GST to within
        # a rupee rather than exactly.
        drop = before - nw.current_total()
        assert abs(drop - Decimal("145.63")) <= Decimal("1")


def test_selling_gold_is_not_taxed(seeded):
    from app.models import GoldTransaction
    client = seeded.test_client()
    client.post("/savings/gold/txn/save", data={
        "type": "sell", "date": "2026-07-10",
        "amount": "5000", "price_per_gram": "10000"})
    with seeded.app_context():
        t = GoldTransaction.query.order_by(GoldTransaction.id.desc()).first()
        assert t.type == "sell"
        assert t.gst_amount == Decimal("0.00")
        assert t.amount == Decimal("5000.00"), "the proceeds are the proceeds"
        assert t.grams == Decimal("0.5000")


def test_the_gst_rate_is_editable(seeded):
    """It's 3% today; the field carries the rate rather than assuming it."""
    from app.models import GoldTransaction
    client = seeded.test_client()
    client.post("/savings/gold/txn/save", data={
        "type": "buy", "date": "2026-07-10", "gst_pct": "5",
        "amount": "5250", "price_per_gram": "10000"})
    with seeded.app_context():
        t = GoldTransaction.query.order_by(GoldTransaction.id.desc()).first()
        assert t.amount == Decimal("5000.00")       # 5250 / 1.05
        assert t.gst_amount == Decimal("250.00")


def test_gold_summary_separates_what_was_paid_from_what_was_bought(seeded):
    """Average price is the metal's; P/L is measured against the whole debit."""
    from app.services import gold as gold_svc
    from app.models import GoldHolding, GoldTransaction
    from app.extensions import db
    client = seeded.test_client()
    with seeded.app_context():
        for t in GoldTransaction.query.all():       # start from a clean holding
            db.session.delete(t)
        for h in GoldHolding.query.all():
            db.session.delete(h)
        db.session.commit()

    client.post("/savings/gold/txn/save", data={
        "type": "buy", "date": "2026-07-10",
        "amount": "5000", "price_per_gram": "10000"})

    with seeded.app_context():
        s = gold_svc.summary()
        assert s["gst"] == Decimal("145.63")
        assert s["invested"] == Decimal("5000.00"), "what left the bank"
        assert s["grams"] == Decimal("0.4854")
        # The metal's own rate, not 5000/0.4854 — which would be the 10,300 the
        # tax makes it look like. Within a rupee, since grams are stored at 4dp.
        assert abs(s["avg_price"] - Decimal("10000")) <= Decimal("1")


def test_fd_deducts_principal_once(seeded):
    from app.services import accounts as acc
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.available_total()

    client.post("/savings/deposit/save", data={
        "kind": "FD", "bank": "Axis", "principal": "50000", "interest_rate": "7",
        "compounding": "quarterly", "start_date": "2026-07-01", "tenure_months": "12",
        "account_id": aid})

    with seeded.app_context():
        assert acc.available_total() == before - Decimal("50000")
        links = Transaction.query.filter_by(invest_kind="deposit").all()
        assert len(links) == 1 and links[0].amount == Decimal("50000")


def test_rd_no_rule_backfill_asset_only(seeded):
    """RD is NOT a recurring rule, and past installments don't touch cash."""
    from app.services import accounts as acc
    from app.models import RecurringRule, Transaction, Deposit
    from app.timeutil import today_ist
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.available_total()

    # Start the RD three months ago so a few installments are already "due".
    start = today_ist().replace(day=1)
    y, m = start.year, start.month - 3
    while m <= 0:
        m += 12; y -= 1
    start = start.replace(year=y, month=m)

    client.post("/savings/deposit/save", data={
        "kind": "RD", "bank": "Kotak", "installment": "4000", "interest_rate": "6.5",
        "compounding": "quarterly", "start_date": start.isoformat(),
        "tenure_months": "24", "account_id": aid})

    with seeded.app_context():
        dep = Deposit.query.filter_by(bank="Kotak").first()
        # no recurring rule created (RDs stay off the Recurring page)
        assert RecurringRule.query.filter_by(invest_kind="deposit",
                                             invest_ref_id=dep.id).count() == 0
        # backfill is asset-only: no cash installments, cash untouched
        assert Transaction.query.filter_by(invest_kind="deposit",
                                           invest_ref_id=dep.id).count() == 0
        assert acc.available_total() == before
        # the plan is armed for a future installment
        assert dep.account_id == aid
        assert dep.next_run_date is not None and dep.next_run_date > today_ist()


def test_rd_future_run_deducts_cash_and_stops_at_maturity(seeded):
    from app.services import accounts as acc
    from app.services import rd as rd_svc
    from app.models import Transaction, Deposit
    from app.timeutil import today_ist, add_months
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)

    # RD starting this month, 3-month tenure -> installments at months 0,1,2.
    start = today_ist().replace(day=1)
    client.post("/savings/deposit/save", data={
        "kind": "RD", "bank": "Canara", "installment": "3000", "interest_rate": "6",
        "compounding": "quarterly", "start_date": start.isoformat(),
        "tenure_months": "3", "account_id": aid})

    with seeded.app_context():
        dep = Deposit.query.filter_by(bank="Canara").first()
        before = acc.account_balance(aid)
        # run a year out: only the 2 future installments (months 1,2) fire; the
        # month-0 installment was asset-only backfill. (The seeded SBI RD also
        # fires, so assert on Canara's own installments, not the whole balance.)
        rd_svc.run_due(as_of=add_months(start, 12))
        canara = Transaction.query.filter_by(
            invest_kind="deposit", invest_ref_id=dep.id, type="savings").all()
        assert len(canara) == 2
        assert sum((t.amount for t in canara), Decimal("0")) == Decimal("6000")  # 2 × 3000
        assert acc.account_balance(aid) <= before - Decimal("6000")   # cash moved out
        # matured -> nothing left to run for Canara (and everything else caught up)
        dep = Deposit.query.filter_by(bank="Canara").first()
        assert dep.next_run_date is None
        assert rd_svc.run_due(as_of=add_months(start, 24)) == 0


def test_recurring_page_excludes_savings(seeded):
    """A savings-type rule never shows on the Recurring page."""
    from app.extensions import db
    from app.models import RecurringRule
    from app.timeutil import today_ist
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        db.session.add(RecurringRule(
            payee="ZZZ Legacy RD", amount=Decimal("1000"), type="savings",
            account_id=aid, frequency="monthly", next_due_date=today_ist(),
            invest_kind="deposit", invest_ref_id=99999, active=True))
        db.session.commit()
    body = seeded.test_client().get("/recurring/").get_data(as_text=True)
    assert "ZZZ Legacy RD" not in body


# ---------------------------------------------------------------------------
# Budget savings section
# ---------------------------------------------------------------------------
def test_budget_savings_aggregation(seeded):
    from app.services import budget as bud
    from app.services import invest_link
    from app.extensions import db
    from app.timeutil import today_ist, month_start
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        cat_id = invest_link.savings_category_id("gold")
        month = month_start(today_ist())
        t = invest_link.sync_cash("gold", 777777, account_id=aid,
                                  amount=Decimal("2500"), on=today_ist(), flow="out")
        db.session.commit()
        saved = bud.savings_saved_by_category(month)
        assert saved.get(cat_id) == Decimal("2500")
        data = bud.compute_savings(month)
        assert any(r["category"].id == cat_id and r["saved"] == Decimal("2500")
                   for r in data["rows"])


# ---------------------------------------------------------------------------
# EPF & Stock tabs now link to their savings categories too
# ---------------------------------------------------------------------------
def test_epf_paid_from_links_cash(seeded):
    from app.services import accounts as acc
    from app.services import invest_link
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.account_balance(aid)
        epf_cat = invest_link.savings_category_id("epf")

    r = client.post("/savings/epf/entry/save", data={
        "month": "2026-06", "employee_share": "1800", "employer_share": "550",
        "account_id": aid})
    assert r.status_code == 204

    with seeded.app_context():
        # only the employee share leaves cash
        assert acc.account_balance(aid) == before - Decimal("1800")
        link = Transaction.query.filter_by(invest_kind="epf").order_by(
            Transaction.id.desc()).first()
        assert link is not None and link.type == "savings" and link.flow == "out"
        assert link.amount == Decimal("1800") and link.category_id == epf_cat


def test_stock_paid_from_links_cash_in_inr(seeded):
    from app.services import accounts as acc
    from app.services import invest_link, market
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        before = acc.account_balance(aid)
        stock_cat = invest_link.savings_category_id("stock")
        rate = market.usdinr()
    expected = (Decimal("2") * Decimal("100") * rate).quantize(Decimal("0.01"))

    r = client.post("/savings/stock/save", data={
        "ticker": "AAPL", "name": "Apple", "date": "2026-07-01",
        "qty": "2", "price_usd": "100", "account_id": aid})
    assert r.status_code == 204

    with seeded.app_context():
        link = Transaction.query.filter_by(invest_kind="stock").order_by(
            Transaction.id.desc()).first()
        assert link is not None and link.type == "savings" and link.flow == "out"
        assert link.amount == expected and link.category_id == stock_cat
        assert acc.account_balance(aid) == before - expected


def test_stock_backfill_no_account_untouched(seeded):
    from app.services import accounts as acc
    from app.models import Transaction
    client = seeded.test_client()
    with seeded.app_context():
        before = acc.available_total()
        links_before = Transaction.query.filter_by(invest_kind="stock").count()
    client.post("/savings/stock/save", data={
        "ticker": "MSFT", "date": "2020-01-01", "qty": "1", "price_usd": "150"})
    with seeded.app_context():
        assert acc.available_total() == before
        assert Transaction.query.filter_by(invest_kind="stock").count() == links_before


# ---------------------------------------------------------------------------
# Savings categories are fixed (five, one per tab)
# ---------------------------------------------------------------------------
def test_five_static_savings_categories(seeded):
    from app.models import Category
    from app.services.invest_link import SAVINGS_CATEGORY_NAMES
    client = seeded.test_client()
    assert client.get("/categories/").status_code == 200
    with seeded.app_context():
        names = {c.name for c in Category.query.filter_by(kind="savings").all()}
        assert SAVINGS_CATEGORY_NAMES <= names
        assert {"Mutual Funds", "Gold", "Deposits", "EPF", "Stocks"} <= names


def test_cannot_add_savings_category(seeded):
    from app.models import Category
    client = seeded.test_client()
    with seeded.app_context():
        before = Category.query.filter_by(kind="savings").count()
    client.post("/categories/save", data={"name": "PPF", "kind": "savings", "icon": "🏦"})
    with seeded.app_context():
        assert Category.query.filter_by(kind="savings").count() == before
        assert Category.query.filter_by(name="PPF").first() is None


def test_cannot_delete_locked_savings_category(seeded):
    from app.extensions import db
    from app.models import Category
    client = seeded.test_client()
    with seeded.app_context():
        cid = Category.query.filter_by(kind="savings", name="Gold").first().id
    client.post(f"/categories/{cid}/delete")
    with seeded.app_context():
        assert db.session.get(Category, cid) is not None
