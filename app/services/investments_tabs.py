"""Context builders for the Gold / Deposits / EPF / Stock tabs."""
from __future__ import annotations

from ..models import GoldHolding, GoldTransaction, StockHolding, EPFAccount
from ..timeutil import today_ist
from . import gold as gold_svc
from . import deposits as dep_svc
from . import epf as epf_svc
from . import market as market_svc
from .settings import get_decimal


def context_for(tab: str) -> dict:
    if tab == "gold":
        return _gold()
    if tab == "deposits":
        return _deposits()
    if tab == "epf":
        return _epf()
    if tab == "stock":
        return _stock()
    return {}


def _gold() -> dict:
    holding = GoldHolding.query.first()
    txns = (GoldTransaction.query.order_by(GoldTransaction.date.desc()).all())
    return {"gold": gold_svc.summary(), "gold_txns": txns,
            "gold_holding_id": holding.id if holding else None,
            "today": today_ist().isoformat()}


def _deposits() -> dict:
    summaries = dep_svc.all_summaries()
    closed = [s for s in dep_svc.all_summaries(include_closed=True)
              if s["deposit"].closed_on]
    return {"deposits": summaries, "closed_deposits": closed,
            "dep_total_accrued": dep_svc.total_accrued(),
            "dep_total_maturity": dep_svc.total_maturity(),
            "today": today_ist().isoformat()}


def _epf() -> dict:
    accounts = []
    for a in EPFAccount.query.all():
        accounts.append({"account": a, "series": epf_svc.running_series(a),
                         "balance": epf_svc.account_balance(a)})
    return {"epf_accounts": accounts, "epf_total": epf_svc.total_balance(),
            "epf_rate": get_decimal("epf_interest_rate"),
            "epf_fy_contrib": epf_svc.employee_contrib_for_fy(),
            "today": today_ist().isoformat()}


def _stock() -> dict:
    rows = [{"h": h, "m": market_svc.stock_metrics(h)} for h in StockHolding.query.all()]
    return {"stocks": rows, "stock_total_inr": market_svc.stock_total_inr(),
            "usdinr": market_svc.usdinr(), "today": today_ist().isoformat()}
