"""Transactions: full page + filters, live htmx list, save/delete, payee autocomplete."""
from __future__ import annotations

import json

from flask import Blueprint, render_template, request, jsonify, abort, make_response

from ..extensions import db
from ..models import Transaction, Category, Account
from ..services import transactions as tx_svc
from ..services import accounts as acc_svc
from ..timeutil import today_ist, month_start, month_label

bp = Blueprint("transactions", __name__, url_prefix="/transactions")


def _form_context():
    return {
        "accounts": acc_svc.active_accounts(),
        "expense_cats": Category.query.filter_by(kind="expense", is_archived=False)
            .order_by(Category.group, Category.sort_order, Category.name).all(),
        "income_cats": Category.query.filter_by(kind="income", is_archived=False)
            .order_by(Category.sort_order, Category.name).all(),
        "today": today_ist().isoformat(),
    }


@bp.route("/")
def index():
    result = tx_svc.filter_transactions(request.args)
    months = _month_options()
    return render_template("transactions/index.html", result=result,
                           accounts=acc_svc.active_accounts(),
                           categories=Category.query.filter_by(is_archived=False)
                               .order_by(Category.kind, Category.name).all(),
                           months=months, args=request.args)


@bp.route("/list")
def list_partial():
    result = tx_svc.filter_transactions(request.args, page=1)
    return render_template("transactions/_list.html", result=result)


@bp.route("/rows")
def rows():
    """One appended page of rows (for the 'Load more' button)."""
    page = request.args.get("page", 1, type=int) or 1
    result = tx_svc.filter_transactions(request.args, page=page)
    return render_template("transactions/_rows.html", result=result)


@bp.route("/save", methods=["POST"])
def save():
    txn_id = request.form.get("id")
    try:
        if txn_id:
            t = db.session.get(Transaction, int(txn_id)) or abort(404)
            tx_svc.update(t, request.form)
            msg = "Transaction updated."
        else:
            t = tx_svc.create(request.form)
            msg = "Transaction added."
    except tx_svc.TxnError as e:
        return _trigger_response({"steward-toast": {"kind": "error", "message": str(e)}}, status=200)

    triggers = {
        "steward-refresh": True,
        "steward-added": {"id": t.id},
        "steward-toast": {"kind": "success", "message": msg},
    }
    _augment_overshoot(t, triggers)
    return _trigger_response(triggers)


@bp.route("/<int:txn_id>/delete", methods=["POST"])
def delete(txn_id):
    t = db.session.get(Transaction, txn_id) or abort(404)
    tx_svc.delete(t)
    return _trigger_response({
        "steward-refresh": True,
        "steward-toast": {"kind": "success", "message": "Transaction deleted."},
    })


@bp.route("/<int:txn_id>/json")
def txn_json(txn_id):
    t = db.session.get(Transaction, txn_id) or abort(404)
    return jsonify({
        "id": t.id, "type": t.type, "flow": t.flow, "date": t.date.isoformat(),
        "amount": str(t.amount), "account_id": t.account_id,
        "transfer_account_id": t.transfer_account_id, "category_id": t.category_id,
        "payee": t.payee or "", "note": t.note or "", "tags": t.tags or "",
        "budget_month": t.budget_month.isoformat() if t.budget_month else None,
        "splits": [{"category_id": s.category_id, "amount": str(s.amount)} for s in t.splits],
    })


@bp.route("/payees")
def payees():
    q = request.args.get("q", "")
    out = []
    for pm in tx_svc.payee_suggestions(q):
        out.append({
            "payee": pm.payee, "category_id": pm.last_category_id,
            "account_id": pm.last_account_id, "type": pm.last_type,
        })
    return jsonify(out)


@bp.route("/recents")
def recents():
    """Recent payees + amounts for the add-form quick-entry chips."""
    type_ = request.args.get("type", "expense")
    payees = [{
        "payee": pm.payee, "category_id": pm.last_category_id,
        "account_id": pm.last_account_id, "type": pm.last_type,
    } for pm in tx_svc.recent_payees(type_)]
    return jsonify({"payees": payees, "amounts": tx_svc.recent_amounts(type_)})


# ---- helpers --------------------------------------------------------------
def _trigger_response(triggers: dict, status: int = 204):
    resp = make_response("", status)
    resp.headers["HX-Trigger"] = json.dumps(triggers)
    return resp


def _augment_overshoot(t: Transaction, triggers: dict) -> None:
    """If this expense pushes a category over 100%, add a red toast + alert."""
    if t.type != "expense":
        return
    from ..services.budget import compute_budget, check_overshoots
    affected = {s.category_id for s in t.splits} if t.splits else (
        {t.category_id} if t.category_id else set())
    if not affected:
        return
    data = compute_budget(t.budget_month)
    over_names = [row["category"].name
                 for g in data["groups"] for row in g["rows"]
                 if row["category"].id in affected and row["state"] == "over"]
    if over_names:
        check_overshoots(t.budget_month, only_categories=affected)
        names = ", ".join(over_names)
        over_toast = {"kind": "over", "title": "Over budget",
                      "message": f"You've gone over your {names} budget."}
        base = triggers.get("steward-toast")
        triggers["steward-toast"] = [base, over_toast] if base else over_toast


def _month_options():
    """Distinct months that have transactions, newest first, plus current."""
    dates = db.session.query(Transaction.date).order_by(Transaction.date.desc()).all()
    seen, months = set(), []
    cur = month_start(today_ist())
    for (d,) in dates:
        m = month_start(d)
        if m not in seen:
            seen.add(m)
            months.append(m)
    if cur not in seen:
        months.insert(0, cur)
    return months
