"""Settings page: salary-rule window, EPF rate, gold override, tax rules, theme."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file)

from ..extensions import db
from ..models import Setting
from ..services import backup as backup_svc
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
                           defaults=DEFAULTS, prices=prices,
                           backup_info=backup_svc.last_backup_info())


@bp.route("/", methods=["POST"])
def save():
    for key in EDITABLE:
        if key in request.form:
            Setting.set(key, request.form.get(key, "").strip())
    db.session.commit()
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/backup")
def backup():
    """Download a byte-exact snapshot of the database."""
    try:
        data = backup_svc.snapshot_bytes()
    except Exception as exc:  # noqa: BLE001 - surface the reason, don't 500
        flash(f"Couldn't create a backup: {exc}", "error")
        return redirect(url_for("settings.index"))

    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=backup_svc.backup_filename(),
                     mimetype="application/vnd.sqlite3")


@bp.route("/restore", methods=["POST"])
def restore():
    """Replace the database with an uploaded backup."""
    upload = request.files.get("backup")
    if not upload or not upload.filename:
        flash("Choose a backup file first.", "error")
        return redirect(url_for("settings.index"))

    tmp = Path(tempfile.mkdtemp(prefix="steward-restore-")) / "upload.db"
    try:
        upload.save(tmp)
        safety = backup_svc.restore(tmp)
        flash(
            "Database restored. The previous one was saved as "
            f"{safety.name} — restart the app to be safe.", "success")
    except backup_svc.RestoreError as exc:
        flash(str(exc), "error")
    except Exception as exc:  # noqa: BLE001
        flash(f"Restore failed: {exc}", "error")
    finally:
        tmp.unlink(missing_ok=True)
        tmp.parent.rmdir()
    return redirect(url_for("settings.index"))
