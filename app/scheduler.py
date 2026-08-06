"""APScheduler wiring for daily price refreshes, recurring materialization,
and net-worth snapshots. All times IST.

Jobs are thin wrappers that push an app context and call service functions.
Every fetch is defensive: a failure is logged and swallowed so the UI never
breaks (services keep last-known cached prices).

A cron job only fires if the process happens to be alive at that minute, and
on the phone it usually is not — Termux runs while the app is open and stops
soon after. So every job also records when it last ran, and `catch_up()` runs
whatever is overdue shortly after start. Without it, opening the app for a
minute a day meant SIP and RD installments never posted, matured deposits
never closed, and the net-worth trend never gained a point.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .timeutil import IST, now_ist

log = logging.getLogger("steward.scheduler")

_scheduler: BackgroundScheduler | None = None

LAST_RUN_PREFIX = "job_last_run:"

# One source of truth: the cron triggers and the catch-up pass are both built
# from this. Times are IST, (hour, minute).
JOBS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("run_recurring", ((6, 0),)),      # rules, SIP/RD installments, matured deposits
    ("sweep_alerts", ((7, 15), (20, 15))),
    ("refresh_market", ((8, 0),)),     # gold + USDINR + stock
    ("auto_backup", ((21, 0),)),
    ("refresh_mf", ((21, 30),)),       # NAVs publish after market close
    ("scan_sms", ((22, 0),)),
    ("snapshot", ((23, 0),)),          # last, so it sees the day's changes
)


def start_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    sched = BackgroundScheduler(timezone=IST, daemon=True)
    for job_id, slots in JOBS:
        minutes = {m for _, m in slots}
        if len(minutes) == 1:                     # one trigger covers every slot
            sched.add_job(_runner(app, job_id),
                          CronTrigger(hour=",".join(str(h) for h, _ in slots),
                                      minute=slots[0][1]),
                          id=job_id, replace_existing=True)
        else:                                     # slots at different minutes
            for i, (hour, minute) in enumerate(slots):
                sched.add_job(_runner(app, job_id), CronTrigger(hour=hour, minute=minute),
                              id="%s:%d" % (job_id, i), replace_existing=True)

    sched.start()
    _scheduler = sched
    log.info("scheduler started")

    # Off the request thread: catch-up can fetch prices and take a backup, and
    # the page that triggered start-up should not wait for any of it.
    threading.Thread(target=catch_up, args=(app,), daemon=True,
                     name="steward-catchup").start()
    return sched


def _runner(app, job_id):
    def run():
        with app.app_context():
            _run_and_mark(job_id)
    return run


def _run_and_mark(job_id: str) -> bool:
    """Run one job and record when. Returns whether it got through cleanly."""
    from .extensions import db
    from .models import Setting
    try:
        _run_named_job(job_id)
    except Exception:            # never let a job crash the scheduler
        log.exception("scheduled job %s failed", job_id)
        return False
    Setting.set(LAST_RUN_PREFIX + job_id, now_ist().replace(tzinfo=None).isoformat())
    db.session.commit()
    return True


def last_run(job_id: str) -> datetime | None:
    from .models import Setting
    raw = Setting.get(LAST_RUN_PREFIX + job_id)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def previous_slot(slots, now: datetime) -> datetime:
    """The most recent time this job was due, at or before ``now``."""
    best = None
    for hour, minute in slots:
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at > now:
            at -= timedelta(days=1)
        if best is None or at > best:
            best = at
    return best


def overdue_jobs(now: datetime | None = None) -> list[str]:
    """Jobs whose last due time has passed without them running since.

    A job is caught up once, not once per missed day: each one brings its area
    up to date in a single call (materialize_due walks every missed
    installment, take_snapshot upserts today's row), and past days cannot be
    reconstructed after the fact anyway.
    """
    now = now or now_ist().replace(tzinfo=None)
    due = []
    for job_id, slots in JOBS:
        seen = last_run(job_id)
        if seen is not None and seen >= previous_slot(slots, now):
            continue
        due.append(job_id)
    return due


def catch_up(app=None, force: bool = False) -> dict:
    """Run everything that was missed while the process was down.

    On a database that has never recorded a run, the watermarks are planted
    without running anything — the same first-run guard the SMS scan uses, so
    a fresh install doesn't fire off a burst of price fetches and a backup the
    first time a page is opened.
    """
    from .extensions import db
    from .models import Setting

    ctx = app.app_context() if app is not None else _null_context()
    with ctx:
        first_run = not force and all(last_run(j) is None for j, _ in JOBS)
        if first_run:
            stamp = now_ist().replace(tzinfo=None).isoformat()
            for job_id, _ in JOBS:
                Setting.set(LAST_RUN_PREFIX + job_id, stamp)
            db.session.commit()
            log.info("catch-up: first run, watermarks planted")
            return {"first_run": True, "ran": [], "failed": []}

        ran, failed = [], []
        for job_id in overdue_jobs():
            (ran if _run_and_mark(job_id) else failed).append(job_id)
        if ran or failed:
            log.info("catch-up ran %s, failed %s", ran, failed)
        return {"first_run": False, "ran": ran, "failed": failed}


class _null_context:
    """Already inside an app context (CLI, tests)."""
    def __enter__(self): return None
    def __exit__(self, *exc): return False


def _job_functions() -> dict:
    """job id -> callable. Every JOBS entry must have one here."""
    return {
        "refresh_mf": _job_refresh_mf,
        "refresh_market": _job_refresh_market,
        "run_recurring": _job_run_recurring,
        "snapshot": _job_snapshot,
        "sweep_alerts": _job_sweep_alerts,
        "auto_backup": _job_auto_backup,
        "scan_sms": _job_scan_sms,
    }


def _run_named_job(name: str) -> None:
    fn = _job_functions().get(name)
    if fn is None:
        raise KeyError("unknown scheduled job %r" % name)
    fn()


# Imports stay inside each function: services pull in heavy dependencies, and
# nothing should load them just to register the scheduler.
def _job_refresh_mf():
    from .services.prices import refresh_mutual_funds
    refresh_mutual_funds()


def _job_refresh_market():
    from .services.prices import refresh_gold, refresh_usdinr, refresh_stocks
    refresh_usdinr()
    refresh_gold()
    refresh_stocks()


def _job_run_recurring():
    from .services.recurring import materialize_due
    from .services.sip import run_due as run_sips
    from .services.rd import run_due as run_rds
    from .services.deposit_actions import close_matured
    materialize_due()
    run_sips()
    run_rds()
    close_matured()   # auto-deposit matured FD/RD proceeds into the bank account


def _job_snapshot():
    from .services.networth import take_snapshot
    take_snapshot()


def _job_sweep_alerts():
    from .services.alerts import sweep_all
    sweep_all()


def _job_auto_backup():
    from .services.backup import auto_backup
    auto_backup()


def _job_scan_sms():
    # Only meaningful on the phone; a desktop install has no Termux:API and
    # simply skips rather than logging a failure every night.
    from .services.sms_import import scan, termux_available
    if termux_available():
        scan()
