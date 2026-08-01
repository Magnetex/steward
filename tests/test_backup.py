"""Backup download and restore.

The restore path is destructive, so most of these check that bad input is
rejected *before* the live database is touched.
"""
import io
import sqlite3
from pathlib import Path

import pytest

from app.services import backup as bk


def test_download_returns_a_usable_sqlite_file(seeded, tmp_path):
    resp = seeded.test_client().get("/settings/backup")
    assert resp.status_code == 200
    assert resp.data[:16] == bk.SQLITE_MAGIC

    out = tmp_path / "dl.db"
    out.write_bytes(resp.data)
    conn = sqlite3.connect(out)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert bk.REQUIRED_TABLES <= names
        # the snapshot carries real rows, not just a schema
        assert conn.execute("SELECT count(*) FROM account").fetchone()[0] > 0
    finally:
        conn.close()


def test_snapshot_round_trips_through_restore(seeded, tmp_path):
    """Back up, change the data, restore, and get the original back."""
    from app.models import Account
    from app.extensions import db

    with seeded.app_context():
        snapshot = bk.write_snapshot(tmp_path / "before.db")
        original = Account.query.count()
        db.session.add(Account(name="Added after backup", type="cash",
                               opening_balance=0, sort_order=99))
        db.session.commit()
        assert Account.query.count() == original + 1

        bk.restore(snapshot)
        assert Account.query.count() == original
        assert Account.query.filter_by(name="Added after backup").first() is None


def test_restore_keeps_a_copy_of_what_it_replaced(seeded, tmp_path):
    with seeded.app_context():
        snapshot = bk.write_snapshot(tmp_path / "snap.db")
        safety = bk.restore(snapshot)
    assert safety.exists()
    assert safety.read_bytes()[:16] == bk.SQLITE_MAGIC


@pytest.mark.parametrize("payload, reason", [
    (b"", "empty"),
    (b"this is not a database at all", "not sqlite"),
])
def test_rejects_junk_uploads(seeded, tmp_path, payload, reason):
    bad = tmp_path / "bad.db"
    bad.write_bytes(payload)
    with seeded.app_context():
        with pytest.raises(bk.RestoreError):
            bk.validate(bad)


def test_rejects_an_unrelated_sqlite_database(seeded, tmp_path):
    """A valid SQLite file that isn't ours must not overwrite the ledger."""
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()

    with seeded.app_context():
        with pytest.raises(bk.RestoreError, match="Steward backup"):
            bk.validate(other)


def test_bad_upload_leaves_the_live_database_untouched(seeded, tmp_path):
    from app.models import Account
    with seeded.app_context():
        before = Account.query.count()

    resp = seeded.test_client().post(
        "/settings/restore",
        data={"backup": (io.BytesIO(b"garbage"), "evil.db")},
        content_type="multipart/form-data", follow_redirects=True)
    assert resp.status_code == 200

    with seeded.app_context():
        assert Account.query.count() == before


def test_restore_with_no_file_is_a_no_op(seeded):
    resp = seeded.test_client().post("/settings/restore", data={},
                                     follow_redirects=True)
    assert resp.status_code == 200


def test_settings_page_offers_backup(seeded):
    html = seeded.test_client().get("/settings/").get_data(as_text=True)
    assert "/settings/backup" in html
    assert "/settings/restore" in html
