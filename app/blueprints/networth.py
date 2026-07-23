"""Net worth: trend + composition charts, current breakdown donut, snapshot."""
from __future__ import annotations

import json

from flask import Blueprint, render_template, make_response

from ..money import money, ZERO
from ..services import networth as nw

bp = Blueprint("networth", __name__, url_prefix="/networth")

BUCKET_ORDER = ["cash_bank", "mf", "gold", "deposits", "epf", "stock"]


def _context():
    buckets = nw.current_buckets()
    total = money(sum(buckets.values(), ZERO))
    series = nw.snapshot_series(180)
    return {
        "buckets": buckets, "total": total,
        "labels": [nw.BUCKET_LABELS[k] for k in BUCKET_ORDER],
        "bucket_keys": BUCKET_ORDER,
        "donut_values": [float(buckets[k]) for k in BUCKET_ORDER],
        "trend_dates": [s.date.isoformat() for s in series],
        "trend_totals": [float(money(s.total)) for s in series],
        "composition": {k: [float(money(getattr(s, k))) for s in series] for k in BUCKET_ORDER},
        "has_history": len(series) > 1,
    }


@bp.route("/")
def index():
    return render_template("networth/index.html", **_context())


@bp.route("/panel")
def panel():
    return render_template("networth/_panel.html", **_context())


@bp.route("/snapshot", methods=["POST"])
def snapshot():
    snap = nw.take_snapshot()
    resp = make_response("", 204)
    resp.headers["HX-Trigger"] = json.dumps({
        "steward-refresh": True,
        "steward-toast": {"kind": "success", "message": f"Snapshot saved — net worth {snap.total}."},
    })
    return resp
