"""Every page must render on a brand-new ledger.

`flask fresh-db` leaves categories and nothing else, so this is the first
thing anyone starting real tracking sees. Every other test runs on seeded
data, which is how a NameError in the dashboard's investment glance survived
a full green suite: the offending `gold["value"] or ZERO` only evaluates
`ZERO` when the gold value is falsy, and seeded data always has gold.
"""
import pytest


GET_ROUTES = [
    "/", "/dashboard/summary", "/dashboard/budget-panel", "/dashboard/recent",
    "/transactions/", "/transactions/list",
    "/accounts/", "/budget/", "/recurring/", "/funds/", "/savings/",
    "/networth/", "/reports/", "/tax/", "/settings/", "/categories/", "/api/alerts",
]


@pytest.fixture
def fresh(app):
    """A database in exactly the state `flask fresh-db` leaves it."""
    from app.services.seed import seed_scaffold
    from app.extensions import db
    with app.app_context():
        seed_scaffold()
        db.session.commit()
    yield app


@pytest.mark.parametrize("route", GET_ROUTES)
def test_page_renders_on_empty_ledger(fresh, route):
    resp = fresh.test_client().get(route)
    assert resp.status_code == 200, f"{route} -> {resp.status_code}"


def test_glance_handles_no_holdings(fresh):
    """No gold, no funds, no deposits -- the falsy branch that broke."""
    from app.blueprints.dashboard import _glance
    with fresh.app_context():
        g = _glance()
    assert g["gold_value"] == 0
    assert g["next_dep"] is None


def test_networth_is_zero_not_an_error(fresh):
    from app.blueprints.dashboard import _summary_context
    from app.services import networth as nw
    with fresh.app_context():
        assert nw.current_total() == 0
        assert _summary_context()["networth"] == 0
