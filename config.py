"""Configuration for Build Steward.

Single-user local app. No secrets of consequence; the SECRET_KEY only
protects flash messages / CSRF-style tokens for this local instance.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"


class Config:
    SECRET_KEY = os.environ.get("STEWARD_SECRET_KEY", "steward-local-dev-key")

    # SQLite lives in instance/steward.db
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{(INSTANCE_DIR / 'steward.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Timezone for all budget/date logic. Fixed to IST per spec.
    TIMEZONE = "Asia/Kolkata"

    # Turn the APScheduler price/snapshot jobs on. Disabled during tests.
    ENABLE_SCHEDULER = os.environ.get("STEWARD_SCHEDULER", "1") == "1"

    # Network timeout for all price fetches (seconds).
    PRICE_FETCH_TIMEOUT = 10


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    ENABLE_SCHEDULER = False
    WTF_CSRF_ENABLED = False
