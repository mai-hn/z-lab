from __future__ import annotations

import math
import hashlib
from datetime import timedelta
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.drive.config import Settings, get_settings
from backend.drive.models import (
    StoredChunk,
    StoredObject,
    UploadPart,
    UploadSession,
    UploadStatus,
    utcnow,
)
from backend.drive.schemas import ConflictPolicy, CreateUploadRequest
from backend.drive.services.fs import FSError, FileService

from backend.drive.utils import (
    new_id,
    parse_completed_set,
    sanitize_filename,
    serialize_completed_set,
    sha256_file,
)


class UploadService:
    def __init__(self, db: Session, storage, settings: Settings | None = None):
        self.db = db
        self.storage = storage
        self.settings = settings or get_settings()
        self.fs = FileService(db, storage)

    def create_session(self, req: CreateUploadRequest) -> UploadSession:
        if req.total_size > self.settings.max_upload_size:
            raise FSError("File too large", "too_large", 413)

        parent_id = self.fs.resolve_parent(req.parent_id, req.path)
        filename = sanitize_filename(req.filename)
        chunk_size = req.chunk_size or self.settings.default_chunk_size
        if chunk_size < 256 * 1024:
            chunk_size = 256 * 1024
        if self.storage.backend_name() == "modal":
            chunk_size = min(chunk_size, self.settings.large_file_threshold)
        total_chunks = max(1, math.ceil(req.total_size / chunk_size))
        from backend.drive.models import ConflictPolicy as ModelConflict

        now = utcnow()
        conflict_val = req.conflict if isinstance(req.conflict, ConflictPolicy) else ConflictPolicy(req.conflict)
        session = UploadSession(
            id=new_id(),
            filename=filename,
            parent_id=parent_id,
            total_size=req.total_size,
            chunk_size=chunk_size,
            total_chunks=total_chunks,
            completed_chunks=0,
            completed_set="",
            file_hash=req.file_hash,
            conflict=ModelConflict(conflict_val.value),
            status=UploadStatus.pending,
            created_at=now,
            expires_at=now + timedelta(hours=self.settings.upload_expire_hours),
            updated_at=now,
        )

        self.db.add(session)
        self.db.flush()
        return session

    def get_session(self, upload_id: str) -> UploadSession:
        session = self.db.get(UploadSession, upload_id)
        if not session:
            raise FSError("Upload session not found", "not_found", 404)
        if session.status == UploadStatus.cancelled:
            raise FSError("Upload cancelled", "cancelled", 410)
        if session.expires_at < utcnow() and session.status not in (
            UploadStatus.completed,
            UploadStatus.cancelled,
        ):
            session.status = UploadStatus.failed
            session.error_message = "Upload expired"
            for part in list(session.parts):
                try:
                    self.storage.delete_file(part.storage_key)
                finally:
                    self.db.delete(part)
            self.storage.delete_upload(session.id)
            self.db.flush()
            raise FSError("Upload expired", "expired", 410)
        return session

    def completed_indices(self, session: UploadSession) -> list[int]:
        return sorted(parse_completed_set(session.completed_set))

    def missing_indices(self, session: UploadSession) -> list[int]:
        done = parse_completed_set(session.completed_set)
        return [i for i in range(session.total_chunks) if i not in done]

    def progress(self, session: UploadSession) -> float:
        if session.total_chunks == 0:
            return 0.0
        return round(session.completed_chunks / session.total_chunks * 100, 2)

    def upload_chunk(self, upload_id: str, index: int, data: bytes | BinaryIO, size_hint: int | None = None) -> UploadSession:
        session = self.get_session(upload_id)
        if session.status in (UploadStatus.completed, UploadStatus.merging):
            raise FSError("Upload already completed", "completed", 400)
        if session.status == UploadStatus.failed:
            raise FSError("Upload failed", "failed", 400)
        if index < 0 or index >= session.total_chunks:
            raise FSError(f"Invalid chunk index {index}", "bad_index", 400)

        done = parse_completed_set(session.completed_set)
        existing_part = self.db.execute(
            select(UploadPart).where(
                UploadPart.upload_id == upload_id,
                UploadPart.chunk_index == index,
            )
        ).scalar_one_or_none()
        if index in done and existing_part is not None:
            # idempotent retry
            return session

        # validate size for non-last chunks
        if isinstance(data, bytes):
            raw = data
            if index < session.total_chunks - 1 and len(raw) != session.chunk_size:
                raise FSError(
                    f"Chunk size mismatch: expected {session.chunk_size}, got {len(raw)}",
                    "bad_chunk_size",
                    400,
                )
            if index == session.total_chunks - 1:
                expected_last = session.total_size - session.chunk_size * (session.total_chunks - 1)
                if len(raw) != expected_last:
                    raise FSError(
                        f"Last chunk size mismatch: expected {expected_last}, got {len(raw)}",
                        "bad_chunk_size",
                        400,
                    )
            self.storage.write_chunk(upload_id, index, raw)
        else:
            raw = data.read()
            self.storage.write_chunk(upload_id, index, raw)

        if existing_part is not None:
            self.db.delete(existing_part)
            self.db.flush()
        self.db.add(
            UploadPart(
                upload_id=upload_id,
                chunk_index=index,
                storage_key=self.storage.upload_chunk_key(upload_id, index),
                size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )

        done.add(index)
        session.completed_set = serialize_completed_set(done)
        session.completed_chunks = len(done)
        session.status = UploadStatus.uploading
        session.updated_at = utcnow()
        self.db.flush()
        return session

    def complete(self, upload_id: str, file_hash: str | None = None) -> tuple[UploadSession, object]:
        session = self.get_session(upload_id)
        if session.status == UploadStatus.completed and session.result_node_id:
            node = self.fs.get_node(session.result_node_id)
            return session, node

        missing = self.missing_indices(session)
        if missing:
            raise FSError(
                f"Missing chunks: {missing[:20]}{'...' if len(missing) > 20 else ''}",
                "incomplete",
                400,
            )

        session.status = UploadStatus.merging
        session.updated_at = utcnow()
        self.db.flush()

        storage_key = new_id().replace("-", "")
        try:
            expected = file_hash or session.file_hash
            keep_chunked = (
                self.storage.backend_name() == "modal"
                or session.total_size > self.settings.large_file_threshold
            )
            if keep_chunked:
                parts = list(
                    self.db.execute(
                        select(UploadPart)
                        .where(UploadPart.upload_id == session.id)
                        .order_by(UploadPart.chunk_index)
                    ).scalars()
                )
                if len(parts) != session.total_chunks:
                    raise FSError("Upload part manifest is incomplete", "incomplete", 400)
                size = sum(int(part.size) for part in parts)
                if size != session.total_size:
                    raise FSError(
                        f"Size mismatch: expected {session.total_size}, got {size}",
                        "size_mismatch",
                        400,
                    )
                digest = expected
                if self.storage.backend_name() == "local":
                    whole_hash = hashlib.sha256()
                    for part in parts:
                        path = self.storage.chunk_path(session.id, part.chunk_index)
                        with path.open("rb") as stream:
                            while block := stream.read(1024 * 1024):
                                whole_hash.update(block)
                        final_key = self.storage.upload_chunk_key(session.id, part.chunk_index)
                        self.storage.write_file_atomic(final_key, path)
                        part.storage_key = final_key
                    digest = whole_hash.hexdigest()
                    if expected and expected.lower() != digest.lower():
                        for part in parts:
                            self.storage.delete_file(part.storage_key)
                        session.status = UploadStatus.failed
                        session.error_message = "Hash mismatch"
                        self.db.flush()
                        raise FSError("File hash mismatch after upload", "hash_mismatch", 400)
                content = StoredObject(
                    id=new_id(),
                    total_size=size,
                    chunk_size=session.chunk_size,
                    chunk_count=len(parts),
                    # Modal validates each part without downloading it again.
                    sha256=digest,
                    backend=self.storage.backend_name(),
                )
                self.db.add(content)
                self.db.flush()
                for part in parts:
                    self.db.add(
                        StoredChunk(
                            content_id=content.id,
                            chunk_index=part.chunk_index,
                            storage_key=part.storage_key,
                            size=part.size,
                            sha256=part.sha256,
                        )
                    )
                self.db.flush()
                content_id = content.id
            else:
                _path, size, digest = self.storage.merge_chunks(
                    session.id,
                    storage_key,
                    session.total_chunks,
                    expected_size=session.total_size,
                )
                if expected and expected.lower() != digest.lower():
                    self.storage.delete_file(storage_key)
                    session.status = UploadStatus.failed
                    session.error_message = "Hash mismatch"
                    self.db.flush()
                    raise FSError("File hash mismatch after merge", "hash_mismatch", 400)
                content_id = None

            from backend.drive.schemas import ConflictPolicy as SchemaConflict

            conflict = SchemaConflict(session.conflict.value)
            node = self.fs.register_file(
                name=session.filename,
                storage_key=storage_key,
                size=size,
                sha256=digest,
                content_id=content_id,
                parent_id=session.parent_id,
                conflict=conflict,
            )
            session.status = UploadStatus.completed
            session.result_node_id = node.id
            session.file_hash = digest
            session.updated_at = utcnow()
            for part in list(session.parts):
                self.db.delete(part)
            self.db.flush()

            # cleanup any leftover local chunks (Modal merge already wiped)
            try:
                self.storage.delete_upload(session.id)
            except Exception:
                pass
            return session, node
        except FSError:
            raise
        except Exception as e:
            session.status = UploadStatus.failed
            session.error_message = str(e)
            session.updated_at = utcnow()
            self.db.flush()
            if self.storage.backend_name() != "modal":
                try:
                    self.storage.delete_file(storage_key)
                except Exception:
                    pass
            raise FSError(f"Merge failed: {e}", "merge_failed", 500)

    def cancel(self, upload_id: str) -> UploadSession:
        session = self.db.get(UploadSession, upload_id)
        if not session:
            raise FSError("Upload session not found", "not_found", 404)
        if session.status == UploadStatus.completed:
            raise FSError("Cannot cancel completed upload", "completed", 400)
        session.status = UploadStatus.cancelled
        session.updated_at = utcnow()
        self.db.flush()
        for part in list(session.parts):
            self.storage.delete_file(part.storage_key)
            self.db.delete(part)
        self.storage.delete_upload(upload_id)
        return session

    def simple_upload(
        self,
        filename: str,
        stream: BinaryIO,
        parent_id: str | None = None,
        path: str | None = None,
        conflict: ConflictPolicy | str = ConflictPolicy.rename,
        expected_hash: str | None = None,
    ):
        parent_id = self.fs.resolve_parent(parent_id, path)
        filename = sanitize_filename(filename)
        storage_key = new_id().replace("-", "")
        tmp = self.storage.tmp_path(f".upload-{storage_key}.tmp")
        size = 0
        try:
            with open(tmp, "wb") as f:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                    if size > self.settings.max_upload_size:
                        raise FSError("File too large", "too_large", 413)
                    if (
                        self.storage.backend_name() == "modal"
                        and size > self.settings.large_file_threshold
                    ):
                        raise FSError(
                            "Files larger than 8 MiB must use the chunked upload API",
                            "chunked_upload_required",
                            413,
                        )
                f.flush()
                import os

                os.fsync(f.fileno())

            digest = sha256_file(tmp)
            if expected_hash and expected_hash.lower() != digest.lower():
                raise FSError("Hash mismatch", "hash_mismatch", 400)

            self.storage.write_file_atomic(storage_key, tmp)
            node = self.fs.register_file(
                name=filename,
                storage_key=storage_key,
                size=size,
                sha256=digest,
                parent_id=parent_id,
                conflict=conflict,
            )
            return node
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            try:
                self.storage.delete_file(storage_key)
            except Exception:
                pass
            raise
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
