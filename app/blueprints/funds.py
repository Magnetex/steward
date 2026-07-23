"""Sinking-fund goals: progress cards, goal CRUD, and asset earmarking."""
from __future__ import annotations

import json

from flask import Blueprint, render_template, request, make_response, redirect, url_for, flash, abort

from ..extensions import db
from ..models import SinkingFund, FundAllocation, FUND_SOURCE_KINDS, Category
from ..money import money, ZERO
from ..timeutil import parse_date, today_ist
from ..services import funds as funds_svc
from ..services import accounts as acc_svc

bp = Blueprint("funds", __name__, url_prefix="/funds")


def _ctx() -> dict:
    """Shared context for the goals page and the htmx-refreshed cards."""
    return {
        "statuses": funds_svc.all_fund_statuses(),
        "archived": funds_svc.archived_fund_statuses(),
        "sources": funds_svc.list_sources(),
        "cash_accounts": acc_svc.active_accounts(),
        "expense_categories": Category.query.filter_by(
            kind="expense", is_archived=False).order_by(
            Category.group, Category.sort_order, Category.name).all(),
        "today": today_ist().isoformat(),
    }


@bp.route("/")
def index():
    return render_template("funds/index.html", **_ctx())


@bp.route("/cards")
def cards():
    return render_template("funds/_cards.html", **_ctx())


@bp.route("/save", methods=["POST"])
def save():
    fid = request.form.get("id")
    fund = db.session.get(SinkingFund, int(fid)) if fid and fid.isdigit() else None
    f = request.form
    name = (f.get("name") or "").strip()
    if not name:
        flash("Give the fund a name.", "error")
        return redirect(url_for("funds.index"))
    if fund is None:
        fund = SinkingFund()
        db.session.add(fund)
    fund.name = name
    fund.icon = (f.get("icon") or "🎯").strip()[:8] or "🎯"
    fund.target_amount = money(f.get("target_amount"))
    fund.target_date = parse_date(f.get("target_date"))
    fund.note = (f.get("note") or "").strip()
    db.session.commit()
    flash("Fund saved.", "success")
    return redirect(url_for("funds.index"))


@bp.route("/<int:fund_id>/delete", methods=["POST"])
def delete(fund_id):
    fund = db.session.get(SinkingFund, fund_id) or abort(404)
    db.session.delete(fund)   # allocations cascade; earmarks simply released
    db.session.commit()
    flash("Fund removed.", "success")
    return redirect(url_for("funds.index"))


@bp.route("/allocate", methods=["POST"])
def allocate():
    """Earmark a ₹ slice of a source (kind:ref_id) toward a goal."""
    fund = db.session.get(SinkingFund, request.form.get("fund_id", type=int))
    if fund is None:
        abort(404)
    kind, _, ref = (request.form.get("source") or "").partition(":")
    if kind not in FUND_SOURCE_KINDS or not ref.isdigit():
        return _trigger({"steward-toast": {"kind": "error", "message": "Pick a source to allocate from."}}, 200)
    ref_id = int(ref)
    amount = money(request.form.get("amount"))
    if amount <= 0:
        return _trigger({"steward-toast": {"kind": "error", "message": "Enter an amount."}}, 200)

    available = funds_svc.available_to_allocate(kind, ref_id)
    status = funds_svc.fund_status(fund)
    remaining_to_goal = status["remaining"]
    allowed = min(available, remaining_to_goal) if remaining_to_goal > 0 else available
    # target reached -> nothing more to earmark ("stop adding")
    if remaining_to_goal <= 0:
        return _trigger({"steward-toast": {"kind": "warn", "message": f"{fund.name} has already reached its target."}}, 200)
    if available <= 0:
        return _trigger({"steward-toast": {"kind": "warn", "message": f"{funds_svc.source_label(kind, ref_id)} is fully earmarked already."}}, 200)

    clamped = amount > allowed
    amount = min(amount, allowed)
    db.session.add(FundAllocation(fund_id=fund.id, source_kind=kind,
                                  source_ref_id=ref_id, amount=amount))
    db.session.commit()
    msg = (f"Earmarked {money(amount)} (capped to what's available)." if clamped
           else f"Earmarked {money(amount)} for {fund.name}.")
    return _trigger({"steward-refresh": True, "steward-toast": {"kind": "success", "message": msg}})


@bp.route("/allocation/<int:alloc_id>/delete", methods=["POST"])
def unallocate(alloc_id):
    a = db.session.get(FundAllocation, alloc_id) or abort(404)
    db.session.delete(a)
    db.session.commit()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": "Earmark removed."}})


@bp.route("/spend", methods=["POST"])
def spend():
    """Redeem selected earmarks to cash, record the purchase, archive the goal."""
    fund = db.session.get(SinkingFund, request.form.get("fund_id", type=int)) or abort(404)
    f = request.form
    alloc_ids = f.getlist("alloc_ids")
    proceeds_account_id = f.get("proceeds_account_id", type=int)
    expense = {
        "amount": f.get("amount"),
        "category_id": f.get("category_id", type=int),
        "account_id": f.get("expense_account_id", type=int),
        "payee": f.get("payee"),
        "note": f.get("note"),
        "date": parse_date(f.get("date"), today_ist()),
    }
    archive = f.get("archive") in ("1", "true", "on", "yes")
    result = funds_svc.spend_goal(
        fund, alloc_ids=alloc_ids, proceeds_account_id=proceeds_account_id,
        expense=expense, archive=archive)
    parts = []
    if result["redeemed"] > 0:
        parts.append(f"redeemed {money(result['redeemed'])}")
    if result["expense"] > 0:
        parts.append(f"spent {money(result['expense'])}")
    msg = f"{fund.name}: " + (", ".join(parts) if parts else "updated") + \
          (" · goal archived." if result["archived"] else ".")
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": msg}})


@bp.route("/<int:fund_id>/archive", methods=["POST"])
def archive(fund_id):
    fund = db.session.get(SinkingFund, fund_id) or abort(404)
    fund.is_archived = True
    db.session.commit()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": f"{fund.name} archived."}})


@bp.route("/<int:fund_id>/unarchive", methods=["POST"])
def unarchive(fund_id):
    fund = db.session.get(SinkingFund, fund_id) or abort(404)
    fund.is_archived = False
    db.session.commit()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success", "message": f"{fund.name} restored."}})


def _trigger(triggers, status=204):
    resp = make_response("", status)
    resp.headers["HX-Trigger"] = json.dumps(triggers)
    return resp
