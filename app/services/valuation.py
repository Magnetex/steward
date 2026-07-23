"""Current INR valuation of each investment bucket.

Each function is implemented in its module's phase; until then it returns 0 so
net-worth and the dashboard glance degrade gracefully. All read from the price
cache — never the network.
"""
from __future__ import annotations

from decimal import Decimal

from ..money import ZERO


def mf_total_value() -> Decimal:
    try:
        from .mf import total_current_value
        return total_current_value()
    except Exception:
        return ZERO


def mf_total_invested() -> Decimal:
    try:
        from .mf import total_invested
        return total_invested()
    except Exception:
        return ZERO


def gold_value() -> Decimal:
    try:
        from .gold import current_value
        return current_value()
    except Exception:
        return ZERO


def deposits_accrued_total() -> Decimal:
    try:
        from .deposits import total_accrued
        return total_accrued()
    except Exception:
        return ZERO


def epf_balance_total() -> Decimal:
    try:
        from .epf import total_balance
        return total_balance()
    except Exception:
        return ZERO


def stock_value_inr() -> Decimal:
    try:
        from .market import stock_total_inr
        return stock_total_inr()
    except Exception:
        return ZERO
