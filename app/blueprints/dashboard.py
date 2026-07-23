"""Dashboard — budget-first landing page with htmx-refreshable regions."""
from __future__ import annotations

from flask import Blueprint, render_template

from ..models import Transaction
from ..money import ZERO, money
from ..timeutil import today_ist, month_start
from ..services import accounts, budget as budget_svc, networth as nw_svc

bp = Blueprint("dashboard", __name__)


def _networth_spark(current, today):
    """Trend of the last 30 snapshots, ending on today's live value.

    Snapshots only exist from 23:00 each day, so the final point is pinned to
    the live total — otherwise the sparkline would contradict the figure
    printed directly above it.
    """
    snaps = nw_svc.snapshot_series(30)
    points = [float(money(s.total)) for s in snaps]
    if snaps and snaps[-1].date == today:
        points[-1] = float(current)
    else:
        points.append(float(current))
    return points


def _summary_context():
    today = today_ist()
    month = month_start(today)
    b = budget_svc.compute_budget(month)
    spent = money(b["total_spent"] + b["unbudgeted"])
    # Value net worth live, the same way /networth/ does. Reading the most
    # recent snapshot here made the two pages disagree by whatever had changed
    # since the previous 23:00 job — and showed zero outright on a database
    # that had no snapshots yet.
    networth = nw_svc.current_total()
    spark = _networth_spark(networth, today)
    return {
        "available": accounts.available_total(),
        "income": b["income_received"], "spent": spent,
        "networth": networth, "spark": spark, "month": month,
    }


def _budget_context():
    month = month_start(today_ist())
    return {"budget": budget_svc.compute_budget(month), "month": month}


def _recent():
    return (Transaction.query.filter(Transaction.parent_id.is_(None))
            .order_by(Transaction.date.desc(), Transaction.id.desc()).limit(10).all())


def _glance():
    """Slim investments glance: MF, gold, next deposit maturity."""
    from ..services import mf as mf_svc, gold as gold_svc, deposits as dep_svc
    mf_value = mf_svc.total_current_value()
    mf_invested = mf_svc.total_invested()
    gold = gold_svc.summary()
    # soonest upcoming maturity
    upcoming = [s for s in dep_svc.all_summaries() if s["days_left"] > 0]
    upcoming.sort(key=lambda s: s["days_left"])
    next_dep = upcoming[0] if upcoming else None
    return {
        "mf_value": mf_value, "mf_pl": money(mf_value - mf_invested),
        "gold_grams": gold["grams"], "gold_value": gold["value"] or ZERO,
        "next_dep": next_dep,
    }


@bp.route("/")
def index():
    ctx = _summary_context()
    ctx.update(_budget_context())
    ctx["recent"] = _recent()
    ctx["glance"] = _glance()
    return render_template("dashboard/index.html", **ctx)


@bp.route("/dashboard/summary")
def summary():
    return render_template("dashboard/_summary.html", **_summary_context())


@bp.route("/dashboard/budget-panel")
def budget_panel():
    return render_template("dashboard/_budget_panel.html", **_budget_context())


@bp.route("/dashboard/recent")
def recent():
    return render_template("dashboard/_recent.html", recent=_recent())
