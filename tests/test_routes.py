"""Smoke test: every GET page renders 200 on seeded data; core mutations work."""
import pytest


GET_ROUTES = [
    "/", "/dashboard/summary", "/dashboard/budget-panel", "/dashboard/recent",
    "/transactions/", "/transactions/list", "/transactions/payees?q=net",
    "/transactions/recents?type=expense",
    "/accounts/", "/budget/", "/recurring/", "/funds/", "/savings/",
    "/networth/", "/reports/", "/tax/", "/settings/", "/api/alerts",
]


@pytest.mark.parametrize("route", GET_ROUTES)
def test_get_route_ok(seeded, route):
    client = seeded.test_client()
    resp = client.get(route)
    assert resp.status_code == 200, f"{route} -> {resp.status_code}"


def test_create_and_delete_transaction(seeded):
    client = seeded.test_client()
    from app.models import Account, Category, Transaction
    with seeded.app_context():
        acc = Account.query.filter_by(type="savings_bank").first().id
        cat = Category.query.filter_by(kind="expense").first().id
        before = Transaction.query.filter(Transaction.parent_id.is_(None)).count()

    r = client.post("/transactions/save", data={
        "type": "expense", "date": "2026-07-15", "amount": "99.50",
        "account_id": acc, "category_id": cat, "payee": "Test Payee"})
    assert r.status_code == 204
    assert "steward-refresh" in r.headers.get("HX-Trigger", "")

    with seeded.app_context():
        from app.models import Transaction
        after = Transaction.query.filter(Transaction.parent_id.is_(None)).count()
        assert after == before + 1
        newest = Transaction.query.order_by(Transaction.id.desc()).first()
        tid = newest.id

    r = client.post(f"/transactions/{tid}/delete")
    assert r.status_code == 204


def test_transfer_not_counted_in_budget(seeded):
    """Transfers must not affect income/expense budget math."""
    client = seeded.test_client()
    from app.services.budget import compute_budget
    from app.timeutil import today_ist, month_start
    with seeded.app_context():
        from app.models import Account
        a = Account.query.filter_by(type="savings_bank").first().id
        b = Account.query.filter_by(type="wallet").first().id
        m = month_start(today_ist())
        before = compute_budget(m)["total_spent"]

    client.post("/transactions/save", data={
        "type": "transfer", "date": today_ist().isoformat(), "amount": "5000",
        "account_id": a, "transfer_account_id": b})

    with seeded.app_context():
        after = compute_budget(m)["total_spent"]
        assert after == before  # unchanged by a transfer


def test_payee_memory_prefill(seeded):
    client = seeded.test_client()
    resp = client.get("/transactions/payees?q=netflix")
    data = resp.get_json()
    assert any(p["payee"].lower().startswith("netflix") for p in data)
    assert data[0]["category_id"] is not None


def test_recents_chips(seeded):
    """Add-form quick-entry chips: recent payees + distinct amounts, type-scoped."""
    client = seeded.test_client()
    from datetime import timedelta
    from app.models import Account, Category, Transaction
    with seeded.app_context():
        acc = Account.query.filter_by(type="savings_bank").first().id
        cat = Category.query.filter_by(kind="expense").first().id
        # Newer than anything seeded, rather than a hardcoded date. Seed places
        # current-month rows on fixed days (dm(this_m, 12)), so early in the
        # month they are dated in the future -- a fixed date here silently
        # dropped out of the newest-5 window and failed on its own.
        newest = Transaction.query.order_by(Transaction.date.desc()).first().date
    entered_on = (newest + timedelta(days=1)).isoformat()

    for amt in ("120.00", "120.00", "340.00"):  # dupes should collapse
        client.post("/transactions/save", data={
            "type": "expense", "date": entered_on, "amount": amt,
            "account_id": acc, "category_id": cat, "payee": "Chip Cafe"})

    data = client.get("/transactions/recents?type=expense").get_json()
    assert "120.00" in data["amounts"]
    assert data["amounts"].count("120.00") == 1  # distinct
    assert any(p["payee"] == "Chip Cafe" for p in data["payees"])
    # Payees are type-scoped: an expense payee shouldn't surface under income.
    inc = client.get("/transactions/recents?type=income").get_json()
    assert all(p["payee"] != "Chip Cafe" for p in inc["payees"])
