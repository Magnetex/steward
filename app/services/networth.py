"""Net-worth valuation and snapshots."""
from __future__ import annotations

from decimal import Decimal

from ..extensions import db
from ..models import NetWorthSnapshot
from ..money import ZERO, money
from ..timeutil import today_ist
from . import accounts, valuation


BUCKET_LABELS = {
    "cash_bank": "Cash & bank",
    "mf": "Mutual funds",
    "gold": "Gold",
    "deposits": "Deposits",
    "epf": "EPF",
    "stock": "Stock",
}


def current_buckets() -> dict[str, Decimal]:
    """Live valuation of every net-worth bucket (INR).

    Sinking funds are NOT a bucket — they only earmark slices of the assets
    below (and cash), so counting them would double the money.
    """
    return {
        "cash_bank": money(accounts.available_total()),
        "mf": money(valuation.mf_total_value()),
        "gold": money(valuation.gold_value()),
        "deposits": money(valuation.deposits_accrued_total()),
        "epf": money(valuation.epf_balance_total()),
        "stock": money(valuation.stock_value_inr()),
    }


def current_total() -> Decimal:
    return money(sum(current_buckets().values(), ZERO))


def take_snapshot(on: "date | None" = None) -> NetWorthSnapshot:
    from datetime import date  # local import for the annotation default
    d = on or today_ist()
    buckets = current_buckets()
    total = money(sum(buckets.values(), ZERO))
    snap = NetWorthSnapshot.query.filter_by(date=d).first()
    if snap is None:
        snap = NetWorthSnapshot(date=d)
        db.session.add(snap)
    for k, v in buckets.items():
        setattr(snap, k, v)
    snap.total = total
    db.session.commit()
    return snap


def snapshot_series(limit: int = 90):
    return (
        NetWorthSnapshot.query.order_by(NetWorthSnapshot.date.desc())
        .limit(limit).all()[::-1]
    )
