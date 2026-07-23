"""XIRR: annualized internal rate of return for irregular cashflows.

Cashflows are (date, amount) with negative = outflow (buy), positive = inflow
(sell / current value). Returns an annual rate as a Decimal percentage, or None
if it can't converge. The solver uses floats (a rate is not an exact decimal),
but the input amounts come from Decimals.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def _npv(rate: float, flows: list[tuple[date, float]], t0: date) -> float:
    total = 0.0
    for d, amt in flows:
        years = (d - t0).days / 365.0
        total += amt / ((1.0 + rate) ** years)
    return total


def xirr(cashflows: list[tuple[date, Decimal]]) -> Decimal | None:
    """Return the annual XIRR as a percentage Decimal (e.g. 14.37), or None."""
    if len(cashflows) < 2:
        return None
    flows = [(d, float(a)) for d, a in cashflows]
    # need at least one positive and one negative flow
    if not (any(a > 0 for _, a in flows) and any(a < 0 for _, a in flows)):
        return None
    t0 = min(d for d, _ in flows)

    # Newton-Raphson with a numerical derivative; fall back to bisection.
    rate = 0.1
    for _ in range(100):
        f = _npv(rate, flows, t0)
        h = 1e-6
        df = (_npv(rate + h, flows, t0) - f) / h
        if df == 0:
            break
        new_rate = rate - f / df
        if new_rate <= -0.9999:
            new_rate = (rate - 0.9999) / 2  # keep it in a valid domain
        if abs(new_rate - rate) < 1e-8:
            rate = new_rate
            break
        rate = new_rate
    else:
        rate = None

    if rate is None or abs(_npv(rate, flows, t0)) > 1e-3:
        rate = _bisect(flows, t0)
    if rate is None:
        return None
    return Decimal(str(round(rate * 100, 2)))


def _bisect(flows, t0) -> float | None:
    lo, hi = -0.9999, 10.0
    flo = _npv(lo, flows, t0)
    fhi = _npv(hi, flows, t0)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = _npv(mid, flows, t0)
        if abs(fm) < 1e-7:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2
