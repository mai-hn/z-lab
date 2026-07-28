from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Optional

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.drive.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None
_engine_url: Optional[str] = None


def reset_engine() -> None:
    global _engine, _SessionLocal, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _engine_url = None


def get_engine() -> Engine:
    global _engine, _SessionLocal, _engine_url
    settings = get_settings()
    settings.ensure_dirs()
    url = f"sqlite:///{settings.db_path}"
    if _engine is not None and _engine_url != url:
        reset_engine()
    if _engine is None:
        _engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        _engine_url = url

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def init_db() -> None:
    from backend.drive import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_content_manifest(engine)


def _migrate_content_manifest(engine: Engine) -> None:
    """Small in-place SQLite migration for pre-manifest databases.

    SQLAlchemy's create_all does not add columns to existing tables. Keep the
    legacy storage_key column for compatibility, then backfill each existing
    file as a one-chunk immutable object.
    """
    columns = {c["name"] for c in inspect(engine).get_columns("file_nodes")}
    if "content_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE file_nodes ADD COLUMN content_id VARCHAR(36)"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_file_nodes_content_id ON file_nodes (content_id)")
            )

    from backend.drive.models import FileNode, NodeType, StoredChunk, StoredObject
    from backend.drive.utils import new_id

    with Session(engine) as db:
        legacy = list(
            db.execute(
                select(FileNode).where(
                    FileNode.node_type == NodeType.file,
                    FileNode.content_id.is_(None),
                    FileNode.storage_key.is_not(None),
                )
            ).scalars()
        )
        for node in legacy:
            content_id = new_id()
            content = StoredObject(
                id=content_id,
                total_size=int(node.size or 0),
                chunk_size=int(node.size or 0),
                chunk_count=1,
                sha256=node.sha256,
                backend="legacy",
            )
            db.add(content)
            db.add(
                StoredChunk(
                    content_id=content_id,
                    chunk_index=0,
                    storage_key=str(node.storage_key),
                    size=int(node.size or 0),
                    sha256=node.sha256,
                )
            )
            node.content_id = content_id
        if legacy:
            db.commit()


def get_session() -> Generator[Session, None, None]:
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    yield from get_session()
