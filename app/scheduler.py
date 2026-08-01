"""APScheduler wiring for daily price refreshes, recurring materialization,
and net-worth snapshots. All times IST.

Jobs are thin wrappers that push an app context and call service functions.
Every fetch is defensive: a failure is logged and swallowed so the UI never
breaks (services keep last-known cached prices).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .timeutil import IST

log = logging.getLogger("steward.scheduler")

_scheduler: BackgroundScheduler | None = None


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone=IST, daemon=True)

    def job(fn_name):
        def runner():
            with app.app_context():
                try:
                    _run_named_job(fn_name)
                except Exception:  # never let a job crash the scheduler
                    log.exception("scheduled job %s failed", fn_name)
        return runner

    # MF NAVs publish after market close -> 21:30 IST
    sched.add_job(job("refresh_mf"), CronTrigger(hour=21, minute=30), id="refresh_mf",
                  replace_existing=True)
    # Gold + USDINR + stock -> 08:00 IST
    sched.add_job(job("refresh_market"), CronTrigger(hour=8, minute=0), id="refresh_market",
                  replace_existing=True)
    # Recurring rules materialized each morning
    sched.add_job(job("run_recurring"), CronTrigger(hour=6, minute=0), id="run_recurring",
                  replace_existing=True)
    # Net-worth snapshot -> 23:00 IST
    sched.add_job(job("snapshot"), CronTrigger(hour=23, minute=0), id="snapshot",
                  replace_existing=True)
    # Alert sweep (maturities, overshoots) a couple of times a day
    sched.add_job(job("sweep_alerts"), CronTrigger(hour="7,20", minute=15), id="sweep_alerts",
                  replace_existing=True)
    # Bank-SMS sweep at the end of the day, before the 23:00 snapshot. The
    # launcher also scans on start, so a day the server was down is covered
    # the next time the app is opened.
    sched.add_job(job("scan_sms"), CronTrigger(hour=22, minute=0), id="scan_sms",
                  replace_existing=True)

    sched.start()
    _scheduler = sched
    log.info("scheduler started")
    return sched


def _run_named_job(name: str) -> None:
    """Dispatch by name using lazy imports (services may load heavy deps)."""
    if name == "refresh_mf":
        from .services.prices import refresh_mutual_funds
        refresh_mutual_funds()
    elif name == "refresh_market":
        from .services.prices import refresh_gold, refresh_usdinr, refresh_stocks
        refresh_usdinr()
        refresh_gold()
        refresh_stocks()
    elif name == "run_recurring":
        from .services.recurring import materialize_due
        from .services.sip import run_due as run_sips
        from .services.rd import run_due as run_rds
        from .services.deposit_actions import close_matured
        materialize_due()
        run_sips()
        run_rds()
        close_matured()   # auto-deposit matured FD/RD proceeds into the bank account
    elif name == "snapshot":
        from .services.networth import take_snapshot
        take_snapshot()
    elif name == "sweep_alerts":
        from .services.alerts import sweep_all
        sweep_all()
    elif name == "scan_sms":
        # Only meaningful on the phone; a desktop install has no Termux:API
        # and simply skips rather than logging a failure every night.
        from .services.sms_import import scan, termux_available
        if termux_available():
            scan()
