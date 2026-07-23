"""Reports aggregation + net-worth snapshot."""
from datetime import date
from decimal import Decimal

from app.timeutil import today_ist, month_start


def test_spending_by_category_sorted(seeded):
    from app.services.reports import spending_by_category
    with seeded.app_context():
        rows = spending_by_category(month_start(today_ist()))
        assert rows
        amounts = [r["amount"] for r in rows]
        assert amounts == sorted(amounts, reverse=True)
        assert all(isinstance(r["amount"], Decimal) for r in rows)


def test_income_expense_trend_12_months(seeded):
    from app.services.reports import income_expense_trend
    with seeded.app_context():
        t = income_expense_trend(month_start(today_ist()), 12)
        assert len(t["labels"]) == 12
        assert len(t["income"]) == 12
        assert len(t["expense"]) == 12


def test_top_payees(seeded):
    from app.services.reports import top_payees
    with seeded.app_context():
        rows = top_payees(month_start(today_ist()))
        assert rows
        # Landlord (rent 25000) should top the list
        assert rows[0]["payee"] == "Landlord"
        assert rows[0]["amount"] == Decimal("25000.00")


def test_month_over_month(seeded):
    from app.services.reports import month_over_month
    with seeded.app_context():
        mom = month_over_month(month_start(today_ist()))
        assert "rows" in mom and mom["rows"]
        for r in mom["rows"]:
            assert "this" in r and "prev" in r


def test_snapshot_creates_row(seeded):
    from app.services.networth import take_snapshot, current_total
    from app.models import NetWorthSnapshot
    with seeded.app_context():
        n_before = NetWorthSnapshot.query.count()
        snap = take_snapshot()
        # snapshot for today overwrites if present; total matches live buckets
        assert snap.total == current_total()
        assert NetWorthSnapshot.query.count() >= n_before
