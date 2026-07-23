"""Capital-gains (FIFO) and 80C computations.

Rates come from Settings (seeded with current Indian defaults, user-editable).
This is a report, not tax advice — the page shows a visible verify-the-law note.
FIFO matches each sell against the oldest buy lots.
"""
from __future__ import annotations

from collections import deque
from datetime import date
from decimal import Decimal

from ..models import MutualFundHolding, GoldHolding, MFTransaction
from ..money import ZERO, money, to_decimal
from ..timeutil import months_between, financial_year_bounds, today_ist
from .settings import get_decimal, get_int
from . import epf as epf_svc


def _mf_events() -> list[dict]:
    """Realized-gain events across all MF holdings (FIFO)."""
    events = []
    for h in MutualFundHolding.query.all():
        lots: deque[list] = deque()  # [date, units_left, nav]
        for t in sorted(h.transactions, key=lambda x: (x.date, x.id)):
            units = to_decimal(t.units, ZERO)
            nav = to_decimal(t.nav, ZERO)
            if t.type in ("buy", "sip"):
                if units > 0:
                    lots.append([t.date, units, nav])
            elif t.type == "sell":
                remaining = units
                while remaining > 0 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot[1])
                    cost = money(matched * lot[2])
                    proceeds = money(matched * nav)
                    gain = money(proceeds - cost)
                    m = months_between(lot[0], t.date)
                    if h.asset_type == "equity":
                        term = "long" if m >= get_int("equity_ltcg_months", 12) else "short"
                        bucket = "equity_ltcg" if term == "long" else "equity_stcg"
                    else:  # debt -> slab regardless of term
                        term = "slab"
                        bucket = "debt"
                    events.append({
                        "asset": "MF", "name": h.scheme_name, "sell_date": t.date,
                        "buy_date": lot[0], "units": matched, "cost": cost,
                        "proceeds": proceeds, "gain": gain, "months": m,
                        "term": term, "bucket": bucket,
                    })
                    lot[1] -= matched
                    remaining -= matched
                    if lot[1] <= 0:
                        lots.popleft()
    return events


def _gold_events() -> list[dict]:
    events = []
    ltcg_months = get_int("gold_ltcg_months", 24)
    for h in GoldHolding.query.all():
        lots: deque[list] = deque()  # [date, grams_left, price_per_gram]
        for t in sorted(h.transactions, key=lambda x: (x.date, x.id)):
            grams = to_decimal(t.grams, ZERO)
            ppg = to_decimal(t.price_per_gram, ZERO)
            if t.type == "buy":
                if grams > 0:
                    lots.append([t.date, grams, ppg])
            elif t.type == "sell":
                remaining = grams
                while remaining > 0 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot[1])
                    cost = money(matched * lot[2])
                    proceeds = money(matched * ppg)
                    gain = money(proceeds - cost)
                    m = months_between(lot[0], t.date)
                    term = "long" if m >= ltcg_months else "short"
                    bucket = "gold_ltcg" if term == "long" else "gold_slab"
                    events.append({
                        "asset": "Gold", "name": "Digital gold", "sell_date": t.date,
                        "buy_date": lot[0], "units": matched, "cost": cost,
                        "proceeds": proceeds, "gain": gain, "months": m,
                        "term": term, "bucket": bucket,
                    })
                    lot[1] -= matched
                    remaining -= matched
                    if lot[1] <= 0:
                        lots.popleft()
    return events


def capital_gains(fy_date: date | None = None) -> dict:
    fy_date = fy_date or today_ist()
    start, end = financial_year_bounds(fy_date)
    events = [e for e in (_mf_events() + _gold_events()) if start <= e["sell_date"] <= end]
    events.sort(key=lambda e: e["sell_date"])

    buckets = {k: ZERO for k in ("equity_ltcg", "equity_stcg", "debt", "gold_ltcg", "gold_slab")}
    for e in events:
        buckets[e["bucket"]] += e["gain"]

    equity_exemption = get_decimal("equity_ltcg_exemption", Decimal("125000"))
    rates = {
        "equity_ltcg": get_decimal("equity_ltcg_rate", Decimal("12.5")),
        "equity_stcg": get_decimal("equity_stcg_rate", Decimal("20")),
        "debt": get_decimal("debt_slab_rate", Decimal("30")),
        "gold_ltcg": get_decimal("gold_ltcg_rate", Decimal("12.5")),
        "gold_slab": get_decimal("gold_slab_rate", Decimal("30")),
    }

    summary = {}
    total_tax = ZERO
    for key, gain in buckets.items():
        gain = money(gain)
        taxable = gain
        if key == "equity_ltcg":
            taxable = money(max(gain - equity_exemption, ZERO))
        else:
            taxable = money(max(gain, ZERO))
        tax = money(taxable * rates[key] / Decimal(100))
        total_tax += tax
        summary[key] = {"gain": gain, "taxable": taxable, "rate": rates[key], "tax": tax}

    return {
        "start": start, "end": end, "events": events, "buckets": summary,
        "total_gain": money(sum(buckets.values(), ZERO)),
        "total_tax": money(total_tax),
        "equity_exemption": equity_exemption,
    }


def sec_80c(fy_date: date | None = None) -> dict:
    """FY total of EPF employee contributions + anything tagged 80C."""
    fy_date = fy_date or today_ist()
    start, end = financial_year_bounds(fy_date)
    epf_amt = epf_svc.employee_contrib_for_fy(fy_date)

    tagged = ZERO
    for t in MFTransaction.query.all():
        if "80c" in (t.tags or "").lower() and start <= t.date <= end and t.type in ("buy", "sip"):
            tagged += money(t.amount)

    limit = get_decimal("sec80c_limit", Decimal("150000"))
    used = money(epf_amt + tagged)
    return {
        "start": start, "end": end, "epf": money(epf_amt), "tagged": money(tagged),
        "used": used, "limit": money(limit),
        "remaining": money(max(limit - used, ZERO)),
        "pct": min(int((used / limit * 100).to_integral_value()) if limit > 0 else 0, 100),
    }


BUCKET_LABELS = {
    "equity_ltcg": "Equity MF · LTCG", "equity_stcg": "Equity MF · STCG",
    "debt": "Debt MF · slab", "gold_ltcg": "Gold · LTCG", "gold_slab": "Gold · slab",
}
