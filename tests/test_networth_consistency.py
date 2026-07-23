"""The dashboard and /networth/ must never disagree about net worth.

They used to: the dashboard printed the most recent NetWorthSnapshot while
/networth/ valued the buckets live, so the two drifted apart with every
transaction and read zero on a database with no snapshots.
"""
from decimal import Decimal


def _dashboard_networth(app):
    from app.blueprints.dashboard import _summary_context
    with app.app_context():
        return _summary_context()["networth"]


def _page_networth(app):
    from app.services import networth as nw
    from app.money import money, ZERO
    with app.app_context():
        return money(sum(nw.current_buckets().values(), ZERO))


def test_dashboard_matches_networth_page(seeded):
    assert _dashboard_networth(seeded) == _page_networth(seeded)


def test_agrees_with_no_snapshots_at_all(seeded):
    """A fresh database has no snapshots; the dashboard must still be right."""
    from app.models import NetWorthSnapshot
    from app.extensions import db
    with seeded.app_context():
        NetWorthSnapshot.query.delete()
        db.session.commit()

    live = _page_networth(seeded)
    assert live > 0, "seed data should have non-zero net worth"
    assert _dashboard_networth(seeded) == live


def test_stays_in_step_after_a_transaction(seeded):
    """A spend recorded after the last snapshot must move both numbers."""
    from app.models import Account, Category, Transaction
    from app.extensions import db
    from app.services import networth as nw
    from app.timeutil import today_ist

    with seeded.app_context():
        nw.take_snapshot()  # snapshot first, then spend
        before = _summary_networth(seeded)
        acc = Account.query.filter_by(type="savings_bank").first()
        cat = Category.query.filter_by(kind="expense").first()
        db.session.add(Transaction(
            date=today_ist(), amount=Decimal("2500"), type="expense",
            account_id=acc.id, category_id=cat.id, payee="Test",
            budget_month=today_ist().replace(day=1),
        ))
        db.session.commit()

    assert _dashboard_networth(seeded) == _page_networth(seeded)
    assert _dashboard_networth(seeded) == before - Decimal("2500")


def _summary_networth(app):
    from app.blueprints.dashboard import _summary_context
    return _summary_context()["networth"]


def test_sparkline_ends_on_the_live_total(seeded):
    """The chart's last point must equal the figure printed above it."""
    from app.blueprints.dashboard import _summary_context
    with seeded.app_context():
        ctx = _summary_context()
    assert ctx["spark"], "sparkline should never be empty"
    assert Decimal(str(ctx["spark"][-1])) == ctx["networth"]
