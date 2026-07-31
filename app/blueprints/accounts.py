"""Accounts: list with balances + CRUD (htmx modal)."""
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from ..extensions import db
from ..models import Account, Transaction, ACCOUNT_TYPES
from ..money import money
from ..services import accounts as acc_svc

bp = Blueprint("accounts", __name__, url_prefix="/accounts")

TYPE_LABELS = {
    "savings_bank": "Savings / bank", "wallet": "Wallet",
    "cash": "Cash", "fund": "Fund (legacy)",
}
TYPE_ICONS = {"savings_bank": "🏦", "wallet": "📱", "cash": "💵", "fund": "🤲"}


@bp.route("/")
def index():
    # Legacy envelope 'fund' accounts are hidden — sinking funds are now goals,
    # not accounts (see the Sinking funds page).
    pairs = [(a, b) for a, b in acc_svc.list_with_balances(include_archived=True)
             if a.type != "fund"]
    return render_template("accounts/index.html", pairs=pairs, types=ACCOUNT_TYPES,
                           type_labels=TYPE_LABELS, type_icons=TYPE_ICONS,
                           available=acc_svc.available_total())


@bp.route("/save", methods=["POST"])
def save():
    account_id = request.form.get("id")
    account_id = int(account_id) if account_id and account_id.isdigit() else None
    account = db.session.get(Account, account_id) if account_id else Account()
    if account is None:
        abort(404)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Account needs a name.", "error")
        return redirect(url_for("accounts.index"))
    account.name = name
    account.type = request.form.get("type") if request.form.get("type") in ACCOUNT_TYPES else "savings_bank"
    account.opening_balance = money(request.form.get("opening_balance"))
    account.icon = (request.form.get("icon") or TYPE_ICONS.get(account.type, "🏦")).strip()[:8] or "🏦"
    account.color = (request.form.get("color") or "#1E6B4E").strip()
    if account_id is None:
        account.sort_order = (db.session.query(db.func.max(Account.sort_order)).scalar() or 0) + 1
        db.session.add(account)
    db.session.commit()
    flash("Account saved.", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/archive", methods=["POST"])
def archive(account_id):
    account = db.session.get(Account, account_id) or abort(404)
    account.is_archived = not account.is_archived
    db.session.commit()
    flash(f"Account {'archived' if account.is_archived else 'restored'}.", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/delete", methods=["POST"])
def delete(account_id):
    account = db.session.get(Account, account_id) or abort(404)
    used = Transaction.query.filter(
        db.or_(Transaction.account_id == account_id,
               Transaction.transfer_account_id == account_id)).count()
    if used:
        flash("Can't delete an account with transactions — archive it instead.", "error")
        return redirect(url_for("accounts.index"))
    db.session.delete(account)
    db.session.commit()
    flash("Account deleted.", "success")
    return redirect(url_for("accounts.index"))
