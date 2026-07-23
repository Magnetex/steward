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
    app.cli.add_command(refresh_prices)
    app.cli.add_command(run_recurring)
    app.cli.add_command(snapshot)


@click.command("init-db")
@with_appcontext
def init_db():
    """Create all tables (dev convenience; prefer migrations for schema changes)."""
    db.create_all()
    click.echo("Tables created.")


@click.command("reset-db")
@click.option("--seed/--no-seed", default=True, help="Load sample data after reset.")
@with_appcontext
def reset_db(seed):
    """Drop everything, recreate tables, and (optionally) seed sample data."""
    db.drop_all()
    db.create_all()
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
    db.drop_all()
    db.create_all()
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
