"""Category management: add / edit / archive / delete (with a usage guard)."""
from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from ..extensions import db
from ..models import (Category, Transaction, BudgetLine, RecurringRule, PayeeMemory,
                      CATEGORY_KINDS)
from ..services.invest_link import (ensure_savings_categories,
                                    SAVINGS_CATEGORY_NAMES)

bp = Blueprint("categories", __name__, url_prefix="/categories")


def _usage_count(cat_id: int) -> int:
    return (
        Transaction.query.filter_by(category_id=cat_id).count()
        + BudgetLine.query.filter_by(category_id=cat_id).count()
        + RecurringRule.query.filter_by(category_id=cat_id).count()
        + PayeeMemory.query.filter_by(last_category_id=cat_id).count()
    )


@bp.route("/")
def index():
    ensure_savings_categories()   # the five static savings categories always exist
    cats = Category.query.order_by(Category.kind, Category.group,
                                   Category.sort_order, Category.name).all()
    used = {c.id: _usage_count(c.id) for c in cats}
    expense = defaultdict(list)
    income = []
    savings = []
    groups = set()
    for c in cats:
        if c.group:
            groups.add(c.group)
        if c.kind == "income":
            income.append(c)
        elif c.kind == "savings":
            savings.append(c)
        else:
            expense[c.group or "Other"].append(c)
    ordered = ["Essentials", "Lifestyle", "Giving", "Savings", "Other"]
    expense_groups = [(g, expense[g]) for g in ordered if g in expense]
    expense_groups += [(g, expense[g]) for g in sorted(expense) if g not in ordered]
    # The five canonical savings categories are locked (each backs a Savings tab);
    # any other savings category (e.g. a legacy one) stays editable/removable.
    locked_savings = {c.id for c in savings if c.name in SAVINGS_CATEGORY_NAMES}
    return render_template("categories/index.html",
                           expense_groups=expense_groups, income=income,
                           savings=savings, groups=sorted(groups), used=used,
                           locked_savings=locked_savings)


@bp.route("/save", methods=["POST"])
def save():
    cid = request.form.get("id")
    cat = db.session.get(Category, int(cid)) if cid and cid.isdigit() else Category()
    if cat is None:
        abort(404)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Give the category a name.", "error")
        return redirect(url_for("categories.index"))
    is_new = not (cid and cid.isdigit())
    if is_new and request.form.get("kind") == "savings":
        flash("Savings categories are fixed — one per Savings tab — and can't be added.", "error")
        return redirect(url_for("categories.index"))
    if not is_new and cat.kind == "savings" and cat.name in SAVINGS_CATEGORY_NAMES:
        flash("This savings category is locked to a Savings tab and can't be changed.", "error")
        return redirect(url_for("categories.index"))
    cat.name = name
    # kind is fixed once a category has history (changing it would corrupt reports)
    if is_new or _usage_count(cat.id) == 0:
        cat.kind = request.form.get("kind") if request.form.get("kind") in CATEGORY_KINDS else "expense"
    cat.icon = (request.form.get("icon") or "🏷️").strip()[:8] or "🏷️"
    cat.group = (request.form.get("group") or "").strip()
    if is_new:
        cat.sort_order = (db.session.query(db.func.max(Category.sort_order)).scalar() or 0) + 1
        db.session.add(cat)
    db.session.commit()
    flash("Category saved.", "success")
    return redirect(url_for("categories.index"))


@bp.route("/<int:cat_id>/archive", methods=["POST"])
def archive(cat_id):
    cat = db.session.get(Category, cat_id) or abort(404)
    cat.is_archived = not cat.is_archived
    db.session.commit()
    flash(f"Category {'archived' if cat.is_archived else 'restored'}.", "success")
    return redirect(url_for("categories.index"))


@bp.route("/<int:cat_id>/delete", methods=["POST"])
def delete(cat_id):
    cat = db.session.get(Category, cat_id) or abort(404)
    if cat.kind == "savings" and cat.name in SAVINGS_CATEGORY_NAMES:
        flash("This savings category is locked to a Savings tab and can't be deleted.", "error")
        return redirect(url_for("categories.index"))
    used = _usage_count(cat_id)
    if used:
        flash(f"'{cat.name}' is used by {used} record(s) — archive it instead to keep history.", "error")
        return redirect(url_for("categories.index"))
    db.session.delete(cat)
    db.session.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("categories.index"))
