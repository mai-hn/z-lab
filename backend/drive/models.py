from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.drive.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NodeType(str, enum.Enum):
    file = "file"
    directory = "directory"


class ConflictPolicy(str, enum.Enum):
    reject = "reject"
    overwrite = "overwrite"
    rename = "rename"


class UploadStatus(str, enum.Enum):
    pending = "pending"
    uploading = "uploading"
    merging = "merging"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class OfflineStatus(str, enum.Enum):
    pending = "pending"
    downloading = "downloading"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class FileNode(Base):
    """Virtual filesystem node. Physical content lives at files/{storage_key}."""

    __tablename__ = "file_nodes"
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_parent_name"),
        Index("ix_nodes_name", "name"),
        Index("ix_nodes_ext", "extension"),
        Index("ix_nodes_mime", "mime_type"),
        Index("ix_nodes_size", "size"),
        Index("ix_nodes_created", "created_at"),
        Index("ix_nodes_modified", "modified_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    node_type: Mapped[NodeType] = mapped_column(Enum(NodeType), nullable=False)
    storage_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    # Files point at an immutable stored object. Multiple FileNodes may share one
    # object, so copy/move/rename are metadata-only operations.
    content_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("stored_objects.id"), nullable=True, index=True
    )
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    extension: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_trashed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    parent = relationship("FileNode", remote_side=[id], backref="children")
    content = relationship("StoredObject", back_populates="nodes")


class StoredObject(Base):
    """Immutable logical content and its ordered Modal/local storage chunks."""

    __tablename__ = "stored_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="modal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    nodes = relationship("FileNode", back_populates="content")
    chunks = relationship(
        "StoredChunk",
        back_populates="content",
        cascade="all, delete-orphan",
        order_by="StoredChunk.chunk_index",
    )


class StoredChunk(Base):
    __tablename__ = "stored_chunks"
    __table_args__ = (
        UniqueConstraint("content_id", "chunk_index", name="uq_content_chunk_index"),
        Index("ix_stored_chunks_key", "storage_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_objects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(96), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    content = relationship("StoredObject", back_populates="chunks")


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    completed_set: Mapped[str] = mapped_column(Text, default="")
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    conflict: Mapped[ConflictPolicy] = mapped_column(
        Enum(ConflictPolicy), default=ConflictPolicy.rename
    )
    status: Mapped[UploadStatus] = mapped_column(Enum(UploadStatus), default=UploadStatus.pending)
    result_node_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    parts = relationship(
        "UploadPart",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="UploadPart.chunk_index",
    )


class UploadPart(Base):
    """A remotely persisted resumable-upload part."""

    __tablename__ = "upload_parts"
    __table_args__ = (
        UniqueConstraint("upload_id", "chunk_index", name="uq_upload_part_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(96), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session = relationship("UploadSession", back_populates="parts")


class OfflineTask(Base):
    __tablename__ = "offline_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[OfflineStatus] = mapped_column(Enum(OfflineStatus), default=OfflineStatus.pending)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    downloaded_size: Mapped[int] = mapped_column(BigInteger, default=0)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)
    speed: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_node_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    is_magnet: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
