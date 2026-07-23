"""Gold: grams held, valuation, and the INR/gram rate.

Rate = manual override (Setting 'gold_manual_rate') when set, else the market
rate cached from yfinance GC=F (USD/troy oz) × USDINR ÷ 31.1035 g/oz.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from ..extensions import db
from ..models import GoldHolding, GoldTransaction
from ..money import ZERO, money, to_decimal, quantize4
from .prices import store_price, cached_price, get_cached
from .settings import gold_manual_rate
from .market import _yf_last_price, usdinr

log = logging.getLogger("steward.gold")

GRAMS_PER_OZ = Decimal("31.1035")
MARKET_KEY = "gold:inr_per_gram"


def refresh_gold_rate() -> bool:
    """Derive INR/gram from GC=F × USDINR ÷ 31.1035 and cache it."""
    usd_per_oz = _yf_last_price("GC=F")
    fx = usdinr()
    if usd_per_oz is None or fx is None:
        store_price(MARKET_KEY, 0, ok=False)
        return False
    inr_per_gram = money(usd_per_oz * fx / GRAMS_PER_OZ)
    store_price(MARKET_KEY, inr_per_gram, currency="INR", meta="GC=F x USDINR / 31.1035")
    return True


def market_rate() -> Decimal | None:
    return cached_price(MARKET_KEY)


def current_rate() -> Decimal | None:
    """Effective rate: manual override wins, else market."""
    manual = gold_manual_rate()
    if manual is not None:
        return manual
    return market_rate()


def summary() -> dict:
    grams = ZERO
    bought = ZERO
    sold = ZERO
    sold_grams = ZERO
    for h in GoldHolding.query.all():
        for t in h.transactions:
            g = to_decimal(t.grams, ZERO)
            a = money(t.amount)
            if t.type == "sell":
                grams -= g; sold += a; sold_grams += g
            else:
                grams += g; bought += a
    bought_grams = grams + sold_grams
    avg_price = (bought / bought_grams).quantize(Decimal("0.01")) if bought_grams > 0 else ZERO
    net_invested = bought - sold
    rate = current_rate()
    value = money(grams * rate) if rate is not None else None
    pl = (value - net_invested) if value is not None else None
    pl_pct = (pl / net_invested * 100).quantize(Decimal("0.01")) if (pl is not None and net_invested > 0) else None
    row = get_cached(MARKET_KEY)
    return {
        "grams": quantize4(grams), "avg_price": avg_price, "invested": money(net_invested),
        "rate": rate, "manual": gold_manual_rate() is not None,
        "value": value, "pl": pl, "pl_pct": pl_pct,
        "as_of": row.as_of if row else None, "rate_ok": (row.ok if row else False) or gold_manual_rate() is not None,
        "provider": (GoldHolding.query.first().provider if GoldHolding.query.first() else "PhonePe / SafeGold"),
    }


def current_value() -> Decimal:
    s = summary()
    return s["value"] or ZERO
