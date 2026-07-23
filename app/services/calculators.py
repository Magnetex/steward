"""Deposit maturity/accrual math (FD compound interest, RD quarterly compounding).

Money stays Decimal; the compounding *factor* is computed in float (a rate is
not an exact decimal) then applied to the Decimal principal and quantized.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..money import money, ZERO, to_decimal
from ..timeutil import add_months, today_ist

COMPOUND_N = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}


def maturity_date(start: date, tenure_months: int) -> date:
    return add_months(start, tenure_months)


def _elapsed_months(start: date, as_of: date, cap: int) -> int:
    if as_of <= start:
        return 0
    months = (as_of.year - start.year) * 12 + (as_of.month - start.month)
    if as_of.day < start.day:
        months -= 1
    return max(0, min(months, cap))


# ---- Fixed deposit ---------------------------------------------------------
def fd_value(principal, annual_rate_pct, compounding: str, months: int) -> Decimal:
    """FD value after ``months`` months: P(1 + r/n)^(n·t)."""
    P = to_decimal(principal, ZERO)
    r = float(to_decimal(annual_rate_pct, ZERO)) / 100.0
    n = COMPOUND_N.get(compounding, 4)
    t = months / 12.0
    factor = (1.0 + r / n) ** (n * t)
    return money(P * Decimal(str(factor)))


def fd_maturity(deposit) -> Decimal:
    return fd_value(deposit.principal, deposit.interest_rate, deposit.compounding,
                    deposit.tenure_months)


def fd_accrued(deposit, as_of: date | None = None) -> Decimal:
    as_of = as_of or today_ist()
    elapsed = _elapsed_months(deposit.start_date, as_of, deposit.tenure_months)
    return fd_value(deposit.principal, deposit.interest_rate, deposit.compounding, elapsed)


# ---- Recurring deposit -----------------------------------------------------
def rd_value(installment, annual_rate_pct, total_months: int, deposited_months: int | None = None) -> Decimal:
    """RD value with quarterly compounding.

    Each monthly installment k (deposited at month k) grows for the months
    remaining until maturity, compounded quarterly. When ``deposited_months`` is
    given (< total), computes the accrued value of installments paid so far,
    grown to that point in time.
    """
    R = to_decimal(installment, ZERO)
    q = float(to_decimal(annual_rate_pct, ZERO)) / 400.0  # quarterly rate
    if deposited_months is None:
        # maturity: N installments, installment k grows for (N-k+1) months
        n = total_months
        total = ZERO
        for k in range(1, n + 1):
            m = n - k + 1
            total += R * Decimal(str((1.0 + q) ** (m / 3.0)))
        return money(total)
    # accrued to 'deposited_months': installments 1..d, each grown for (d-k+1) months
    d = max(0, min(deposited_months, total_months))
    total = ZERO
    for k in range(1, d + 1):
        m = d - k + 1
        total += R * Decimal(str((1.0 + q) ** (m / 3.0)))
    return money(total)


def rd_maturity(deposit) -> Decimal:
    return rd_value(deposit.installment, deposit.interest_rate, deposit.tenure_months)


def rd_accrued(deposit, as_of: date | None = None) -> Decimal:
    as_of = as_of or today_ist()
    elapsed = _elapsed_months(deposit.start_date, as_of, deposit.tenure_months)
    return rd_value(deposit.installment, deposit.interest_rate, deposit.tenure_months,
                    deposited_months=elapsed)


# ---- Unified deposit summary ----------------------------------------------
def deposit_summary(deposit, as_of: date | None = None) -> dict:
    as_of = as_of or today_ist()
    mat_date = maturity_date(deposit.start_date, deposit.tenure_months)
    if deposit.kind == "RD":
        maturity = rd_maturity(deposit)
        accrued = rd_accrued(deposit, as_of)
        invested_so_far = money(to_decimal(deposit.installment, ZERO) *
                                _elapsed_months(deposit.start_date, as_of, deposit.tenure_months))
        principal_total = money(to_decimal(deposit.installment, ZERO) * deposit.tenure_months)
    else:
        maturity = fd_maturity(deposit)
        accrued = fd_accrued(deposit, as_of)
        invested_so_far = money(deposit.principal)
        principal_total = money(deposit.principal)
    days_left = (mat_date - as_of).days
    total_days = max((mat_date - deposit.start_date).days, 1)
    elapsed_days = max(0, min((as_of - deposit.start_date).days, total_days))
    months_elapsed = _elapsed_months(deposit.start_date, as_of, deposit.tenure_months)
    return {
        "deposit": deposit, "maturity_date": mat_date, "maturity_value": maturity,
        "accrued_value": accrued, "days_left": days_left,
        "invested_so_far": invested_so_far, "principal_total": principal_total,
        "interest": money(maturity - principal_total),
        "months_elapsed": months_elapsed,
        "progress_pct": int(elapsed_days / total_days * 100),
        "matured": days_left <= 0,
    }
