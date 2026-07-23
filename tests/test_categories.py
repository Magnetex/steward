"""Category CRUD (+ usage guard) and unbudgeted-spending aggregation."""
from datetime import date
from decimal import Decimal

from app.timeutil import today_ist, month_start


def test_category_page_and_create(seeded):
    client = seeded.test_client()
    assert client.get("/categories/").status_code == 200
    from app.models import Category
    with seeded.app_context():
        n = Category.query.count()
    client.post("/categories/save", data={"name": "Pets", "kind": "expense",
                                          "icon": "🐾", "group": "Lifestyle"})
    with seeded.app_context():
        assert Category.query.count() == n + 1
        c = Category.query.filter_by(name="Pets").first()
        assert c.kind == "expense" and c.group == "Lifestyle"


def test_category_archive_and_hidden_from_new_use(seeded):
    from app.models import Category
    client = seeded.test_client()
    with seeded.app_context():
        c = Category.query.filter_by(name="Personal").first()
        cid = c.id
    client.post(f"/categories/{cid}/archive")
    with seeded.app_context():
        from app.extensions import db
        assert db.session.get(Category, cid).is_archived is True
        # archived categories don't appear in the add-transaction form lists
        exp = Category.query.filter_by(kind="expense", is_archived=False).all()
        assert cid not in [x.id for x in exp]


def test_delete_guard_blocks_used_category(seeded):
    from app.models import Category, Transaction
    client = seeded.test_client()
    with seeded.app_context():
        used = Category.query.filter_by(name="Rent").first()  # rent has transactions
        used_id = used.id
        n = Category.query.count()
    r = client.post(f"/categories/{used_id}/delete", follow_redirects=True)
    with seeded.app_context():
        assert Category.query.count() == n  # not deleted
        from app.extensions import db
        assert db.session.get(Category, used_id) is not None


def test_delete_unused_category(seeded):
    from app.models import Category
    client = seeded.test_client()
    client.post("/categories/save", data={"name": "Temp", "kind": "expense", "icon": "🧪"})
    with seeded.app_context():
        c = Category.query.filter_by(name="Temp").first()
        cid = c.id
        n = Category.query.count()
    client.post(f"/categories/{cid}/delete")
    with seeded.app_context():
        assert Category.query.count() == n - 1


def test_spending_without_budget_line_is_unbudgeted(seeded):
    """An expense in a category with no line lands in 'Unbudgeted', not a row."""
    from app.services.budget import compute_budget, upsert_line, remove_line
    from app.models import Category, Account
    from app.services import transactions as tx
    from werkzeug.datastructures import MultiDict
    m = month_start(today_ist())
    with seeded.app_context():
        misc = Category.query.filter_by(name="Miscellaneous").first()
        acc = Account.query.filter_by(type="savings_bank").first()
        # ensure Misc has no budget line this month
        remove_line(m, misc.id)
        before = compute_budget(m)
        # spend in Misc
        tx.create(MultiDict([("type", "expense"), ("date", m.isoformat()),
                             ("amount", "1234"), ("account_id", str(acc.id)),
                             ("category_id", str(misc.id))]))
        after = compute_budget(m)
        # Misc is NOT shown as a budgeted row...
        misc_rows = [r for g in after["groups"] for r in g["rows"] if r["category"].id == misc.id]
        assert misc_rows == []
        # ...but the ₹1234 is captured in unbudgeted
        assert after["unbudgeted"] == before["unbudgeted"] + Decimal("1234.00")
        assert any(r["category_id"] == misc.id for r in after["unbudgeted_rows"])


def test_adding_line_moves_spending_into_budget(seeded):
    """Adding a budget line for that category moves its spend out of unbudgeted."""
    from app.services.budget import compute_budget, upsert_line, remove_line
    from app.models import Category, Account
    from app.services import transactions as tx
    from werkzeug.datastructures import MultiDict
    m = month_start(today_ist())
    with seeded.app_context():
        misc = Category.query.filter_by(name="Miscellaneous").first()
        acc = Account.query.filter_by(type="savings_bank").first()
        remove_line(m, misc.id)
        tx.create(MultiDict([("type", "expense"), ("date", m.isoformat()),
                             ("amount", "1000"), ("account_id", str(acc.id)),
                             ("category_id", str(misc.id))]))
        upsert_line(m, misc.id, Decimal("2000"))
        b = compute_budget(m)
        row = [r for g in b["groups"] for r in g["rows"] if r["category"].id == misc.id]
        assert len(row) == 1
        assert row[0]["spent"] == Decimal("1000.00")
        assert row[0]["planned"] == Decimal("2000.00")
