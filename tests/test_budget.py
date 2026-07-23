"""Budget aggregation, inline edit, copy-last-month, overshoot alerts."""
from datetime import date
from decimal import Decimal

from app.timeutil import today_ist, month_start, next_month_start, prev_month_start


def _ids(app):
    from app.models import Category, Account
    with app.app_context():
        return {
            "dining": Category.query.filter_by(name="Dining Out").first().id,
            "groceries": Category.query.filter_by(name="Groceries").first().id,
            "acc": Account.query.filter_by(type="savings_bank").first().id,
        }


def test_upsert_and_remove_line(seeded):
    from app.services import budget as B
    from app.models import BudgetLine
    ids = _ids(seeded)
    m = month_start(today_ist())
    with seeded.app_context():
        B.upsert_line(m, ids["groceries"], Decimal("12345"))
        ln = BudgetLine.query.filter_by(budget_month=m, category_id=ids["groceries"]).first()
        assert ln.planned_amount == Decimal("12345.00")
        B.remove_line(m, ids["groceries"])
        assert BudgetLine.query.filter_by(budget_month=m, category_id=ids["groceries"]).first() is None


def test_copy_from_previous_skips_existing(seeded):
    from app.services import budget as B
    from app.models import BudgetLine
    m = month_start(today_ist())
    nxt = next_month_start(m)
    with seeded.app_context():
        before = BudgetLine.query.filter_by(budget_month=nxt).count()
        n = B.copy_from_previous(nxt)     # copies current month -> next
        after = BudgetLine.query.filter_by(budget_month=nxt).count()
        assert after == before + n
        # running again copies nothing new
        assert B.copy_from_previous(nxt) == 0


def test_overshoot_alert_created_and_deduped(seeded):
    from app.services import budget as B
    from app.models import Alert
    ids = _ids(seeded)
    m = month_start(today_ist())
    client = seeded.test_client()
    with seeded.app_context():
        B.upsert_line(m, ids["dining"], Decimal("500"))
    client.post("/transactions/save", data={
        "type": "expense", "date": today_ist().isoformat(), "amount": "3000",
        "account_id": ids["acc"], "category_id": ids["dining"], "payee": "X"})
    client.post("/transactions/save", data={
        "type": "expense", "date": today_ist().isoformat(), "amount": "50",
        "account_id": ids["acc"], "category_id": ids["dining"], "payee": "Y"})
    with seeded.app_context():
        assert Alert.query.filter_by(type="overshoot", is_read=False).count() == 1


def test_income_breakdown(seeded):
    from app.services.budget import compute_income
    m = month_start(today_ist())
    with seeded.app_context():
        inc = compute_income(m)
        assert inc["total_received"] >= Decimal("0")
        assert all("received" in r and "planned" in r for r in inc["rows"])


def test_bar_state_thresholds():
    from app.services.budget import bar_state
    assert bar_state(Decimal("0"), Decimal("100")) == "ok"
    assert bar_state(Decimal("79"), Decimal("100")) == "ok"
    assert bar_state(Decimal("80"), Decimal("100")) == "warn"
    assert bar_state(Decimal("100"), Decimal("100")) == "warn"
    assert bar_state(Decimal("101"), Decimal("100")) == "over"
    assert bar_state(Decimal("10"), Decimal("0")) == "over"   # spent with no plan
