"""Catching up jobs missed while the process was down.

On the phone the server only runs while the app is open, so the cron times
mostly pass with nothing listening. These cover the watermark logic that
decides what still needs running.
"""
from datetime import datetime

from app.extensions import db
from app.models import Setting, NetWorthSnapshot
from app import scheduler as sch


def _stamp(job_id, when):
    Setting.set(sch.LAST_RUN_PREFIX + job_id, when.isoformat())
    db.session.commit()


def _rewind_all(when=datetime(2026, 7, 29, 12, 0)):
    for job_id, _ in sch.JOBS:
        _stamp(job_id, when)


def _offline(monkeypatch, keep=("snapshot",)):
    """Run only the jobs a test cares about; the rest would hit the network."""
    real = sch._run_named_job
    monkeypatch.setattr(sch, "_run_named_job",
                        lambda name: real(name) if name in keep else None)


def test_previous_slot_picks_the_most_recent_due_time():
    now = datetime(2026, 8, 5, 12, 0)
    # single daily slot earlier today
    assert sch.previous_slot(((6, 0),), now) == datetime(2026, 8, 5, 6, 0)
    # a slot later today was last due yesterday
    assert sch.previous_slot(((23, 0),), now) == datetime(2026, 8, 4, 23, 0)
    # two slots a day: the morning one, until the evening one passes
    assert sch.previous_slot(((7, 15), (20, 15)), now) == datetime(2026, 8, 5, 7, 15)
    assert sch.previous_slot(((7, 15), (20, 15)), datetime(2026, 8, 5, 21, 0)) \
        == datetime(2026, 8, 5, 20, 15)


def test_a_job_that_ran_after_its_slot_is_not_overdue(app):
    with app.app_context():
        now = datetime(2026, 8, 5, 12, 0)
        _stamp("run_recurring", datetime(2026, 8, 5, 6, 30))    # after the 06:00 slot
        assert "run_recurring" not in sch.overdue_jobs(now)


def test_a_job_that_last_ran_before_its_slot_is_overdue(app):
    with app.app_context():
        now = datetime(2026, 8, 5, 12, 0)
        _stamp("run_recurring", datetime(2026, 8, 4, 6, 30))    # yesterday's run
        assert "run_recurring" in sch.overdue_jobs(now)


def test_a_job_never_run_is_overdue(app):
    with app.app_context():
        assert set(sch.overdue_jobs(datetime(2026, 8, 5, 12, 0))) == {j for j, _ in sch.JOBS}


def test_first_catch_up_plants_watermarks_without_running_anything(app):
    """A fresh install must not fire off a burst of fetches and a backup."""
    with app.app_context():
        assert NetWorthSnapshot.query.count() == 0
        result = sch.catch_up()

        assert result["first_run"] is True
        assert result["ran"] == []
        assert NetWorthSnapshot.query.count() == 0, "nothing was executed"
        assert sch.overdue_jobs() == [], "but everything is now watermarked"


def test_catch_up_runs_what_was_missed(app, monkeypatch):
    """The second launch, a day later, brings things up to date."""
    with app.app_context():
        sch.catch_up()                                   # plant watermarks
        _rewind_all()
        _offline(monkeypatch)

        result = sch.catch_up()

        assert result["first_run"] is False
        assert "snapshot" in result["ran"]
        assert NetWorthSnapshot.query.count() == 1, "the trend gains its point"
        assert sch.overdue_jobs() == []


def test_a_failing_job_does_not_stop_the_others_or_claim_success(app, monkeypatch):
    with app.app_context():
        sch.catch_up()
        _rewind_all()

        def boom(name):
            if name == "refresh_market":
                raise RuntimeError("no network")
            if name == "snapshot":
                sch._job_snapshot()

        monkeypatch.setattr(sch, "_run_named_job", boom)
        result = sch.catch_up()

        assert result["failed"] == ["refresh_market"]
        assert "snapshot" in result["ran"], "later jobs still ran"
        # the failed one stays overdue, so the next launch retries it
        assert sch.overdue_jobs() == ["refresh_market"]


def test_catch_up_is_a_no_op_when_nothing_is_due(app):
    with app.app_context():
        sch.catch_up()
        assert sch.catch_up() == {"first_run": False, "ran": [], "failed": []}


def test_every_scheduled_job_has_an_implementation(app):
    """A typo in JOBS would otherwise only surface at 06:00 on the phone."""
    with app.app_context():
        assert {job_id for job_id, _ in sch.JOBS} == set(sch._job_functions())
        for job_id, slots in sch.JOBS:
            assert slots, f"{job_id} has no times"
