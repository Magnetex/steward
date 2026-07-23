"""USD→INR and US stock prices via yfinance. Defensive; never raises to the UI.

The UI reads cached values; these functions run only from refresh jobs/buttons.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from ..extensions import db
from ..models import StockHolding
from ..money import ZERO, money, to_decimal, quantize4
from .prices import store_price, cached_price, get_cached

log = logging.getLogger("steward.market")

USDINR_KEY = "fx:usdinr"
USDINR_FALLBACK = Decimal("86.00")


def _yf_last_price(symbol: str) -> Decimal | None:
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if hist is not None and not hist.empty:
            return to_decimal(float(hist["Close"].dropna().iloc[-1]), None)
        fi = getattr(t, "fast_info", None)
        if fi and fi.get("last_price"):
            return to_decimal(float(fi["last_price"]), None)
    except Exception as exc:  # noqa: BLE001
        log.warning("yfinance %s failed: %s", symbol, exc)
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
