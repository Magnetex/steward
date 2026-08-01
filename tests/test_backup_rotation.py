"""Dated backups written by the Termux launcher, and their rotation."""
import sqlite3

from app.services import backup as bk
from app.timeutil import today_ist


def test_writes_a_dated_snapshot(seeded, tmp_path):
    with seeded.app_context():
        out = bk.daily_backup(tmp_path / "Steward" / "backup")

    assert out.name == f"steward-{today_ist().isoformat()}.db"
    assert out.parent.is_dir(), "destination should be created if missing"
    assert out.read_bytes()[:16] == bk.SQLITE_MAGIC

    conn = sqlite3.connect(out)
    try:
        assert conn.execute("SELECT count(*) FROM account").fetchone()[0] > 0
    finally:
        conn.close()


def test_same_day_overwrites_rather_than_accumulating(seeded, tmp_path):
    with seeded.app_context():
        bk.daily_backup(tmp_path)
        bk.daily_backup(tmp_path)
        bk.daily_backup(tmp_path)
    assert len(list(tmp_path.glob(bk.DAILY_GLOB))) == 1


def test_rotation_keeps_only_the_newest(seeded, tmp_path):
    # Stand in for previous days' backups; names sort chronologically.
    for day in range(1, 21):
        (tmp_path / f"steward-2026-07-{day:02d}.db").write_bytes(b"old")

    with seeded.app_context():
        bk.daily_backup(tmp_path, keep=5)

    kept = sorted(p.name for p in tmp_path.glob(bk.DAILY_GLOB))
    assert len(kept) == 5
    assert kept[-1] == f"steward-{today_ist().isoformat()}.db", "today's is kept"
    assert "steward-2026-07-01.db" not in kept, "oldest is pruned"


def test_keep_zero_prunes_nothing(seeded, tmp_path):
    (tmp_path / "steward-2026-01-01.db").write_bytes(b"old")
    with seeded.app_context():
        bk.daily_backup(tmp_path, keep=0)
    assert (tmp_path / "steward-2026-01-01.db").exists()


def test_leaves_no_partial_file_behind(seeded, tmp_path):
    """The snapshot is staged then moved, so no .part should survive."""
    with seeded.app_context():
        bk.daily_backup(tmp_path)
    assert not list(tmp_path.glob("*.part"))


def test_existing_backup_survives_a_failed_snapshot(seeded, tmp_path, monkeypatch):
    """A later failure must not destroy the backup already on disk."""
    with seeded.app_context():
        good = bk.daily_backup(tmp_path)
        original = good.read_bytes()

        def boom(dest):
            raise sqlite3.OperationalError("disk full")

        monkeypatch.setattr(bk, "write_snapshot", boom)
        try:
            bk.daily_backup(tmp_path)
        except sqlite3.OperationalError:
            pass

    assert good.read_bytes() == original, "previous backup was corrupted"
    assert not list(tmp_path.glob("*.part"))
