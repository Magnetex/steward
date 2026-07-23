"""Shared extension singletons, imported by the app factory and models."""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

# The scheduler is created lazily in scheduler.py to avoid import cycles.
