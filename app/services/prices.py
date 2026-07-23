"""Price fetching & caching.

Every fetch: 10s timeout, one retry, and on failure keep the last cached price
with its original fetched_at. Failures never raise to the caller.

Full network integrations (mfapi.in, yfinance) are wired in the investments
phases; the cache read/write plumbing below is used from day one.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from ..extensions import db
from ..models import PriceCache
from ..money import to_decimal, ZERO
from ..timeutil import now_ist

log = logging.getLogger("steward.prices")


# ---- cache helpers ---------------------------------------------------------
def get_cached(key: str) -> PriceCache | None:
    return PriceCache.query.filter_by(key=key).first()


def cached_price(key: str) -> Decimal | None:
    row = get_cached(key)
    return to_decimal(row.price, None) if row else None


def store_price(key: str, price, *, currency: str = "INR", as_of: date | None = None,
                ok: bool = True, meta: str = "") -> PriceCache:
    row = get_cached(key)
    if row is None:
        row = PriceCache(key=key)
        db.session.add(row)
    if ok:
        row.price = to_decimal(price, ZERO)
        row.currency = currency
        row.as_of = as_of
        row.fetched_at = now_ist().replace(tzinfo=None)
        row.ok = True
        row.meta = meta
    else:
        # keep last-known price/fetched_at; just note the failure
        row.ok = False
        if meta:
            row.meta = meta
    return row


# ---- refresh entry points (implemented in later phases) --------------------
def refresh_mutual_funds() -> dict[str, bool]:
    from .mf import refresh_all_navs
    return refresh_all_navs()


def refresh_gold() -> dict[str, bool]:
    from .gold import refresh_gold_rate
    return {"gold": refresh_gold_rate()}


def refresh_usdinr() -> dict[str, bool]:
    from .market import refresh_usdinr as _r
    return {"usdinr": _r()}


def refresh_stocks() -> dict[str, bool]:
    from .market import refresh_stock_prices
    return refresh_stock_prices()


def refresh_all() -> dict[str, bool]:
    results: dict[str, bool] = {}
    for fn in (refresh_usdinr, refresh_mutual_funds, refresh_gold, refresh_stocks):
        try:
            results.update(fn())
        except Exception as exc:  # never surface to the UI
            log.warning("refresh %s failed: %s", fn.__name__, exc)
    db.session.commit()
    return results
