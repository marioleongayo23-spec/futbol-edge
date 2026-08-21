"""Motor y sesiones de base de datos."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .models import Base


def make_engine(url: str | None = None):
    url = url or settings.database_url
    if url.startswith("sqlite"):
        # Aseguramos que exista la carpeta del fichero SQLite.
        path = url.replace("sqlite:///", "")
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url, pool_pre_ping=True)
    return engine


_engine = None
_Session: sessionmaker | None = None


def init_db(url: str | None = None):
    global _engine, _Session
    _engine = make_engine(url)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def get_session() -> Session:
    if _Session is None:
        init_db()
    session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
