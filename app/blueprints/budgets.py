"""Budget page: month switcher, grouped lines, inline editing, copy-last-month."""
from __future__ import annotations

import json

from flask import Blueprint, render_template, request, make_response, abort

from ..extensions import db
from ..models import Category
from ..money import money
from ..timeutil import today_ist, month_start, next_month_start, prev_month_start, parse_date, month_label
from ..services import budget as budget_svc

bp = Blueprint("budgets", __name__, url_prefix="/budget")


def _month_from_args():
    raw = request.args.get("month") or request.form.get("month")
    if raw:
        d = parse_date(raw + "-01" if len(raw) == 7 else raw)
        if d:
            return month_start(d)
    return month_start(today_ist())


def _grid_context(month):
    exp = budget_svc.compute_budget(month)
    inc = budget_svc.compute_income(month)
    # categories not yet in the budget (for the "add line" picker) — expense and
    # savings alike; savings rows only count as "used" once they have a line.
    used = {r["category"].id for g in exp["groups"] for r in g["rows"]}
    used |= {r["category"].id for r in exp["savings"]["rows"] if r["has_line"]}
    addable = Category.query.filter(Category.kind.in_(["expense", "savings"]),
                                    Category.is_archived.is_(False)) \
        .filter(~Category.id.in_(used or [0])) \
        .order_by(Category.kind, Category.group, Category.name).all()
    return {
        "month": month, "budget": exp, "income": inc, "addable": addable,
        "prev_month": prev_month_start(month), "next_month": next_month_start(month),
    }


@bp.route("/")
def index():
    month = _month_from_args()
    return render_template("budgets/index.html", **_grid_context(month))


@bp.route("/grid")
def grid():
    month = _month_from_args()
    return render_template("budgets/_grid.html", **_grid_context(month))


@bp.route("/line", methods=["POST"])
def save_line():
    month = _month_from_args()
    cat_id = request.form.get("category_id", type=int)
    if not cat_id:
        abort(400)
    amount = money(request.form.get("planned_amount"))
    budget_svc.upsert_line(month, cat_id, amount)
    triggers = {"steward-refresh": True}
    # lowering a plan can push a category over budget
    budget_svc.check_overshoots(month, only_categories={cat_id})
    return _trigger(triggers)


@bp.route("/add-line", methods=["POST"])
def add_line():
    month = _month_from_args()
    cat_id = request.form.get("category_id", type=int)
    if cat_id:
        budget_svc.upsert_line(month, cat_id, money(0))
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": "Category added to budget."}})


@bp.route("/remove-line", methods=["POST"])
def remove_line():
    month = _month_from_args()
    cat_id = request.form.get("category_id", type=int)
    if cat_id:
        budget_svc.remove_line(month, cat_id)
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": "Removed from budget."}})


@bp.route("/copy", methods=["POST"])
def copy_last():
    month = _month_from_args()
    n = budget_svc.copy_from_previous(month)
    msg = f"Copied {n} line(s) from {month_label(prev_month_start(month))}." if n \
        else "Nothing new to copy — those categories already have plans."
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": msg}})


def _trigger(triggers, status=204):
    resp = make_response("", status)
    resp.headers["HX-Trigger"] = json.dumps(triggers)
    return resp
