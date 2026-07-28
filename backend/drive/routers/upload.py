from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.drive.deps import DbSession, SettingsDep, StorageDep
from backend.drive.schemas import (
    ChunkUploadResult,
    CompleteUploadRequest,
    ConflictPolicy,
    CreateUploadRequest,
    FileNodeOut,
    UploadSessionOut,
)
from backend.drive.services.fs import FSError, FileService
from backend.drive.services.upload import UploadService

router = APIRouter(tags=["upload"])


def _err(e: FSError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code})


def _session_out(svc: UploadService, session) -> UploadSessionOut:
    completed = svc.completed_indices(session)
    missing = svc.missing_indices(session)
    return UploadSessionOut(
        id=session.id,
        filename=session.filename,
        parent_id=session.parent_id,
        total_size=session.total_size,
        chunk_size=session.chunk_size,
        total_chunks=session.total_chunks,
        completed_chunks=session.completed_chunks,
        completed_indices=completed,
        missing_indices=missing,
        file_hash=session.file_hash,
        conflict=session.conflict.value,  # type: ignore[arg-type]
        status=session.status.value,
        result_node_id=session.result_node_id,
        error_message=session.error_message,
        created_at=session.created_at,
        expires_at=session.expires_at,
        progress=svc.progress(session),
    )


@router.post("/upload", response_model=FileNodeOut, status_code=201)
async def simple_upload(
    db: DbSession,
    storage: StorageDep,
    settings: SettingsDep,
    file: UploadFile = File(...),
    parent_id: str | None = Form(None),
    path: str | None = Form(None),
    conflict: ConflictPolicy = Form(ConflictPolicy.rename),
    file_hash: str | None = Form(None),
):
    """Ordinary upload for small/medium files. Uses temp file + atomic move."""
    if (
        storage.backend_name() == "modal"
        and file.size is not None
        and file.size > settings.large_file_threshold
    ):
        raise HTTPException(
            status_code=413,
            detail={
                "message": "Files larger than 8 MiB must use chunked upload",
                "code": "chunked_upload_required",
            },
        )
    svc = UploadService(db, storage)
    fs = FileService(db, storage)
    try:
        node = svc.simple_upload(
            filename=file.filename or "unnamed",
            stream=file.file,
            parent_id=parent_id,
            path=path,
            conflict=conflict,
            expected_hash=file_hash,
        )
        return fs.to_out(node)
    except FSError as e:
        raise _err(e) from e


@router.post("/uploads", response_model=UploadSessionOut, status_code=201)
def create_upload(body: CreateUploadRequest, db: DbSession, storage: StorageDep):
    """Create a chunked upload session (resumable)."""
    svc = UploadService(db, storage)
    try:
        session = svc.create_session(body)
        return _session_out(svc, session)
    except FSError as e:
        raise _err(e) from e


@router.get("/uploads/{upload_id}", response_model=UploadSessionOut)
def get_upload(upload_id: str, db: DbSession, storage: StorageDep):
    svc = UploadService(db, storage)
    try:
        session = svc.get_session(upload_id)
        return _session_out(svc, session)
    except FSError as e:
        raise _err(e) from e


@router.put("/uploads/{upload_id}/parts/{chunk_index}", response_model=ChunkUploadResult)
async def upload_part(
    upload_id: str,
    chunk_index: int,
    db: DbSession,
    storage: StorageDep,
    file: UploadFile = File(...),
):
    svc = UploadService(db, storage)
    try:
        before = set(svc.completed_indices(svc.get_session(upload_id)))
        already = chunk_index in before
        data = await file.read()
        session = svc.upload_chunk(upload_id, chunk_index, data)
        return ChunkUploadResult(
            upload_id=session.id,
            chunk_index=chunk_index,
            completed_chunks=session.completed_chunks,
            total_chunks=session.total_chunks,
            progress=svc.progress(session),
            already_uploaded=already,
        )
    except FSError as e:
        raise _err(e) from e


@router.post("/uploads/{upload_id}/complete", response_model=FileNodeOut)
def complete_upload(
    upload_id: str,
    db: DbSession,
    storage: StorageDep,
    body: CompleteUploadRequest | None = None,
):
    svc = UploadService(db, storage)
    fs = FileService(db, storage)
    try:
        file_hash = body.file_hash if body else None
        _session, node = svc.complete(upload_id, file_hash=file_hash)
        return fs.to_out(node)  # type: ignore[arg-type]
    except FSError as e:
        raise _err(e) from e


@router.delete("/uploads/{upload_id}", response_model=UploadSessionOut)
def cancel_upload(upload_id: str, db: DbSession, storage: StorageDep):
    svc = UploadService(db, storage)
    try:
        session = svc.cancel(upload_id)
        return _session_out(svc, session)
    except FSError as e:
        raise _err(e) from e
