from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from backend.drive.deps import DbSession, StorageDep
from backend.drive.schemas import SearchQuery, SearchResult
from backend.drive.services.fs import FSError, FileService
from backend.drive.services.search import SearchService

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResult)
def search(
    db: DbSession,
    storage: StorageDep,
    q: str | None = None,
    extension: str | None = None,
    mime_prefix: str | None = None,
    file_type: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    modified_after: datetime | None = None,
    modified_before: datetime | None = None,
    parent_id: str | None = None,
    path: str | None = None,
    recursive: bool = True,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    svc = SearchService(db, storage)
    fs = FileService(db, storage)
    try:
        query = SearchQuery(
            q=q,
            extension=extension,
            mime_prefix=mime_prefix,
            file_type=file_type,  # type: ignore[arg-type]
            min_size=min_size,
            max_size=max_size,
            created_after=created_after,
            created_before=created_before,
            modified_after=modified_after,
            modified_before=modified_before,
            parent_id=parent_id,
            path=path,
            recursive=recursive,
            limit=limit,
            offset=offset,
        )
        rows, total = svc.search(query)
        return SearchResult(
            items=[fs.to_out(r) for r in rows],
            total=total,
            limit=limit,
            offset=offset,
        )
    except FSError as e:
        raise HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code}) from e
