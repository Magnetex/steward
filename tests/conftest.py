"""Pytest fixtures. Uses a temp-file SQLite DB (in-memory loses data across
the connections Flask-SQLAlchemy opens)."""
import pytest

from app import create_app
from app.extensions import db as _db
from config import TestConfig


@pytest.fixture
def app(tmp_path):
    class Cfg(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"

    app = create_app(Cfg)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded(app):
    from app.services.seed import seed_all
    with app.app_context():
        seed_all()
    yield app
