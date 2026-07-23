"""Alert center: create/dedupe/read alerts. Used by budgets, recurring,
deposits (maturities) and the nav bell.
"""
from __future__ import annotations

from datetime import date

from ..extensions import db
from ..models import Alert


def add_alert(type_: str, message: str, *, due_date: date | None = None,
              dedupe_key: str | None = None, action: str = "", ref_id: int | None = None) -> Alert | None:
    """Create an alert unless an unread one with the same dedupe_key exists."""
    if dedupe_key:
        existing = Alert.query.filter_by(dedupe_key=dedupe_key, is_read=False).first()
        if existing:
            return existing
    a = Alert(type=type_, message=message, due_date=due_date,
              dedupe_key=dedupe_key, action=action, ref_id=ref_id)
    db.session.add(a)
    return a


def unread_count() -> int:
    return Alert.query.filter_by(is_read=False).count()


def recent(limit: int = 30):
    return Alert.query.order_by(Alert.is_read.asc(), Alert.created_at.desc()).limit(limit).all()


def mark_read(alert_id: int) -> None:
    a = db.session.get(Alert, alert_id)
    if a:
        a.is_read = True
        db.session.commit()


def mark_all_read() -> None:
    Alert.query.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()


def sweep_all() -> None:
    """Scheduled sweep: regenerate maturity + overshoot alerts. Filled in as
    those modules land; safe to call any time."""
    try:
        from .deposits import sweep_maturity_alerts
        sweep_maturity_alerts()
    except Exception:
        pass
    try:
        from .budget import compute_budget
        from ..timeutil import today_ist, month_start
        _ = compute_budget(month_start(today_ist()))
    except Exception:
        pass
    db.session.commit()
