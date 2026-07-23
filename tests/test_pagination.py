"""Transaction list pagination: page slicing, has_more, and full-set totals."""
from decimal import Decimal

from werkzeug.datastructures import MultiDict


def test_pagination_slices_and_totals(seeded):
    from app.services.transactions import filter_transactions
    with seeded.app_context():
        # page 1 of 5
        p1 = filter_transactions(MultiDict(), page=1, page_size=5)
        assert len(p1["rows"]) == 5
        assert p1["count"] > 5              # total across all pages
        assert p1["has_more"] is True
        assert p1["shown"] == 5

        # totals are computed over the ENTIRE filtered set, not just the page
        full = filter_transactions(MultiDict(), page=1, page_size=10_000)
        assert p1["income"] == full["income"]
        assert p1["expense"] == full["expense"]
        assert p1["net"] == full["net"]

        # last page has the remainder and no "more"
        import math
        total = p1["count"]
        last_page = math.ceil(total / 5)
        last = filter_transactions(MultiDict(), page=last_page, page_size=5)
        assert last["has_more"] is False
        assert 1 <= len(last["rows"]) <= 5


def test_rows_endpoint_returns_more(seeded):
    client = seeded.test_client()
    # page 2 with default size still returns 200 (may be empty if <50 txns)
    r = client.get("/transactions/rows?page=2")
    assert r.status_code == 200


def test_pages_do_not_overlap(seeded):
    from app.services.transactions import filter_transactions
    with seeded.app_context():
        p1 = filter_transactions(MultiDict(), page=1, page_size=5)
        p2 = filter_transactions(MultiDict(), page=2, page_size=5)
        ids1 = {t.id for t in p1["rows"]}
        ids2 = {t.id for t in p2["rows"]}
        assert ids1.isdisjoint(ids2)
