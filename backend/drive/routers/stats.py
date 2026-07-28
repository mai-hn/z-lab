from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from backend.drive.deps import DbSession, StorageDep
from backend.drive.models import OfflineTask, UploadSession
from backend.drive.schemas import StorageStats
from backend.drive.services.fs import FileService

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StorageStats)
def storage_stats(db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    base = fs.stats()
    uploads = db.execute(select(func.count()).select_from(UploadSession)).scalar() or 0
    offline = db.execute(select(func.count()).select_from(OfflineTask)).scalar() or 0
    return StorageStats(
        used_bytes=base["used_bytes"],
        logical_bytes=base["logical_bytes"],
        saved_bytes=base["saved_bytes"],
        chunked_files=base["chunked_files"],
        shared_contents=base["shared_contents"],
        file_count=base["file_count"],
        directory_count=base["directory_count"],
        upload_sessions=uploads,
        offline_tasks=offline,
    )
