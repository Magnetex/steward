"""Settings page: salary-rule window, EPF rate, gold override, tax rules, theme."""
from __future__ import annotations

from flask import Blueprint, render_template, request, redirect, url_for, flash

from ..extensions import db
from ..models import Setting
from ..services.settings import all_settings, DEFAULTS

bp = Blueprint("settings", __name__, url_prefix="/settings")

# keys the settings form is allowed to write
EDITABLE = [
    "salary_rule_window", "epf_interest_rate", "gold_manual_rate",
    "equity_ltcg_months", "equity_ltcg_rate", "equity_ltcg_exemption",
    "equity_stcg_rate", "debt_slab_rate", "gold_ltcg_months", "gold_ltcg_rate",
    "gold_slab_rate", "sec80c_limit", "theme",
]


@bp.route("/")
def index():
    from ..models import PriceCache
    prices = PriceCache.query.order_by(PriceCache.key).all()
    return render_template("settings/index.html", settings=all_settings(),
                           defaults=DEFAULTS, prices=prices)


@bp.route("/", methods=["POST"])
def save():
    for key in EDITABLE:
        if key in request.form:
            Setting.set(key, request.form.get(key, "").strip())
    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))
