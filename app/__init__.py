"""Application factory for Build Steward."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from .extensions import db, migrate
from .money import fmt_inr, money
from .timeutil import today_ist, month_label


def create_app(config_object: str | type | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    if config_object is None:
        config_object = os.environ.get("STEWARD_CONFIG", "config.Config")
    app.config.from_object(config_object)

    # Ensure instance/ exists for the SQLite file.
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    # Models must be imported so migrations & create_all see them.
    from . import models  # noqa: F401

    _register_blueprints(app)
    _register_template_helpers(app)
    _register_cli(app)
    _register_context(app)

    # Background price/snapshot jobs start lazily on the first served request,
    # so CLI commands (reset-db, seed, tests) never spin up the scheduler.
    app._scheduler_started = False

    @app.before_request
    def _maybe_start_scheduler():
        if app._scheduler_started:
            return
        app._scheduler_started = True
        if app.config.get("ENABLE_SCHEDULER") and not app.config.get("TESTING"):
            # Under the reloader, only the serving child handles requests.
            from .scheduler import start_scheduler
            start_scheduler(app)

    return app


def _register_blueprints(app: Flask) -> None:
    from .blueprints.dashboard import bp as dashboard_bp
    from .blueprints.accounts import bp as accounts_bp
    from .blueprints.categories import bp as categories_bp
    from .blueprints.transactions import bp as transactions_bp
    from .blueprints.budgets import bp as budgets_bp
    from .blueprints.recurring import bp as recurring_bp
    from .blueprints.funds import bp as funds_bp
    from .blueprints.savings import bp as savings_bp
    from .blueprints.networth import bp as networth_bp
    from .blueprints.reports import bp as reports_bp
    from .blueprints.tax import bp as tax_bp
    from .blueprints.settings import bp as settings_bp
    from .blueprints.imports import bp as imports_bp
    from .blueprints.api import bp as api_bp

    for bp in (
        dashboard_bp, accounts_bp, categories_bp, transactions_bp, budgets_bp,
        recurring_bp, funds_bp, savings_bp, networth_bp, reports_bp, tax_bp,
        settings_bp, imports_bp, api_bp,
    ):
        app.register_blueprint(bp)


def _register_template_helpers(app: Flask) -> None:
    app.jinja_env.filters["inr"] = lambda v: fmt_inr(v)
    app.jinja_env.filters["inr0"] = lambda v: fmt_inr(v, paise=False)

    def pct(part, whole):
        from decimal import Decimal
        whole = money(whole)
        if whole == 0:
            return 0
        return float(money(part) / whole * Decimal(100))

    app.jinja_env.filters["pct"] = pct
    app.jinja_env.globals["today"] = today_ist
    app.jinja_env.globals["month_label"] = month_label


def _register_context(app: Flask) -> None:
    from .services.settings import get_str

    @app.context_processor
    def inject_nav():
        from .models import Alert
        unread = Alert.query.filter_by(is_read=False).count()
        return {
            "nav_unread": unread,
            "server_theme": get_str("theme"),
        }

    @app.context_processor
    def inject_add_form():
        # Account/category lists for the global add-transaction slide-over.
        from .models import Account, Category
        from .timeutil import today_ist
        from .services.settings import salary_window_days
        exp = Category.query.filter_by(kind="expense", is_archived=False) \
            .order_by(Category.group, Category.sort_order, Category.name).all()
        inc = Category.query.filter_by(kind="income", is_archived=False) \
            .order_by(Category.sort_order, Category.name).all()
        # Savings categories are included in the name map (so linked savings rows
        # render their category) but have no add-form picker — savings is entered
        # from the Savings page, not here.
        sav = Category.query.filter_by(kind="savings", is_archived=False) \
            .order_by(Category.sort_order, Category.name).all()
        cat_map = {c.id: f"{c.icon} {c.name}" for c in exp + inc + sav}
        from .services.accounts import default_account_id
        return {
            "form_accounts": Account.query.filter_by(is_archived=False)
                .order_by(Account.sort_order, Account.name).all(),
            "form_expense_cats": exp,
            "form_income_cats": inc,
            "form_cat_map": cat_map,
            "form_today": today_ist().isoformat(),
            "salary_window": salary_window_days(),
            "form_default_account": default_account_id() or "",
        }


def _register_cli(app: Flask) -> None:
    from .cli import register_cli
    register_cli(app)
