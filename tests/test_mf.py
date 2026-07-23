"""Mutual funds: XIRR, holding valuation, SIP entry. (No network — uses cache.)"""
from datetime import date
from decimal import Decimal


def test_xirr_one_year_10pct():
    from app.services.xirr import xirr
    r = xirr([(date(2025, 7, 15), Decimal("-100000")),
              (date(2026, 7, 15), Decimal("110000"))])
    assert r is not None
    assert abs(r - Decimal("10")) < Decimal("0.1")


def test_xirr_needs_sign_change():
    from app.services.xirr import xirr
    # all outflows -> no solution
    assert xirr([(date(2025, 1, 1), Decimal("-100")),
                 (date(2025, 6, 1), Decimal("-100"))]) is None


def test_holding_metrics_offline(seeded):
    from app.services import mf as MF
    from app.models import MutualFundHolding
    with seeded.app_context():
        h = MutualFundHolding.query.first()
        m = MF.holding_metrics(h)
        # net invested = buys/sips - sells (computed from the holding's own rows)
        bought = sum((t.amount for t in h.transactions if t.type in ("buy", "sip")), Decimal("0"))
        sold = sum((t.amount for t in h.transactions if t.type == "sell"), Decimal("0"))
        assert m["invested"] == (bought - sold).quantize(Decimal("0.01"))
        assert m["units"] > Decimal("0")
        assert m["current_value"] is not None          # seed primes the cache
        assert m["current_value"] == (m["units"] * m["nav"]).quantize(Decimal("0.01"))
        assert m["pl"] == m["current_value"] - m["invested"]


def test_mf_txn_save_computes_units(seeded):
    from app.models import MutualFundHolding, MFTransaction
    client = seeded.test_client()
    with seeded.app_context():
        h = MutualFundHolding.query.first()
        hid = h.id
        n_before = len(h.transactions)
    # amount 5000 at NAV 100 -> 50 units
    r = client.post("/savings/mf/txn/save", data={
        "holding_id": hid, "type": "sip", "date": "2026-07-15",
        "amount": "5000", "nav": "100"})
    assert r.status_code == 204
    with seeded.app_context():
        from app.extensions import db
        h = db.session.get(MutualFundHolding, hid)
        assert len(h.transactions) == n_before + 1
        newest = max(h.transactions, key=lambda t: t.id)
        assert newest.units == Decimal("50.0000")


def test_total_valuation(seeded):
    from app.services import mf as MF
    from app.models import MutualFundHolding
    with seeded.app_context():
        expected = Decimal("0")
        for h in MutualFundHolding.query.all():
            bought = sum((t.amount for t in h.transactions if t.type in ("buy", "sip")), Decimal("0"))
            sold = sum((t.amount for t in h.transactions if t.type == "sell"), Decimal("0"))
            expected += (bought - sold)
        assert MF.total_invested() == expected.quantize(Decimal("0.01"))
        assert MF.total_current_value() > Decimal("0")
