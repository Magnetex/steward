"""Small htmx/JSON endpoints: theme persistence and the alert center."""
from __future__ import annotations

from flask import Blueprint, request, render_template, jsonify

from ..extensions import db
from ..models import Setting
from ..services import alerts as alerts_svc

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/theme", methods=["POST"])
def set_theme():
    theme = (request.form.get("theme") or request.json.get("theme") if request.is_json else request.form.get("theme")) or "light"
    theme = "dark" if str(theme).lower() == "dark" else "light"
    Setting.set("theme", theme)
    db.session.commit()
    return jsonify({"theme": theme})


@bp.route("/alerts")
def alerts_panel():
    return render_template("partials/alerts_panel.html", alerts=alerts_svc.recent())


@bp.route("/alerts/<int:alert_id>/read", methods=["POST"])
def alert_read(alert_id):
    alerts_svc.mark_read(alert_id)
    return render_template("partials/alerts_panel.html", alerts=alerts_svc.recent())


@bp.route("/alerts/read-all", methods=["POST"])
def alerts_read_all():
    alerts_svc.mark_all_read()
    return render_template("partials/alerts_panel.html", alerts=alerts_svc.recent())


@bp.route("/refresh-prices", methods=["POST"])
def refresh_prices():
    """Manual price refresh (MF NAVs, gold, USDINR, stock) with per-item status."""
    import json
    from ..services.prices import refresh_all
    from flask import make_response
    results = refresh_all()
    html = render_template("partials/price_results.html", results=results)
    resp = make_response(html)
    ok = sum(1 for v in results.values() if v)
    resp.headers["HX-Trigger"] = json.dumps({
        "steward-refresh": True,
        "steward-toast": {"kind": "success" if ok == len(results) else "warn",
                          "message": f"Refreshed {ok}/{len(results)} price sources."},
    })
    return resp
