"""Backup status has to be *visible*.

A silently-skipped backup is indistinguishable from a working one until the
data is gone — which is exactly how a real ledger was lost. These pin the
parts that make the failure loud.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import Alert, Setting
from app.services import backup as bk
from app.services.alerts import sweep_backup_alert


def test_a_successful_backup_is_recorded(seeded, tmp_path):
    with seeded.app_context():
        assert bk.last_backup_info()["when"] is None
        out = bk.daily_backup(tmp_path)

        info = bk.last_backup_info()
        assert info["when"] is not None
        assert info["path"] == str(out)
        assert info["stale"] is False


def test_never_backed_up_reads_as_stale(seeded):
    with seeded.app_context():
        info = bk.last_backup_info()
        assert info["when"] is None
        assert info["stale"] is True


def test_an_old_backup_reads_as_stale(seeded, tmp_path):
    with seeded.app_context():
        bk.daily_backup(tmp_path)
        old = (datetime.now() - timedelta(days=9)).isoformat()
        Setting.set(bk.LAST_BACKUP_KEY, old)
        db.session.commit()

        info = bk.last_backup_info()
        assert info["age_days"] >= 9
        assert info["stale"] is True


def test_alert_raised_when_nothing_has_been_backed_up(seeded):
    with seeded.app_context():
        sweep_backup_alert()
        db.session.commit()

        alert = Alert.query.filter_by(dedupe_key="backup-stale").one()
        assert "has ever been taken" in alert.message
        assert not alert.is_read


def test_alert_is_not_duplicated_on_every_sweep(seeded):
    with seeded.app_context():
        for _ in range(4):
            sweep_backup_alert()
            db.session.commit()
        assert Alert.query.filter_by(dedupe_key="backup-stale").count() == 1


def test_no_alert_once_a_backup_exists(seeded, tmp_path):
    with seeded.app_context():
        bk.daily_backup(tmp_path)
        sweep_backup_alert()
        db.session.commit()
        assert Alert.query.filter_by(dedupe_key="backup-stale").count() == 0


def test_auto_backup_is_a_no_op_without_shared_storage(seeded, monkeypatch):
    """On a desktop there's no /sdcard; it must skip, not crash."""
    monkeypatch.setattr(bk, "shared_storage_dir", lambda: None)
    with seeded.app_context():
        assert bk.auto_backup() is None


def test_auto_backup_writes_when_storage_exists(seeded, tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "shared_storage_dir", lambda: tmp_path / "Steward")
    with seeded.app_context():
        out = bk.auto_backup()
        assert out is not None and out.exists()
        assert bk.last_backup_info()["stale"] is False


def test_settings_page_shows_the_warning(seeded):
    html = seeded.test_client().get("/settings/").get_data(as_text=True)
    assert "No backup has ever been taken" in html


def test_settings_page_shows_success_after_a_backup(seeded, tmp_path):
    with seeded.app_context():
        bk.daily_backup(tmp_path)
    html = seeded.test_client().get("/settings/").get_data(as_text=True)
    assert "Last backup" in html
    assert "No backup has ever been taken" not in html
