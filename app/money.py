"""Exact money & quantity handling.

Rule from the spec: use ``Decimal`` for all money and unit math — never floats.

SQLite has no exact decimal type, so we store every Decimal as plain text and
read it straight back as a Decimal. That keeps values exact (no float round
trips). All aggregation happens in Python with Decimal, never in SQL, so the
lack of numeric ordering on TEXT columns never bites us.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

# Common quantizers
TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")


class DecimalText(TypeDecorator):
    """Store a Decimal losslessly as TEXT, read it back as a Decimal."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        # 'f' formatting avoids scientific notation like 1E+2
        return format(value, "f")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


def to_decimal(value, default: Decimal | None = ZERO) -> Decimal | None:
    """Coerce user input / None into a Decimal. Empty -> default."""
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return default


def money(value) -> Decimal:
    """Quantize to paise (2dp), rounding half up. Always returns a Decimal."""
    d = to_decimal(value, ZERO)
    return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def quantize4(value) -> Decimal:
    """Quantize to 4dp (units, grams, NAV)."""
    d = to_decimal(value, ZERO)
    return d.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def fmt_inr(value, *, paise: bool = True) -> str:
    """Format a Decimal/number as an Indian-grouped ₹ string.

    12,34,567.89 style grouping (Indian lakh/crore).
    """
    if value is None:
        value = ZERO
    d = money(value) if paise else to_decimal(value, ZERO)
    neg = d < 0
    d = abs(d)
    whole = int(d)
    frac = (d - whole)
    # Indian grouping: last 3 digits, then groups of 2
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        import re
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        grouped = f"{head},{tail}"
    else:
        grouped = s
    if paise:
        cents = f"{frac:.2f}"[2:]  # two digits after the dot
        out = f"₹{grouped}.{cents}"
    else:
        out = f"₹{grouped}"
    return f"-{out}" if neg else out
