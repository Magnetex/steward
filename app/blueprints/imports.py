"""SMS import review queue: scan, confirm, dismiss."""
from __future__ import annotations

import json

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, make_response)

from ..extensions import db
from ..models import Account, Category, PendingImport
from ..services import sms_import as sms
from ..timeutil import today_ist

bp = Blueprint("imports", __name__, url_prefix="/imports")


def _context():
    return {
        "rows": sms.pending_rows(),
        "accounts": Account.query.filter_by(is_archived=False)
                    .order_by(Account.sort_order, Account.name).all(),
        "categories": Category.query.filter_by(is_archived=False)
                      .order_by(Category.kind, Category.sort_order).all(),
        "last_scan": sms.last_scan_at(),
        "termux": sms.termux_available(),
        "today": today_ist(),
    }


@bp.route("/")
def index():
    return render_template("imports/index.html", **_context())


@bp.route("/scan", methods=["POST"])
def scan():
    try:
        result = sms.scan()
        flash(result["message"], "success" if result["imported"] else "info")
    except sms.SMSUnavailable as exc:
        flash(str(exc), "error")
    except Exception as exc:  # noqa: BLE001
        flash(f"Scan failed: {exc}", "error")
    return redirect(url_for("imports.index"))


@bp.route("/<int:row_id>/confirm", methods=["POST"])
def confirm(row_id):
    row = db.session.get(PendingImport, row_id)
    if row is None or row.status != "pending":
        flash("That item is no longer pending.", "error")
        return redirect(url_for("imports.index"))

    def _int(name):
        raw = (request.form.get(name) or "").strip()
        return int(raw) if raw.isdigit() else None

    try:
        sms.confirm(
            row,
            account_id=_int("account_id"),
            category_id=_int("category_id"),
            transfer_account_id=_int("transfer_account_id"),
            txn_type=(request.form.get("type") or "").strip() or None,
            payee=request.form.get("payee"),
        )
        flash("Transaction added.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("imports.index"))


@bp.route("/<int:row_id>/dismiss", methods=["POST"])
def dismiss(row_id):
    row = db.session.get(PendingImport, row_id)
    if row is not None and row.status == "pending":
        sms.dismiss(row)
        flash("Dismissed.", "success")
    return redirect(url_for("imports.index"))
