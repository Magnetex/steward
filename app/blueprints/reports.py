"""Reports page: the four fixed reports."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, render_template, request

from ..timeutil import today_ist, month_start, next_month_start, prev_month_start, parse_date, month_label
from ..services import reports as rep

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _month():
    raw = request.args.get("month")
    if raw:
        d = parse_date(raw + "-01" if len(raw) == 7 else raw)
        if d:
            return month_start(d)
    return month_start(today_ist())


@bp.route("/")
def index():
    month = _month()
    by_cat = rep.spending_by_category(month)
    mom = rep.month_over_month(month)
    trend = rep.income_expense_trend(month, 12)
    payees = rep.top_payees(month)
    return render_template(
        "reports/index.html", month=month, month_lbl=month_label(month),
        prev_month=prev_month_start(month), next_month=next_month_start(month),
        by_cat=by_cat,
        by_cat_labels=[r["name"] for r in by_cat],
        by_cat_values=[float(r["amount"]) for r in by_cat],
        by_cat_total=sum((r["amount"] for r in by_cat), Decimal("0")),
        mom=mom,
        mom_labels=[r["name"] for r in mom["rows"][:8]],
        mom_this=[float(r["this"]) for r in mom["rows"][:8]],
        mom_prev=[float(r["prev"]) for r in mom["rows"][:8]],
        trend=trend,
        trend_income=[float(v) for v in trend["income"]],
        trend_expense=[float(v) for v in trend["expense"]],
        payees=payees,
    )
