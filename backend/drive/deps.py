from __future__ import annotations

import base64
import binascii
from typing import Annotated, Callable, Generator, Union

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from backend.drive.config import Settings, get_settings
from backend.drive.database import get_session
from backend.drive.storage import LocalStorage, ModalVolumeStorage, create_storage

StorageType = Union[LocalStorage, ModalVolumeStorage]


def get_db() -> Generator[Session, None, None]:
    yield from get_session()


def get_storage(request: Request) -> StorageType:
    cached = getattr(request.app.state, "storage", None)
    if cached is not None:
        return cached
    on_commit: Callable[[], None] | None = getattr(request.app.state, "volume_commit", None)
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    backend = getattr(request.app.state, "storage_backend", None)
    storage = create_storage(settings=settings, on_commit=on_commit, backend=backend)
    request.app.state.storage = storage
    return storage


def require_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_token: Annotated[str | None, Header()] = None,
) -> None:
    token = settings.api_token
    if not token:
        return
    provided = x_api_token
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided and authorization and authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:].strip()).decode("utf-8")
            username, _, password = decoded.partition(":")
            provided = password or username
        except (binascii.Error, UnicodeDecodeError):
            provided = None
    if provided != token:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": 'Basic realm="Z-Lab WebDAV"'},
        )


DbSession = Annotated[Session, Depends(get_db)]
StorageDep = Annotated[StorageType, Depends(get_storage)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
