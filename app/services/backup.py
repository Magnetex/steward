"""Database backup and restore.

A backup is a byte-exact SQLite snapshot, taken with sqlite3's online backup
API — safe to run while the app is serving, and consistent even mid-write.
Restore replaces the live database with an uploaded one, keeping a safety
copy of what it replaced.

Deliberately file-level rather than a JSON dump: this is disaster recovery,
so it must restore to exactly the prior state, including anything a
re-serialization would round or drop.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..timeutil import now_ist, today_ist

# Dated one-per-day, so launching the app repeatedly overwrites the day's file
# instead of producing dozens. Sorts chronologically as plain text, which is
# what rotation relies on.
DAILY_GLOB = "steward-*.db"

SQLITE_MAGIC = b"SQLite format 3\x00"

# Tables a file must have to be plausibly a Steward database. Deliberately a
# small core set: a backup taken at an older revision is still worth being
# able to restore, so this must not demand the newest tables. alembic_version
# is *not* required — every Alembic app has one, so it proves nothing, and
# demanding it would reject a database built by create_all.
REQUIRED_TABLES = {"account", "category", "transaction"}


class RestoreError(Exception):
    """An uploaded file was rejected — the live database is untouched."""


def database_path() -> Path:
    """Filesystem path of the configured SQLite database."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        raise RestoreError("Backup and restore only support SQLite databases.")
    return Path(uri.replace("sqlite:///", "", 1))


def backup_filename() -> str:
    return f"steward-backup-{now_ist().strftime('%Y%m%d-%H%M')}.db"


def write_snapshot(dest: Path) -> Path:
    """Copy the live database to ``dest`` using SQLite's online backup API.

    Unlike a plain file copy this is atomic with respect to writers, so it is
    safe to take while the app is running.
    """
    src = sqlite3.connect(str(database_path()))
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    return dest


def snapshot_bytes() -> bytes:
    """A snapshot as bytes, ready to send as a download.

    Read into memory and the temp file deleted immediately, rather than
    streaming from disk: the response outlives the request handler, so a
    file left for later cleanup is still open when we try to remove it
    (a hard error on Windows, a silent leak elsewhere). The database is a
    few hundred KB, so holding it in memory costs nothing.
    """
    with tempfile.TemporaryDirectory(prefix="steward-backup-") as d:
        tmp = Path(d) / "snapshot.db"
        write_snapshot(tmp)
        return tmp.read_bytes()


def daily_backup(dest_dir: Path, keep: int = 14) -> Path:
    """Snapshot into ``dest_dir`` as a dated file, pruning to ``keep`` newest.

    Used by the Termux launcher to set a copy aside on every app start. The
    destination is shared storage, which survives uninstalling Termux — unlike
    the database itself, which lives in Termux's private directory.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    target = dest_dir / f"steward-{today_ist().isoformat()}.db"
    write_snapshot_atomically(target)

    if keep > 0:
        existing = sorted(dest_dir.glob(DAILY_GLOB))
        for stale in existing[:-keep]:
            stale.unlink(missing_ok=True)
    return target


def write_snapshot_atomically(target: Path) -> Path:
    """Snapshot to a sibling temp file, then move into place.

    Writing straight to ``target`` would leave a half-written backup there if
    the process died partway — and on a phone, that file may be the only copy.
    """
    tmp = target.with_name(target.name + ".part")
    tmp.unlink(missing_ok=True)
    try:
        write_snapshot(tmp)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def validate(path: Path) -> None:
    """Reject anything that isn't a readable Steward database.

    Raises RestoreError with a message safe to show the user. Called before
    the live database is touched.
    """
    if not path.exists() or path.stat().st_size == 0:
        raise RestoreError("That file is empty.")

    with path.open("rb") as fh:
        if fh.read(16) != SQLITE_MAGIC:
            raise RestoreError(
                "That isn't a SQLite database file. Upload a .db backup "
                "downloaded from this app."
            )

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise RestoreError(f"Couldn't open that database: {exc}") from exc

    try:
        ok = conn.execute("PRAGMA integrity_check").fetchone()
        if not ok or ok[0] != "ok":
            raise RestoreError("That database is corrupt and can't be restored.")
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError as exc:
        raise RestoreError(f"That database couldn't be read: {exc}") from exc
    finally:
        conn.close()

    missing = REQUIRED_TABLES - names
    if missing:
        raise RestoreError(
            "That doesn't look like a Steward backup (missing: "
            + ", ".join(sorted(missing)) + ")."
        )


def restore(uploaded: Path) -> Path:
    """Replace the live database with ``uploaded``.

    Validates first, then snapshots what is about to be replaced so a mistaken
    restore is recoverable. Returns the path of that safety copy.
    """
    validate(uploaded)

    live = database_path()
    safety = live.with_name(
        f"{live.stem}-replaced-{now_ist().strftime('%Y%m%d-%H%M%S')}.db")
    if live.exists():
        write_snapshot(safety)

    # Drop pooled connections before swapping the file underneath them;
    # SQLAlchemy reconnects lazily on the next query.
    db.session.remove()
    db.engine.dispose()

    shutil.copyfile(uploaded, live)
    return safety
