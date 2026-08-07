"""Typed access to the key/value Setting store, with sensible defaults.

Tax defaults are seeded to current Indian rules but are user-configurable; the
Tax page shows a visible 'verify against current law' note.
"""
from __future__ import annotations

from decimal import Decimal

from ..models import Setting
from ..money import to_decimal

# key -> default value (as string). Empty string means "unset".
DEFAULTS: dict[str, str] = {
    "theme": "light",
    "salary_rule_window": "7",         # days at month-end that push income to next month
    "epf_interest_rate": "8.25",       # annual %
    "gold_manual_rate": "",            # INR/gram override; empty = use market fetch
    # GST charged on a digital gold purchase, included in the amount debited
    # (3% at Aug 2026: 1.5% CGST + 1.5% SGST, unchanged by the Sept 2025 overhaul).
    "gold_gst_pct": "3",
    # Capital-gains tax rules (India defaults; user-editable)
    "equity_ltcg_months": "12",
    "equity_ltcg_rate": "12.5",
    "equity_ltcg_exemption": "125000",
    "equity_stcg_rate": "20",
    "debt_slab_rate": "30",
    "gold_ltcg_months": "24",
    "gold_ltcg_rate": "12.5",
    "gold_slab_rate": "30",
    "sec80c_limit": "150000",
}


def get_str(key: str) -> str:
    return Setting.get(key, DEFAULTS.get(key, ""))


def get_decimal(key: str, default: Decimal | None = None) -> Decimal | None:
    raw = Setting.get(key, DEFAULTS.get(key, ""))
    if raw in (None, ""):
        return default
    return to_decimal(raw, default)


def get_int(key: str, default: int = 0) -> int:
    raw = Setting.get(key, DEFAULTS.get(key, ""))
    try:
        return int(str(raw))
    except (ValueError, TypeError):
        return default


def salary_window_days() -> int:
    return get_int("salary_rule_window", 7)


def gold_gst_pct() -> Decimal:
    """GST on a digital gold buy, as a percentage of the pre-tax gold value."""
    return get_decimal("gold_gst_pct", Decimal("3")) or Decimal("0")


def gold_manual_rate() -> Decimal | None:
    raw = Setting.get("gold_manual_rate", "")
    if raw in (None, ""):
        return None
    return to_decimal(raw, None)


def all_settings() -> dict[str, str]:
    """Current effective settings (stored value or default) for the form."""
    out = dict(DEFAULTS)
    for row in Setting.query.all():
        if row.value not in (None, ""):
            out[row.key] = row.value
    return out
