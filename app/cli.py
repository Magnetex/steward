"""Flask CLI commands: db bootstrap, seeding, and manual job triggers."""
from __future__ import annotations

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db


def register_cli(app: Flask) -> None:
    app.cli.add_command(init_db)
    app.cli.add_command(reset_db)
    app.cli.add_command(fresh_db)
    app.cli.add_command(seed)
    app.cli.add_command(backup)
    app.cli.add_command(scan_sms)
    app.cli.add_command(sms_doctor)
    app.cli.add_command(refresh_prices)
    app.cli.add_command(run_recurring)
    app.cli.add_command(snapshot)
    app.cli.add_command(catch_up)


@click.command("init-db")
@with_appcontext
def init_db():
    """Create all tables (dev convenience; prefer migrations for schema changes)."""
    db.create_all()
    click.echo("Tables created.")


def _recreate_schema():
    """Drop and rebuild every table, then tell Alembic we're at head.

    ``create_all`` builds the schema straight from the models, which *is* the
    head revision — but it leaves ``alembic_version`` at whatever it said
    before. Without the stamp the two drift apart, and the next real migration
    tries to add a column ``create_all`` already made ("duplicate column").
    """
    db.drop_all()
    db.create_all()
    try:
        from flask_migrate import stamp
        stamp(revision="head")
    except Exception as exc:  # noqa: BLE001 - never block a reset on this
        click.echo(f"  (couldn't stamp migration head: {exc})")


@click.command("reset-db")
@click.option("--seed/--no-seed", default=True, help="Load sample data after reset.")
@with_appcontext
def reset_db(seed):
    """Drop everything, recreate tables, and (optionally) seed sample data."""
    _recreate_schema()
    click.echo("Database reset.")
    if seed:
        from .services.seed import seed_all
        seed_all()
        click.echo("Sample data loaded.")


@click.command("fresh-db")
@click.option("--categories/--no-categories", default=True,
              help="Keep the default category set (default: yes).")
@click.confirmation_option(prompt="This deletes ALL data in the database. Continue?")
@with_appcontext
def fresh_db(categories):
    """Start a real ledger: wipe everything, keep only default categories.

    Unlike ``seed``, this creates no accounts, transactions or holdings — just
    the scaffolding you need before entering your own data.
    """
    _recreate_schema()
    if categories:
        from .services.seed import seed_scaffold
        seed_scaffold()
        db.session.commit()
        click.echo("Fresh database ready - default categories, no sample data.")
    else:
        click.echo("Fresh database ready - completely empty.")
    click.echo("Next: add your accounts with real opening balances.")


@click.command("seed")
@with_appcontext
def seed():
    """Load realistic sample data (idempotent-ish: clears app tables first)."""
    from .services.seed import seed_all
    seed_all()
    click.echo("Sample data loaded.")


@click.command("backup")
@click.argument("dest_dir", type=click.Path(file_okay=False))
@click.option("--keep", default=14, show_default=True,
              help="How many dated backups to keep (0 = keep all).")
@with_appcontext
def backup(dest_dir, keep):
    """Write a dated database snapshot into DEST_DIR.

    One file per day, so running it repeatedly overwrites today's rather than
    piling up. Used by the Termux launcher on every app start.
    """
    from .services.backup import daily_backup
    path = daily_backup(dest_dir, keep=keep)
    size = path.stat().st_size / 1024
    click.echo(f"Backed up to {path} ({size:.0f} KB)")


@click.command("scan-sms")
@with_appcontext
def scan_sms():
    """Read bank SMS via Termux:API and queue anything new for review."""
    from .services.sms_import import scan, SMSUnavailable, termux_available
    if not termux_available():
        click.echo("Termux:API not available - skipping SMS scan.")
        return
    try:
        result = scan()
    except SMSUnavailable as exc:
        click.echo(f"SMS scan skipped: {exc}")
        return
    click.echo(result["message"])


@click.command("sms-doctor")
@with_appcontext
def sms_doctor():
    """Diagnose SMS scanning: what Termux:API is actually returning."""
    import shutil
    import subprocess

    click.echo("Checking SMS scanning setup...\n")

    for tool in ("termux-sms-list", "termux-api-start"):
        path = shutil.which(tool)
        click.echo(f"  {tool:20} {path or 'NOT FOUND'}")
    if not shutil.which("termux-sms-list"):
        click.echo("\nInstall the Termux:API *app*, then: pkg install termux-api")
        return

    click.echo("\nRunning: termux-sms-list -l 1 -t inbox")
    try:
        out = subprocess.run(["termux-sms-list", "-l", "1", "-t", "inbox"],
                             capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        click.echo("  TIMED OUT — Android is likely waiting on a permission prompt.")
        return

    click.echo(f"  exit code : {out.returncode}")
    click.echo(f"  stdout    : {(out.stdout or '').strip()[:400] or '(empty)'}")
    click.echo(f"  stderr    : {(out.stderr or '').strip()[:400] or '(empty)'}")

    from .services.sms_import import parse_termux_output, SMSUnavailable
    try:
        rows = parse_termux_output(out.stdout, out.stderr)
    except SMSUnavailable as exc:
        click.echo(f"\n  -> Could not read messages: {exc}")
        return
    click.echo(f"\n  -> Parsed {len(rows)} message(s).")
    if rows:
        keys = sorted(rows[0].keys())
        click.echo(f"     fields: {', '.join(keys)}")
        if "received" not in keys:
            click.echo("     WARNING: no 'received' field — scanning needs it.")


@click.command("refresh-prices")
@with_appcontext
def refresh_prices():
    """Fetch MF NAVs, gold, USDINR, and stock prices now."""
    from .services.prices import refresh_all
    results = refresh_all()
    for key, ok in results.items():
        click.echo(f"  {'OK ' if ok else 'FAIL'} {key}")


@click.command("run-recurring")
@with_appcontext
def run_recurring():
    """Materialize due recurring rules (auto-create + remind-only)."""
    from .services.recurring import materialize_due
    n = materialize_due()
    click.echo(f"Processed {n} due rule(s).")


@click.command("snapshot")
@with_appcontext
def snapshot():
    """Record a net-worth snapshot for today."""
    from .services.networth import take_snapshot
    snap = take_snapshot()
    click.echo(f"Snapshot for {snap.date}: total {snap.total}")


@click.command("catch-up")
@click.option("--force", is_flag=True,
              help="Run overdue jobs even on a database that has never run any.")
@with_appcontext
def catch_up(force):
    """Run any daily job missed while the app was closed."""
    from .scheduler import catch_up as run_catch_up, overdue_jobs
    if force is False:
        pending = overdue_jobs()
        click.echo(f"Overdue: {', '.join(pending) if pending else 'nothing'}")
    result = run_catch_up(force=force)
    if result["first_run"]:
        click.echo("First run — watermarks planted, nothing executed.")
    else:
        click.echo(f"Ran: {', '.join(result['ran']) or 'nothing'}"
                   + (f" · failed: {', '.join(result['failed'])}" if result["failed"] else ""))
