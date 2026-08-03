"""USD→INR and US stock prices from Yahoo's chart API. Never raises to the UI.

Plain HTTP rather than the ``yfinance`` package: that pulls in pandas and
numpy, the only compiled dependencies in the tree, for what amounts to one
JSON lookup. Dropping it keeps the install pure-Python, which matters on
Android/Termux where building numpy from source is slow and often fails.

The UI reads cached values; these functions run only from refresh jobs/buttons.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import requests

from ..extensions import db
from ..models import StockHolding
from ..money import ZERO, money, to_decimal, quantize4
from .prices import store_price, cached_price, get_cached

log = logging.getLogger("steward.market")

USDINR_KEY = "fx:usdinr"
USDINR_FALLBACK = Decimal("86.00")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TIMEOUT = 10
# Yahoo rejects requests without a browser-ish User-Agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BuildSteward/1.0)"}


def _yf_last_price(symbol: str) -> Decimal | None:
    """Latest price for a Yahoo symbol, or None if it can't be fetched.

    Prefers the quote in ``meta``; falls back to the most recent non-null
    close, which is what shows up outside market hours.
    """
    for attempt in range(2):
        try:
            r = requests.get(CHART_URL.format(symbol=symbol),
                             params={"range": "5d", "interval": "1d"},
                             headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            results = ((r.json().get("chart") or {}).get("result")) or []
            if not results:
                return None
            block = results[0]

            price = (block.get("meta") or {}).get("regularMarketPrice")
            if price:
                return to_decimal(float(price), None)

            quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]
            closes = [c for c in (quote.get("close") or []) if c is not None]
            if closes:
                return to_decimal(float(closes[-1]), None)
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("yahoo %s failed (try %d): %s", symbol, attempt + 1, exc)
    return None


def refresh_usdinr() -> bool:
    price = _yf_last_price("USDINR=X")
    if price is None:
        store_price(USDINR_KEY, 0, currency="USD", ok=False)
        return False
    store_price(USDINR_KEY, price, currency="USD", meta="USDINR=X")
    return True


def usdinr() -> Decimal:
    return cached_price(USDINR_KEY) or USDINR_FALLBACK


def refresh_stock_prices() -> dict[str, bool]:
    out = {}
    for h in StockHolding.query.all():
        price = _yf_last_price(h.ticker)
        if price is None:
            store_price(f"stock:{h.ticker}", 0, currency="USD", ok=False)
            out[f"stock:{h.ticker}"] = False
        else:
            store_price(f"stock:{h.ticker}", price, currency="USD", meta=h.name or h.ticker)
            out[f"stock:{h.ticker}"] = True
    db.session.commit()
    return out


# ---- valuation -------------------------------------------------------------
def stock_metrics(holding: StockHolding) -> dict:
    qty = ZERO
    cost_usd = ZERO
    for t in holding.transactions:
        qty += to_decimal(t.qty, ZERO)
        cost_usd += to_decimal(t.qty, ZERO) * to_decimal(t.price_usd, ZERO)
    price = cached_price(f"stock:{holding.ticker}")
    row = get_cached(f"stock:{holding.ticker}")
    fx = usdinr()
    avg_cost = (cost_usd / qty).quantize(Decimal("0.01")) if qty > 0 else ZERO
    value_usd = (qty * price) if price is not None else None
    value_inr = money(value_usd * fx) if value_usd is not None else None
    invested_inr = money(cost_usd * fx)
    pl_usd = (value_usd - cost_usd) if value_usd is not None else None
    pl_pct = ((pl_usd / cost_usd * 100).quantize(Decimal("0.01"))
              if (pl_usd is not None and cost_usd > 0) else None)
    return {
        "qty": qty.quantize(Decimal("0.0001")), "avg_cost_usd": avg_cost,
        "price_usd": price, "value_usd": (value_usd.quantize(Decimal("0.01")) if value_usd is not None else None),
        "value_inr": value_inr, "invested_inr": invested_inr,
        "cost_usd": cost_usd.quantize(Decimal("0.01")),
        "pl_usd": (pl_usd.quantize(Decimal("0.01")) if pl_usd is not None else None),
        "pl_pct": pl_pct, "fx": fx, "as_of": row.as_of if row else None,
        "price_ok": row.ok if row else False,
    }


def stock_total_inr() -> Decimal:
    total = ZERO
    for h in StockHolding.query.all():
        v = stock_metrics(h)["value_inr"]
        if v is not None:
            total += v
    return money(total)
