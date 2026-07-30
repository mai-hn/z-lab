"""Modal Volume-backed file API for TOOLBOX.

Deploy with:
    MODAL_DRIVE_VOLUME_NAME=toolbox-drive modal deploy modal/modal_drive.py
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import modal

APP_NAME = "toolbox-modal-drive"
MOUNT_PATH = Path("/drive")
VOLUME_NAME = os.environ.get("MODAL_DRIVE_VOLUME_NAME", "toolbox-drive")

app = modal.App(APP_NAME)
image = modal.Image.debian_slim(python_version="3.12").uv_pip_install(
    "fastapi[standard]"
)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def normalize_remote_path(value: str | None) -> str:
    raw = (value or "/").strip().replace("\\", "/")
    if "\x00" in raw or len(raw) > 4096:
        raise ValueError("Invalid path")

    parts = []
    for part in PurePosixPath("/" + raw.lstrip("/")).parts:
        if part in {"", "/", "."}:
            continue
        if part == "..":
            raise ValueError("Parent traversal is not allowed")
        parts.append(part)

    return "/" + "/".join(parts)


def resolve_remote_path(value: str | None) -> tuple[str, Path]:
    remote_path = normalize_remote_path(value)
    candidate = (MOUNT_PATH / remote_path.lstrip("/")).resolve()
    root = MOUNT_PATH.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path escapes the drive")
    return remote_path, candidate


def safe_file_name(value: str | None) -> str:
    name = (value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or "\x00" in name or len(name) > 255:
        raise ValueError("Invalid file name")
    return name


def file_entry(path: Path) -> dict:
    stat = path.stat()
    relative = path.relative_to(MOUNT_PATH).as_posix()
    return {
        "name": path.name,
        "path": "/" + relative,
        "type": "directory" if path.is_dir() else "file",
        "size": 0 if path.is_dir() else stat.st_size,
        "modifiedAt": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    }


@app.function(
    image=image,
    volumes={str(MOUNT_PATH): volume},
    timeout=60 * 60,
)
@modal.asgi_app(requires_proxy_auth=True)
def drive_api():
    from fastapi import FastAPI, File, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse
    from pydantic import BaseModel, Field

    web = FastAPI(title="TOOLBOX Modal Drive API", docs_url=None, redoc_url=None)

    class FolderPayload(BaseModel):
        path: str = Field(min_length=1, max_length=4096)

    class RenamePayload(BaseModel):
        path: str = Field(min_length=1, max_length=4096)
        new_name: str = Field(alias="newName", min_length=1, max_length=255)

    def checked_path(value: str | None) -> tuple[str, Path]:
        try:
            return resolve_remote_path(value)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @web.get("/health")
    def health():
        return {"ok": True, "volume": VOLUME_NAME}

    @web.get("/files")
    def list_files(path: str = Query(default="/", max_length=4096)):
        volume.reload()
        remote_path, local_path = checked_path(path)
        if not local_path.exists():
            raise HTTPException(status_code=404, detail="Directory not found")
        if not local_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        entries = sorted(
            (file_entry(item) for item in local_path.iterdir()),
            key=lambda item: (item["type"] != "directory", item["name"].lower()),
        )
        return {"ok": True, "path": remote_path, "entries": entries}

    @web.post("/folders")
    def create_folder(payload: FolderPayload):
        volume.reload()
        remote_path, local_path = checked_path(payload.path)
        if local_path.exists():
            raise HTTPException(status_code=409, detail="Path already exists")
        local_path.mkdir(parents=True, exist_ok=False)
        volume.commit()
        return {"ok": True, "path": remote_path, "entry": file_entry(local_path)}

    @web.post("/upload")
    async def upload_file(
        path: str = Query(default="/", max_length=4096),
        overwrite: bool = Query(default=False),
        file: UploadFile = File(...),
    ):
        volume.reload()
        remote_directory, local_directory = checked_path(path)
        if not local_directory.exists() or not local_directory.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")

        try:
            file_name = safe_file_name(file.filename)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        target = local_directory / file_name
        if target.exists() and not overwrite:
            raise HTTPException(status_code=409, detail="File already exists")

        temporary = local_directory / f".upload-{uuid.uuid4().hex}"
        try:
            with temporary.open("wb") as destination:
                while chunk := await file.read(1024 * 1024):
                    destination.write(chunk)
            temporary.replace(target)
            volume.commit()
        finally:
            await file.close()
            if temporary.exists():
                temporary.unlink()

        return {
            "ok": True,
            "path": remote_directory,
            "entry": file_entry(target),
        }

    @web.patch("/files")
    def rename_file(payload: RenamePayload):
        volume.reload()
        remote_path, local_path = checked_path(payload.path)
        if remote_path == "/" or not local_path.exists():
            raise HTTPException(status_code=404, detail="File or folder not found")

        try:
            new_name = safe_file_name(payload.new_name)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        destination = local_path.with_name(new_name)
        if destination.exists():
            raise HTTPException(status_code=409, detail="Destination already exists")
        local_path.rename(destination)
        volume.commit()
        return {"ok": True, "entry": file_entry(destination)}

    @web.delete("/files")
    def delete_file(
        path: str = Query(min_length=1, max_length=4096),
        recursive: bool = Query(default=False),
    ):
        volume.reload()
        remote_path, local_path = checked_path(path)
        if remote_path == "/":
            raise HTTPException(status_code=400, detail="Cannot delete drive root")
        if not local_path.exists():
            raise HTTPException(status_code=404, detail="File or folder not found")

        if local_path.is_dir():
            if recursive:
                shutil.rmtree(local_path)
            else:
                try:
                    local_path.rmdir()
                except OSError as error:
                    raise HTTPException(
                        status_code=409, detail="Directory is not empty"
                    ) from error
        else:
            local_path.unlink()

        volume.commit()
        return {"ok": True, "path": remote_path}

    @web.get("/download")
    def download_file(path: str = Query(min_length=1, max_length=4096)):
        volume.reload()
        remote_path, local_path = checked_path(path)
        if remote_path == "/" or not local_path.exists() or not local_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        media_type, _ = mimetypes.guess_type(local_path.name)
        return FileResponse(
            path=local_path,
            filename=local_path.name,
            media_type=media_type or "application/octet-stream",
        )

    return web
