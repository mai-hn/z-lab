from __future__ import annotations

import hashlib
import hmac
import time
from datetime import timezone
from email.utils import format_datetime
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException

from backend.drive.config import Settings
from backend.drive.deps import DbSession
from backend.drive.models import NodeType
from backend.drive.services.fs import FSError, FileService

SIGNATURE_VERSION = "v1"


def _payload(node_id: str, expires: int) -> bytes:
    return f"{SIGNATURE_VERSION}\n{node_id}\n{expires}".encode()


def sign_download(node_id: str, expires: int, signing_key: str) -> str:
    if not signing_key:
        raise ValueError("DRIVE_DOWNLOAD_SIGNING_KEY is not configured")
    return hmac.new(signing_key.encode(), _payload(node_id, expires), hashlib.sha256).hexdigest()


def verify_download_signature(
    node_id: str,
    expires: int,
    signature: str,
    signing_key: str,
    *,
    now: int | None = None,
) -> None:
    if not signing_key:
        raise HTTPException(503, "Direct download signing is not configured")
    current = int(time.time()) if now is None else now
    if expires < current:
        raise HTTPException(410, "Download link has expired")
    expected = sign_download(node_id, expires, signing_key)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid download signature")


def modal_download_enabled(settings: Settings, storage_backend: str) -> bool:
    parsed = urlsplit(settings.modal_download_url.strip())
    return (
        storage_backend == "modal"
        and parsed.scheme == "https"
        and bool(parsed.netloc)
        and bool(settings.download_signing_key)
    )


def create_modal_download_url(
    node_id: str,
    settings: Settings,
    *,
    now: int | None = None,
) -> tuple[str, int]:
    current = int(time.time()) if now is None else now
    expires = current + settings.download_link_ttl_seconds
    signature = sign_download(node_id, expires, settings.download_signing_key)
    base = urlsplit(settings.modal_download_url.strip())
    path = f"{base.path.rstrip('/')}/download/{quote(node_id, safe='')}"
    query = urlencode(
        {
            "expires": expires,
            "signature": signature,
        }
    )
    if base.query:
        query = f"{base.query}&{query}"
    return urlunsplit((base.scheme, base.netloc, path, query, base.fragment)), expires


def _etag(node) -> str:
    if node.sha256:
        return f'"{node.sha256}"'
    stamp = int(node.modified_at.replace(tzinfo=timezone.utc).timestamp())
    return f'W/"{node.id}-{stamp}"'


def create_manifest_router(storage, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["direct download"])

    @router.get(
        "/internal/drive/download-manifests/{node_id}",
        include_in_schema=False,
    )
    def get_download_manifest(
        node_id: str,
        expires: int,
        signature: str,
        db: DbSession,
    ) -> dict:
        """Return metadata after validating the short-lived Modal callback signature."""
        verify_download_signature(node_id, expires, signature, settings.download_signing_key)
        fs = FileService(db, storage)
        try:
            node = fs.get_node(node_id)
            assert node is not None
            if node.node_type != NodeType.file:
                raise HTTPException(400, "Not a file")
            chunks = fs.content_chunks(node)
        except FSError as error:
            raise HTTPException(error.status, error.message) from error

        return {
            "version": 1,
            "node_id": node.id,
            "content_id": node.content_id,
            "filename": node.name,
            "size": int(node.size or sum(int(chunk.size) for chunk in chunks)),
            "mime_type": node.mime_type or "application/octet-stream",
            "etag": _etag(node),
            "last_modified": format_datetime(
                node.modified_at.replace(tzinfo=timezone.utc),
                usegmt=True,
            ),
            "chunks": [
                {
                    "index": chunk.chunk_index,
                    "storage_key": chunk.storage_key,
                    "size": int(chunk.size),
                }
                for chunk in chunks
            ],
        }

    return router
