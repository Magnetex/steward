"""Tax page: FIFO capital gains + 80C summary. A report, not tax advice."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, render_template, request

from ..timeutil import today_ist, financial_year_bounds
from ..services import tax as tax_svc

bp = Blueprint("tax", __name__, url_prefix="/tax")


def _fy_date():
    raw = request.args.get("fy")  # e.g. "2026" meaning FY 2026-27
    if raw and raw.isdigit():
        return date(int(raw), 6, 1)  # mid-year anchor inside Apr-Mar FY
    return today_ist()


@bp.route("/")
def index():
    fy_date = _fy_date()
    start, end = financial_year_bounds(fy_date)
    gains = tax_svc.capital_gains(fy_date)
    eighty_c = tax_svc.sec_80c(fy_date)
    return render_template(
        "tax/index.html",
        fy_label=f"{start.year}–{str(end.year)[2:]}",
        prev_fy=start.year - 1, next_fy=start.year + 1,
        gains=gains, eighty_c=eighty_c, bucket_labels=tax_svc.BUCKET_LABELS,
    )
