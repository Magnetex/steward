"""Mutual funds: mfapi.in integration, holding valuation, P/L, XIRR.

Network calls are defensive (10s timeout, one retry) and never raise to the UI.
The UI reads current NAV from the PriceCache; refresh jobs/buttons populate it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import requests

from ..extensions import db
from ..models import MutualFundHolding, MFTransaction
from ..money import ZERO, money, to_decimal
from ..timeutil import today_ist, parse_date
from .prices import store_price, cached_price
from .xirr import xirr

log = logging.getLogger("steward.mf")

BASE = "https://api.mfapi.in/mf"
TIMEOUT = 10


def _get(url: str, params=None):
    """GET with one retry; returns parsed JSON or None on failure."""
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("mfapi GET %s failed (try %d): %s", url, attempt + 1, exc)
    return None


# ---- network ---------------------------------------------------------------
def search_schemes(query: str) -> list[dict]:
    if not query or len(query.strip()) < 3:
        return []
    data = _get(f"{BASE}/search", params={"q": query.strip()})
    if not data:
        return []
    out = []
    for item in data[:25]:
        out.append({"scheme_code": str(item.get("schemeCode")),
                    "scheme_name": item.get("schemeName", "")})
    return out


def _parse_history(payload) -> list[tuple[date, Decimal]]:
    rows = []
    for d in (payload or {}).get("data", []):
        try:
            dt = datetime.strptime(d["date"], "%d-%m-%Y").date()
            rows.append((dt, to_decimal(d["nav"], ZERO)))
        except (ValueError, KeyError):
            continue
    rows.sort(key=lambda x: x[0])
    return rows


def fetch_scheme(scheme_code: str) -> dict | None:
    """Full mfapi payload for a scheme (meta + history)."""
    return _get(f"{BASE}/{scheme_code}")


def latest_nav(scheme_code: str) -> tuple[Decimal, date] | None:
    payload = fetch_scheme(scheme_code)
    hist = _parse_history(payload)
    if not hist:
        return None
    d, nav = hist[-1]
    return nav, d


def nav_as_of(scheme_code: str, on: date) -> tuple[Decimal, date] | None:
    """NAV on the given date, or the most recent trading day before it."""
    payload = fetch_scheme(scheme_code)
    hist = _parse_history(payload)
    prior = [(d, nav) for d, nav in hist if d <= on]
    if not prior:
        return None
    return prior[-1][1], prior[-1][0]


def nav_history(scheme_code: str) -> list[tuple[date, Decimal]]:
    """Full (date, NAV) history, ascending. Empty on a failed fetch.

    Fetch once and reuse for many date lookups (e.g. SIP backfill) instead of
    hitting the network per month.
    """
    return _parse_history(fetch_scheme(scheme_code))


def nav_on(history: list[tuple[date, Decimal]], on: date) -> Decimal | None:
    """NAV as of ``on`` from a pre-fetched ``history`` (most recent day <= on)."""
    prior = [nav for d, nav in history if d <= on]
    return prior[-1] if prior else None


def refresh_nav(scheme_code: str) -> bool:
    res = latest_nav(scheme_code)
    if res is None:
        store_price(f"mf:{scheme_code}", 0, ok=False)
        return False
    nav, d = res
    store_price(f"mf:{scheme_code}", nav, currency="INR", as_of=d)
    return True


def refresh_all_navs() -> dict[str, bool]:
    out = {}
    codes = {h.scheme_code for h in MutualFundHolding.query.all()}
    for code in codes:
        out[f"mf:{code}"] = refresh_nav(code)
    db.session.commit()
    return out


# ---- valuation -------------------------------------------------------------
def current_nav(scheme_code: str) -> Decimal | None:
    return cached_price(f"mf:{scheme_code}")


def holding_metrics(holding: MutualFundHolding) -> dict:
    units = ZERO
    bought = ZERO
    sold = ZERO
    for t in holding.transactions:
        u = to_decimal(t.units, ZERO)
        a = money(t.amount)
        if t.type == "sell":
            units -= u
            sold += a
        else:
            units += u
            bought += a
    net_invested = bought - sold
    nav = current_nav(holding.scheme_code)
    current_value = money(units * nav) if nav is not None else None
    pl = (current_value - net_invested) if current_value is not None else None
    pl_pct = None
    if pl is not None and net_invested > 0:
        pl_pct = (pl / net_invested * 100).quantize(Decimal("0.01"))

    # XIRR: buys negative, sells positive, current value positive today
    flows = []
    for t in holding.transactions:
        amt = money(t.amount)
        flows.append((t.date, amt if t.type == "sell" else -amt))
    if current_value is not None and units > 0:
        flows.append((today_ist(), current_value))
    rate = xirr(flows) if len(flows) >= 2 else None

    nav_row = None
    from .prices import get_cached
    row = get_cached(f"mf:{holding.scheme_code}")
    if row:
        nav_row = {"nav": to_decimal(row.price, ZERO), "as_of": row.as_of, "ok": row.ok}

    return {
        "units": units.quantize(Decimal("0.0001")),
        "invested": money(net_invested),
        "current_value": current_value,
        "nav": nav, "nav_row": nav_row,
        "pl": pl, "pl_pct": pl_pct, "xirr": rate,
        "bought": money(bought), "sold": money(sold),
    }


def total_current_value() -> Decimal:
    total = ZERO
    for h in MutualFundHolding.query.all():
        m = holding_metrics(h)
        if m["current_value"] is not None:
            total += m["current_value"]
    return money(total)


def total_invested() -> Decimal:
    total = ZERO
    for h in MutualFundHolding.query.all():
        total += holding_metrics(h)["invested"]
    return money(total)
