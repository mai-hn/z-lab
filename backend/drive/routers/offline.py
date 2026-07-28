from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.drive.deps import DbSession, StorageDep
from backend.drive.schemas import CreateOfflineRequest, OfflineTaskOut
from backend.drive.services.fs import FSError
from backend.drive.services.offline import OfflineService

router = APIRouter(prefix="/offline", tags=["offline"])


def _err(e: FSError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code})


def _out(task) -> OfflineTaskOut:
    return OfflineTaskOut.model_validate(task)


@router.post("", response_model=OfflineTaskOut, status_code=201)
def create_offline_task(body: CreateOfflineRequest, db: DbSession, storage: StorageDep):
    """Create offline task.

    - storage_backend=modal → spawns Modal Function only for this job (no always-on web).
    - storage_backend=local → downloads in a local background thread.
    """
    svc = OfflineService(db, storage)
    try:
        task = svc.create(body)
        db.commit()
        svc.start_async(task.id)
        db.refresh(task)
        return _out(task)
    except FSError as e:
        raise _err(e) from e


@router.get("", response_model=list)
def list_offline(db: DbSession, storage: StorageDep, limit: int = 50):
    svc = OfflineService(db, storage)
    return [_out(t) for t in svc.list_tasks(limit=limit)]


@router.get("/{task_id}", response_model=OfflineTaskOut)
def get_offline(task_id: str, db: DbSession, storage: StorageDep):
    svc = OfflineService(db, storage)
    try:
        return _out(svc.get(task_id))
    except FSError as e:
        raise _err(e) from e


@router.post("/{task_id}/cancel", response_model=OfflineTaskOut)
def cancel_offline(task_id: str, db: DbSession, storage: StorageDep):
    svc = OfflineService(db, storage)
    try:
        return _out(svc.cancel(task_id))
    except FSError as e:
        raise _err(e) from e


@router.delete("/{task_id}", status_code=204)
def delete_offline(task_id: str, db: DbSession, storage: StorageDep):
    svc = OfflineService(db, storage)
    try:
        svc.delete(task_id)
    except FSError as e:
        raise _err(e) from e
