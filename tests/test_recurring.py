"""Recurring engine: materialization, scheduling math, reminders, Record it."""
from datetime import date, timedelta
from decimal import Decimal


def _make_rule(app, **kw):
    from app.extensions import db
    from app.models import RecurringRule, Account, Category
    with app.app_context():
        acc = Account.query.first() or Account(name="A", type="cash")
        cat = Category.query.filter_by(kind="expense").first()
        if acc.id is None:
            db.session.add(acc); db.session.commit()
        defaults = dict(payee="Netflix", amount=Decimal("649"), type="expense",
                        category_id=cat.id if cat else None, account_id=acc.id,
                        frequency="monthly", day_of_month=6, mode="auto_create",
                        next_due_date=date(2026, 6, 6), active=True)
        defaults.update(kw)
        r = RecurringRule(**defaults)
        db.session.add(r)
        db.session.commit()
        return r.id


def test_next_after_schedules():
    from app.services.recurring import next_after
    from app.models import RecurringRule
    r = RecurringRule(frequency="monthly", day_of_month=6)
    assert next_after(r, date(2026, 6, 6)) == date(2026, 7, 6)
    r2 = RecurringRule(frequency="weekly")
    assert next_after(r2, date(2026, 6, 6)) == date(2026, 6, 13)
    r3 = RecurringRule(frequency="yearly", month_of_year=4, day_of_month=15)
    assert next_after(r3, date(2026, 4, 15)) == date(2027, 4, 15)
    # month-end clamp: day 31 in a 30-day month
    r4 = RecurringRule(frequency="monthly", day_of_month=31)
    assert next_after(r4, date(2026, 8, 31)) == date(2026, 9, 30)


def test_auto_create_materializes_and_advances(seeded):
    from app.services.recurring import materialize_due
    from app.models import Transaction, RecurringRule
    rid = _make_rule(seeded, next_due_date=date(2026, 6, 6), mode="auto_create")
    with seeded.app_context():
        before = Transaction.query.filter(Transaction.parent_id.is_(None)).count()
    materialize_due(as_of=date(2026, 7, 15))  # Jun 6 and Jul 6 are due -> 2 txns
    with seeded.app_context():
        after = Transaction.query.filter(Transaction.parent_id.is_(None)).count()
        from app.extensions import db
        rule = db.session.get(RecurringRule, rid)
        assert after == before + 2
        assert rule.next_due_date > date(2026, 7, 15)
        # created transactions are tagged 'recurring'
        recs = Transaction.query.filter(Transaction.tags.ilike("%recurring%")).all()
        assert len(recs) >= 2


def test_remind_only_creates_alert_not_txn(seeded):
    from app.services.recurring import materialize_due
    from app.models import Transaction, Alert
    _make_rule(seeded, payee="Electricity", mode="remind_only",
               next_due_date=date(2026, 7, 10))
    with seeded.app_context():
        before = Transaction.query.count()
    materialize_due(as_of=date(2026, 7, 15))
    with seeded.app_context():
        assert Transaction.query.count() == before  # no txn
        assert Alert.query.filter_by(type="recurring", action="record").count() >= 1


def test_record_it_endpoint(seeded):
    from app.models import Transaction, RecurringRule
    rid = _make_rule(seeded, payee="Water bill", mode="remind_only",
                     next_due_date=date(2026, 7, 10))
    client = seeded.test_client()
    with seeded.app_context():
        before = Transaction.query.filter(Transaction.parent_id.is_(None)).count()
    r = client.post(f"/recurring/record/{rid}")
    assert r.status_code == 200
    with seeded.app_context():
        after = Transaction.query.filter(Transaction.parent_id.is_(None)).count()
        assert after == before + 1


def test_upcoming_window(seeded):
    from app.services.recurring import upcoming
    _make_rule(seeded, payee="Soon", next_due_date=date(2026, 7, 20))
    _make_rule(seeded, payee="Later", next_due_date=date(2026, 9, 1))
    with seeded.app_context():
        rows = upcoming(days=14, as_of=date(2026, 7, 15))
        payees = [r.payee for r in rows]
        assert "Soon" in payees
        assert "Later" not in payees
