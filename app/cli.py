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
    app.cli.add_command(backup)
    app.cli.add_command(refresh_prices)
    app.cli.add_command(run_recurring)
    app.cli.add_command(snapshot)


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
@click.argument("dest", type=click.Path())
@click.option("--keep", type=int, default=0,
              help="Delete all but the newest N backups sitting beside DEST.")
@with_appcontext
def backup(dest, keep):
    """Write a snapshot of the database to DEST.

    Same online-backup snapshot the Settings page downloads, so it is safe to
    run while the app is serving. Used by tools/termux-start.sh to keep copies
    in Android shared storage, where they outlive Termux itself.
    """
    from pathlib import Path
    from .services.backup import write_snapshot

    path = Path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_snapshot(path)
    click.echo(f"Backed up to {path}")

    if keep > 0:
        # Same-shaped siblings only, so this can never reach beyond its own
        # backup set (a bare *.db glob would happily delete the live database
        # if someone pointed DEST at instance/).
        stem = path.name.split("-")[0]
        siblings = sorted(path.parent.glob(f"{stem}-*.db"),
                          key=lambda p: p.stat().st_mtime, reverse=True)
        for old in siblings[keep:]:
            old.unlink()
            click.echo(f"  removed {old.name}")


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
