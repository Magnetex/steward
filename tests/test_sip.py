"""SIP plans: backfill (asset-only), annual step-up, future run (units + cash)."""
from datetime import date
from decimal import Decimal

import pytest


def _hdfc_id(app):
    from app.models import Account
    return Account.query.filter_by(type="savings_bank").first().id


def _holding(app):
    from app.models import MutualFundHolding
    return MutualFundHolding.query.order_by(MutualFundHolding.id).first()


@pytest.fixture
def flat_nav(monkeypatch):
    """Force a deterministic NAV of 50 for every date (no network)."""
    from app.services import mf as mf_svc
    monkeypatch.setattr(mf_svc, "nav_history",
                        lambda code: [(date(2000, 1, 1), Decimal("50"))])
    return Decimal("50")


# ---------------------------------------------------------------------------
# Step-up amount (pure function)
# ---------------------------------------------------------------------------
def test_step_up_amount_annual():
    from app.services import sip
    from app.models import SIPPlan
    plan = SIPPlan(amount=Decimal("5000"), start_date=date(2024, 1, 1),
                   step_up_pct=Decimal("10"))
    assert sip.stepped_amount(plan, date(2024, 6, 1)) == Decimal("5000.00")   # yr 0
    assert sip.stepped_amount(plan, date(2025, 2, 1)) == Decimal("5500.00")   # yr 1: +10%
    assert sip.stepped_amount(plan, date(2026, 2, 1)) == Decimal("6050.00")   # yr 2: +10% again


def test_no_step_up_keeps_base():
    from app.services import sip
    from app.models import SIPPlan
    plan = SIPPlan(amount=Decimal("3000"), start_date=date(2024, 1, 1),
                   step_up_pct=Decimal("0"))
    assert sip.stepped_amount(plan, date(2030, 1, 1)) == Decimal("3000.00")


# ---------------------------------------------------------------------------
# Backfill: one installment per past month, asset-only (no cash movement)
# ---------------------------------------------------------------------------
def test_backfill_creates_monthly_installments_asset_only(seeded, flat_nav):
    from app.services import sip
    from app.services import accounts as acc
    from app.extensions import db
    from app.models import MFTransaction, Transaction
    from app.timeutil import today_ist, add_months
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        hid = _holding(seeded).id
        cash_before = acc.account_balance(aid)

        start = today_ist().replace(day=1)
        # three whole months ago
        y, m = start.year, start.month - 3
        while m <= 0:
            m += 12; y -= 1
        start = start.replace(year=y, month=m)

        plan, summary = sip.create_plan(holding_id=hid, amount=Decimal("5000"),
                                        start_date=start, step_up_pct=Decimal("0"),
                                        account_id=aid)
        db.session.commit()

        # expected number of monthly installments from start..today inclusive
        expected = 0
        d = start
        while d <= today_ist():
            expected += 1
            d = add_months(d, 1)

        made = MFTransaction.query.filter_by(sip_plan_id=plan.id).count()
        assert made == expected == summary["count"]
        # units priced at NAV 50: 5000 / 50 = 100 units each
        first = MFTransaction.query.filter_by(sip_plan_id=plan.id).first()
        assert first.units == Decimal("100.0000") and first.type == "sip"

        # asset-only: no linked cash transactions, cash untouched
        assert Transaction.query.filter_by(invest_kind="mf").filter(
            Transaction.note.ilike("SIP%")).count() == 0
        assert acc.account_balance(aid) == cash_before
        # next run is in the future
        assert plan.next_run_date > today_ist()


# ---------------------------------------------------------------------------
# Future run: buys units AND debits cash (net-worth neutral)
# ---------------------------------------------------------------------------
def test_future_run_deducts_cash(seeded, flat_nav):
    from app.services import sip
    from app.services import accounts as acc
    from app.extensions import db
    from app.models import MFTransaction, Transaction
    from app.timeutil import today_ist, add_months
    with seeded.app_context():
        aid = _hdfc_id(seeded)
        hid = _holding(seeded).id
        start = today_ist().replace(day=1)

        plan, _ = sip.create_plan(holding_id=hid, amount=Decimal("4000"),
                                  start_date=start, account_id=aid)
        db.session.commit()
        cash_after_backfill = acc.account_balance(aid)
        made_before = MFTransaction.query.filter_by(sip_plan_id=plan.id).count()

        # advance a month and run the scheduler path
        nxt = add_months(start, 1)
        touched = sip.run_due(as_of=nxt)
        assert touched == 1

        made_after = MFTransaction.query.filter_by(sip_plan_id=plan.id).count()
        assert made_after == made_before + 1
        # a linked cash-out savings txn now exists and cash dropped by 4000
        link = Transaction.query.filter_by(invest_kind="mf", type="savings").order_by(
            Transaction.id.desc()).first()
        assert link is not None and link.flow == "out" and link.amount == Decimal("4000")
        assert acc.account_balance(aid) == cash_after_backfill - Decimal("4000")


# ---------------------------------------------------------------------------
# Stop / delete keep the invested history
# ---------------------------------------------------------------------------
def test_stop_plan_halts_future_runs(seeded, flat_nav):
    from app.services import sip
    from app.extensions import db
    from app.models import MFTransaction
    from app.timeutil import today_ist, add_months
    with seeded.app_context():
        hid = _holding(seeded).id
        start = today_ist().replace(day=1)
        plan, _ = sip.create_plan(holding_id=hid, amount=Decimal("2000"), start_date=start)
        sip.stop_plan(plan)
        db.session.commit()
        made = MFTransaction.query.filter_by(sip_plan_id=plan.id).count()
        # running due does nothing for a stopped plan
        sip.run_due(as_of=add_months(start, 2))
        assert MFTransaction.query.filter_by(sip_plan_id=plan.id).count() == made
        assert plan.active is False


def test_delete_plan_keeps_past_txns(seeded, flat_nav):
    from app.services import sip
    from app.extensions import db
    from app.models import MFTransaction, SIPPlan
    from app.timeutil import today_ist
    with seeded.app_context():
        hid = _holding(seeded).id
        start = today_ist().replace(day=1)
        plan, _ = sip.create_plan(holding_id=hid, amount=Decimal("2000"), start_date=start)
        db.session.commit()
        pid = plan.id
        made = MFTransaction.query.filter_by(sip_plan_id=pid).count()
        assert made >= 1
        sip.delete_plan(plan)
        db.session.commit()
        assert db.session.get(SIPPlan, pid) is None
        # the installments survive, just detached from the (gone) plan
        assert MFTransaction.query.filter_by(sip_plan_id=pid).count() == 0
        assert MFTransaction.query.filter_by(sip_plan_id=None).count() >= made
