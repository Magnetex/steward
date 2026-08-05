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


# --- charts have a text equivalent ----------------------------------------
def test_charts_without_a_list_carry_a_data_table(seeded):
    """A chart is an SVG: unreadable to a screen reader, absent if it can't draw."""
    html = seeded.test_client().get("/reports/").get_data(as_text=True)
    assert 'data-chart-fallback="rep-mom"' in html
    assert 'data-chart-fallback="rep-trend"' in html
    assert "Income and expense by month" in html, "the table is captioned"
    # the donut needs none: the category list under it already says the same
    assert 'data-chart-fallback="rep-donut"' not in html


def test_every_chart_is_hidden_from_screen_readers(seeded):
    """Either a table or a visible list carries the numbers instead."""
    client = seeded.test_client()
    for path, ids in (("/reports/", ["rep-donut", "rep-mom", "rep-trend"]),
                      ("/networth/", ["nw-donut", "nw-trend", "nw-comp"]),
                      ("/", ["nw-spark"])):
        html = client.get(path).get_data(as_text=True)
        for chart_id in ids:
            i = html.find('id="%s"' % chart_id)
            assert i != -1, f"{chart_id} missing from {path}"
            assert 'aria-hidden="true"' in html[i:i + 200], \
                f"{chart_id} on {path} is read out as raw SVG"


def test_the_networth_history_charts_have_tables(seeded):
    html = seeded.test_client().get("/networth/").get_data(as_text=True)
    assert 'data-chart-fallback="nw-trend"' in html
    assert 'data-chart-fallback="nw-comp"' in html
    assert "Net worth by snapshot date" in html
