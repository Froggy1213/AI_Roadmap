from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


engine = None
db_session = scoped_session(sessionmaker(autoflush=False, expire_on_commit=False))


def init_engine(uri: str):
    """Bind the global engine/session to `uri`. check_same_thread is off so the
    background agent thread (stage 2) can share the SQLite file."""
    global engine
    connect_args = {"check_same_thread": False} if uri.startswith("sqlite") else {}
    engine = create_engine(uri, connect_args=connect_args)

    if uri.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_fk_on(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    db_session.configure(bind=engine)
    return engine

