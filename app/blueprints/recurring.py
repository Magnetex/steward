"""Recurring rules: CRUD, upcoming list, manual run, and 'Record it'."""
from __future__ import annotations

import json

from flask import Blueprint, render_template, request, make_response, redirect, url_for, flash, abort

from ..extensions import db
from ..models import RecurringRule, Category, Account, Alert, RECUR_FREQ, RECUR_MODES
from ..money import money
from ..timeutil import parse_date, today_ist
from ..services import recurring as rec_svc
from ..services import accounts as acc_svc

bp = Blueprint("recurring", __name__, url_prefix="/recurring")

# The Recurring page is for expense/income/transfer only. Investments (SIPs, RDs)
# are managed in Savings, not here.
_PAGE_TYPES = ("expense", "income", "transfer")


def _ctx():
    return {
        "rules": RecurringRule.query
            .filter(RecurringRule.type.in_(_PAGE_TYPES))
            .order_by(RecurringRule.active.desc(), RecurringRule.next_due_date).all(),
        "upcoming": [r for r in rec_svc.upcoming(14) if r.type in _PAGE_TYPES],
        "accounts": acc_svc.active_accounts(),
        "expense_cats": Category.query.filter_by(kind="expense", is_archived=False).order_by(Category.name).all(),
        "income_cats": Category.query.filter_by(kind="income", is_archived=False).order_by(Category.name).all(),
        "freqs": RECUR_FREQ, "modes": RECUR_MODES, "today": today_ist().isoformat(),
    }


@bp.route("/")
def index():
    return render_template("recurring/index.html", **_ctx())


@bp.route("/save", methods=["POST"])
def save():
    rid = request.form.get("id")
    rule = db.session.get(RecurringRule, int(rid)) if rid and rid.isdigit() else RecurringRule()
    if rule is None:
        abort(404)
    f = request.form
    rule.payee = (f.get("payee") or "").strip()
    rule.amount = money(f.get("amount"))
    rule.type = f.get("type") if f.get("type") in ("expense", "income", "transfer") else "expense"
    rule.category_id = f.get("category_id", type=int) if rule.type != "transfer" else None
    rule.account_id = f.get("account_id", type=int)
    rule.transfer_account_id = f.get("transfer_account_id", type=int) if rule.type == "transfer" else None
    rule.frequency = f.get("frequency") if f.get("frequency") in RECUR_FREQ else "monthly"
    rule.day_of_month = f.get("day_of_month", type=int) or 1
    rule.weekday = f.get("weekday", type=int) or 0
    rule.month_of_year = f.get("month_of_year", type=int) or 1
    rule.next_due_date = parse_date(f.get("next_due_date"), today_ist())
    rule.mode = f.get("mode") if f.get("mode") in RECUR_MODES else "auto_create"
    rule.note = (f.get("note") or "").strip()
    rule.tags = (f.get("tags") or "").strip()
    rule.active = f.get("active") in ("on", "true", "1", "yes", None) if "active" in f else True
    if not rule.account_id:
        flash("Choose an account for the rule.", "error")
        return redirect(url_for("recurring.index"))
    if rid and rid.isdigit():
        pass
    else:
        db.session.add(rule)
    db.session.commit()
    flash("Recurring rule saved.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/<int:rule_id>/delete", methods=["POST"])
def delete(rule_id):
    rule = db.session.get(RecurringRule, rule_id) or abort(404)
    db.session.delete(rule)
    db.session.commit()
    flash("Rule deleted.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/<int:rule_id>/toggle", methods=["POST"])
def toggle(rule_id):
    rule = db.session.get(RecurringRule, rule_id) or abort(404)
    rule.active = not rule.active
    db.session.commit()
    flash(f"Rule {'resumed' if rule.active else 'paused'}.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/run", methods=["POST"])
def run_now():
    # Recurring rules only — SIP/RD auto-investments run on the daily scheduler.
    n = rec_svc.materialize_due()
    return _trigger({"steward-refresh": True,
                     "steward-toast": {"kind": "success",
                                       "message": f"Processed {n} due rule(s)." if n else "Nothing due right now."}})


@bp.route("/record/<int:rule_id>", methods=["POST"])
def record_it(rule_id):
    """From a remind-only alert: create the transaction now."""
    rule = db.session.get(RecurringRule, rule_id) or abort(404)
    rec_svc.record_from_rule(rule, on=today_ist())
    # mark the matching alert(s) read
    Alert.query.filter_by(action="record", ref_id=rule_id, is_read=False).update({"is_read": True})
    db.session.commit()
    from ..services import alerts as alerts_svc
    html = render_template("partials/alerts_panel.html", alerts=alerts_svc.recent())
    resp = make_response(html)
    resp.headers["HX-Trigger"] = json.dumps({
        "steward-refresh": True,
        "steward-toast": {"kind": "success", "message": "Recorded as a transaction."},
    })
    return resp


def _trigger(triggers, status=204):
    resp = make_response("", status)
    resp.headers["HX-Trigger"] = json.dumps(triggers)
    return resp
