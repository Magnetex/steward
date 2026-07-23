"""Exact money math: formatting, Decimal storage, balances, splits, salary rule."""
from datetime import date
from decimal import Decimal

from app.money import money, fmt_inr, to_decimal, DecimalText  # noqa: F401
from app.timeutil import month_start, next_month_start


def test_indian_number_grouping():
    assert fmt_inr(Decimal("235163")) == "₹2,35,163.00"
    assert fmt_inr(Decimal("1234567.89")) == "₹12,34,567.89"
    assert fmt_inr(Decimal("100")) == "₹100.00"
    assert fmt_inr(Decimal("-2500.5")) == "-₹2,500.50"
    assert fmt_inr(Decimal("235163"), paise=False) == "₹2,35,163"


def test_money_quantize_half_up():
    assert money("10.005") == Decimal("10.01")
    assert money("10.004") == Decimal("10.00")
    assert money(None) == Decimal("0.00")
    assert money("1,234.5") == Decimal("1234.50")


def test_decimal_text_roundtrip(app):
    """Values persist as exact Decimals (no float drift)."""
    from app.extensions import db
    from app.models import Account
    with app.app_context():
        a = Account(name="X", type="cash", opening_balance=Decimal("0.1"))
        db.session.add(a)
        db.session.commit()
        got = db.session.get(Account, a.id).opening_balance
        assert got == Decimal("0.1")
        assert isinstance(got, Decimal)


def test_account_balance_with_transfers(app):
    from app.extensions import db
    from app.models import Account, Transaction
    from app.services.accounts import account_balance
    with app.app_context():
        a = Account(name="A", type="savings_bank", opening_balance=Decimal("1000"))
        b = Account(name="B", type="wallet", opening_balance=Decimal("0"))
        db.session.add_all([a, b])
        db.session.flush()
        m = month_start(date(2026, 7, 1))
        db.session.add(Transaction(date=date(2026, 7, 2), amount=Decimal("200"),
                                   type="expense", account_id=a.id, budget_month=m))
        db.session.add(Transaction(date=date(2026, 7, 3), amount=Decimal("300"),
                                   type="transfer", account_id=a.id,
                                   transfer_account_id=b.id, budget_month=m))
        db.session.add(Transaction(date=date(2026, 7, 4), amount=Decimal("50"),
                                   type="income", account_id=a.id, budget_month=m))
        db.session.commit()
        assert account_balance(a.id) == Decimal("550.00")   # 1000 -200 -300 +50
        assert account_balance(b.id) == Decimal("300.00")   # +300 transfer in


def test_salary_rule_shifts_late_income():
    # 7-day window. July has 31 days; income on the 26th (>=25) -> August.
    assert next_month_start(date(2026, 7, 26)) == date(2026, 8, 1)
    from app.services.settings import DEFAULTS
    assert DEFAULTS["salary_rule_window"] == "7"


def test_default_budget_month(seeded):
    from app.services.budget import default_budget_month
    with seeded.app_context():
        # income on the 26th of July -> August budget
        assert default_budget_month(date(2026, 7, 26), "income") == date(2026, 8, 1)
        # income on the 10th -> July budget
        assert default_budget_month(date(2026, 7, 10), "income") == date(2026, 7, 1)
        # expense late in month stays in July
        assert default_budget_month(date(2026, 7, 28), "expense") == date(2026, 7, 1)


def test_split_must_sum_to_total(app):
    from app.services import transactions as tx
    from app.extensions import db
    from app.models import Account, Category
    from werkzeug.datastructures import MultiDict
    with app.app_context():
        acc = Account(name="A", type="cash", opening_balance=Decimal("0"))
        c1 = Category(name="G", kind="expense")
        c2 = Category(name="P", kind="expense")
        db.session.add_all([acc, c1, c2])
        db.session.commit()
        form = MultiDict([
            ("type", "expense"), ("date", "2026-07-10"), ("amount", "300"),
            ("account_id", str(acc.id)),
            ("split_category", str(c1.id)), ("split_amount", "100"),
            ("split_category", str(c2.id)), ("split_amount", "200"),
        ])
        t = tx.create(form)
        assert len(t.splits) == 2
        assert t.category_id is None
        assert sum(s.amount for s in t.splits) == Decimal("300.00")

        bad = MultiDict([
            ("type", "expense"), ("date", "2026-07-10"), ("amount", "300"),
            ("account_id", str(acc.id)),
            ("split_category", str(c1.id)), ("split_amount", "100"),
        ])
        try:
            tx.create(bad)
            assert False, "expected TxnError"
        except tx.TxnError:
            pass


def test_budget_aggregation_with_splits(seeded):
    from app.services.budget import compute_budget, category_spent
    from app.timeutil import today_ist, month_start
    with seeded.app_context():
        m = month_start(today_ist())
        b = compute_budget(m)
        # totals are Decimals and remaining == planned - spent
        assert b["total_remaining"] == b["total_planned"] - b["total_spent"]
        spent = category_spent(m)
        assert all(isinstance(v, Decimal) for v in spent.values())
