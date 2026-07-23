"""FIFO capital gains, term classification, exemptions, and 80C."""
from datetime import date
from decimal import Decimal

from app.timeutil import today_ist


def test_fifo_lot_matching_and_terms(seeded):
    from app.services.tax import capital_gains
    with seeded.app_context():
        g = capital_gains(today_ist())
        events = g["events"]
        assert len(events) >= 2
        mf = [e for e in events if e["asset"] == "MF"][0]
        # 400 units @ (80.50 - 64.20) = 6520, held 13 months -> long
        assert mf["gain"] == Decimal("6520.00")
        assert mf["term"] == "long"
        assert mf["bucket"] == "equity_ltcg"
        gold = [e for e in events if e["asset"] == "Gold"][0]
        assert gold["gain"] == Decimal("1650.00")
        assert gold["bucket"] == "gold_slab"


def test_equity_ltcg_exemption_applied(seeded):
    from app.services.tax import capital_gains
    with seeded.app_context():
        g = capital_gains(today_ist())
        b = g["buckets"]["equity_ltcg"]
        assert b["gain"] == Decimal("6520.00")
        assert b["taxable"] == Decimal("0.00")   # below 1.25L exemption
        assert b["tax"] == Decimal("0.00")


def test_gold_slab_tax(seeded):
    from app.services.tax import capital_gains
    with seeded.app_context():
        g = capital_gains(today_ist())
        b = g["buckets"]["gold_slab"]
        assert b["taxable"] == Decimal("1650.00")
        assert b["tax"] == Decimal("495.00")      # 30% of 1650


def test_80c_aggregation(seeded):
    from app.services.tax import sec_80c
    with seeded.app_context():
        c = sec_80c(today_ist())
        assert c["epf"] > Decimal("0")
        assert c["tagged"] == Decimal("37500.00")  # 3 ELSS SIPs x 12500
        assert c["used"] == c["epf"] + c["tagged"]
        assert c["limit"] == Decimal("150000.00")
        assert 0 <= c["pct"] <= 100


def test_fifo_partial_lot(app):
    """FIFO logic: a sell spanning two lots splits into two gain events."""
    from app.services import tax
    from app.extensions import db
    from app.models import MutualFundHolding, MFTransaction
    with app.app_context():
        h = MutualFundHolding(scheme_code="X", scheme_name="X", asset_type="equity")
        db.session.add(h); db.session.flush()
        db.session.add_all([
            MFTransaction(holding_id=h.id, date=date(2024, 1, 1), type="buy", units=Decimal("100"), nav=Decimal("10"), amount=Decimal("1000")),
            MFTransaction(holding_id=h.id, date=date(2024, 6, 1), type="buy", units=Decimal("100"), nav=Decimal("20"), amount=Decimal("2000")),
            MFTransaction(holding_id=h.id, date=date(2026, 1, 1), type="sell", units=Decimal("150"), nav=Decimal("30"), amount=Decimal("4500")),
        ])
        db.session.commit()
        events = tax._mf_events()
        # 100 units from lot1 (gain 100*(30-10)=2000) + 50 from lot2 (50*(30-20)=500)
        assert len(events) == 2
        assert events[0]["gain"] == Decimal("2000.00")
        assert events[1]["gain"] == Decimal("500.00")
