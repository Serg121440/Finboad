"""Database engine and session.

PostgreSQL in production (relaxdev internal network, no TLS). If a PostgreSQL URL
is configured but unreachable we fail loudly instead of silently writing into a
throwaway SQLite file: data written there disappears on the next deploy.
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from core import config

Base = declarative_base()

# libpq rejects these, and the relaxdev database has no TLS at all.
_DROP_PARAMS = {"schema", "pgbouncer", "connect_timeout_ms", "sslmode", "ssl", "channel_binding"}


class DatabaseUnavailable(RuntimeError):
    pass


def _build_engine(raw_url: str):
    if not raw_url:
        return create_engine(config.SQLITE_URL, echo=False)
    url = make_url(raw_url)
    if url.get_dialect().name in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg2",
                      query={k: v for k, v in url.query.items() if k not in _DROP_PARAMS})
        return create_engine(url, echo=False, pool_pre_ping=True, pool_size=5,
                             connect_args={"connect_timeout": 5, "sslmode": "disable"})
    return create_engine(url, echo=False)


engine = _build_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


def init_db():
    """Create v2 tables. Raises DatabaseUnavailable if the server can't be reached."""
    import core.models  # noqa: F401  (registers tables)
    try:
        Base.metadata.create_all(engine)
        _add_missing_columns()
    except Exception as e:  # pragma: no cover - depends on infrastructure
        raise DatabaseUnavailable(str(e)) from e


def _add_missing_columns():
    """create_all() doesn't alter existing tables: add columns introduced later."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}'))


@contextmanager
def session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
