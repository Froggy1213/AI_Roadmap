"""Shared test fixtures: in-memory SQLite database with a fresh session."""

import os

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker

from app.db import Base
from app.models import *  # noqa: F401,F403 — register all model mappings


@pytest.fixture(scope="function")
def db_session():
    """A fresh in-memory SQLite database per test, with FK enforcement."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    session = scoped_session(session_factory)

    yield session

    session.remove()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
