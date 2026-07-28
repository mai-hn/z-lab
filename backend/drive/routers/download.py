from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse

from backend.drive.deps import DbSession, SettingsDep, StorageDep
from backend.drive.direct_download import create_modal_download_url, modal_download_enabled
from backend.drive.models import NodeType
from backend.drive.schemas import DirectDownloadLinkOut
from backend.drive.services.fs import FSError, FileService

router = APIRouter(tags=["download"])

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _err(e: FSError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code})


@router.get("/files/{node_id}/content")
def download_file(
    node_id: str,
    request: Request,
    db: DbSession,
    storage: StorageDep,
    settings: SettingsDep,
):
    """Download with HTTP Range support for resume / multi-thread / video seek."""
    fs = FileService(db, storage)
    try:
        node = fs.get_node(node_id)
        assert node is not None
    except FSError as e:
        raise _err(e) from e

    if node.node_type != NodeType.file:
        raise HTTPException(status_code=400, detail="Not a file")
    if modal_download_enabled(settings, storage.backend_name()):
        url, _expires = create_modal_download_url(node.id, settings)
        return RedirectResponse(
            url,
            status_code=307,
            headers={
                "Cache-Control": "private, no-store",
                "X-Download-Provider": "modal",
            },
        )
    try:
        chunks = fs.content_chunks(node)
    except FSError as e:
        raise _err(e) from e

    # Prefer DB size (avoids extra Volume round-trip); fall back to storage probe
    file_size = int(node.size or 0)
    if file_size <= 0:
        file_size = sum(int(chunk.size) for chunk in chunks)
    content_type = node.mime_type or "application/octet-stream"
    filename = node.name
    # RFC 5987
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    # For inline preview of media
    inline = request.query_params.get("inline", "").lower() in ("1", "true", "yes")
    if inline:
        disposition = f"inline; filename*=UTF-8''{quote(filename)}"

    def iter_content(start: int = 0, end: int | None = None):
        """Yield ordered manifest chunks, translating a global HTTP range."""
        global_offset = 0
        wanted_end = file_size - 1 if end is None else end
        for chunk in chunks:
            chunk_size = int(chunk.size)
            chunk_end = global_offset + chunk_size - 1
            if chunk_end < start:
                global_offset += chunk_size
                continue
            if global_offset > wanted_end:
                break
            local_start = max(0, start - global_offset)
            local_end = min(chunk_size - 1, wanted_end - global_offset)
            yield from storage.iter_file(
                chunk.storage_key,
                start=local_start,
                end=local_end,
            )
            global_offset += chunk_size

    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header:
        m = RANGE_RE.match(range_header.strip())
        if not m:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        start_s, end_s = m.group(1), m.group(2)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        if end_s == "" and start_s:
            end = file_size - 1
        if start_s == "" and end_s:
            # suffix bytes: last N bytes
            suffix = int(end_s)
            start = max(file_size - suffix, 0)
            end = file_size - 1
        if start >= file_size or end >= file_size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": content_type,
            "Content-Disposition": disposition,
            "Cache-Control": "private, max-age=0",
            "X-File-Size": str(file_size),
            "X-Chunk-Count": str(len(chunks)),
        }
        return StreamingResponse(
            iter_content(start=start, end=end),
            status_code=206,
            headers=headers,
            media_type=content_type,
        )

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": content_type,
        "Content-Disposition": disposition,
        "Cache-Control": "private, max-age=0",
        "X-File-Size": str(file_size),
        "X-Chunk-Count": str(len(chunks)),
    }
    return StreamingResponse(
        iter_content(),
        status_code=200,
        headers=headers,
        media_type=content_type,
    )


@router.get("/files/{node_id}/download-link", response_model=DirectDownloadLinkOut)
def create_download_link(
    node_id: str,
    request: Request,
    db: DbSession,
    storage: StorageDep,
    settings: SettingsDep,
):
    fs = FileService(db, storage)
    try:
        node = fs.get_node(node_id)
        assert node is not None
    except FSError as error:
        raise _err(error) from error
    if node.node_type != NodeType.file:
        raise HTTPException(status_code=400, detail="Not a file")

    if modal_download_enabled(settings, storage.backend_name()):
        url, expires = create_modal_download_url(node.id, settings)
        return DirectDownloadLinkOut(
            url=url,
            provider="modal",
            expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
            size=int(node.size or 0),
            filename=node.name,
        )

    root_path = request.scope.get("root_path", "")
    return DirectDownloadLinkOut(
        url=f"{root_path}/files/{quote(node.id, safe='')}/content",
        provider="local",
        size=int(node.size or 0),
        filename=node.name,
    )


@router.head("/files/{node_id}/content")
def head_file(node_id: str, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        node = fs.get_node(node_id)
        assert node is not None
    except FSError as e:
        raise _err(e) from e
    if node.node_type != NodeType.file:
        raise HTTPException(status_code=400, detail="Not a file")
    try:
        chunks = fs.content_chunks(node)
    except FSError as e:
        raise _err(e) from e
    size = int(node.size or sum(int(chunk.size) for chunk in chunks))
    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
            "Content-Type": node.mime_type or "application/octet-stream",
            "X-File-Size": str(size),
            "X-Chunk-Count": str(len(chunks)),
        },
    )
