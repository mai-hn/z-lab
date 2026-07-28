from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from backend.drive.deps import DbSession, StorageDep
from backend.drive.models import FileNode
from backend.drive.schemas import (
    CopyRequest,
    CreateDirectoryRequest,
    DirectoryListing,
    FileInfoOut,
    FileNodeOut,
    MoveRequest,
    RenameRequest,
)
from backend.drive.services.fs import FSError, FileService

router = APIRouter(prefix="/files", tags=["files"])


def _err(e: FSError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"message": e.message, "code": e.code})


@router.get("", response_model=DirectoryListing)
def list_files(
    db: DbSession,
    storage: StorageDep,
    parent_id: str | None = None,
    path: str | None = Query(None, description="Virtual path, e.g. /docs/images"),
):
    fs = FileService(db, storage)
    try:
        parent, items = fs.list_directory(parent_id=parent_id, path=path)
        parent_out = fs.to_out(parent) if parent else None
        path_str = fs.node_path(parent) if parent else (path or "/")
        return DirectoryListing(
            path=path_str,
            node=parent_out,
            items=[fs.to_out(i) for i in items],
            total=len(items),
        )
    except FSError as e:
        raise _err(e) from e


@router.post("/directories", response_model=FileNodeOut, status_code=201)
def create_directory(body: CreateDirectoryRequest, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        node = fs.create_directory(name=body.name, parent_id=body.parent_id, path=body.path)
        return fs.to_out(node)
    except FSError as e:
        raise _err(e) from e


@router.get("/{node_id}", response_model=FileInfoOut)
def get_file_info(node_id: str, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        node = fs.get_node(node_id)
        assert node is not None
        out = fs.to_out(node)
        refs = (
            db.execute(
                select(func.count())
                .select_from(FileNode)
                .where(FileNode.content_id == node.content_id)
            ).scalar()
            if node.content_id
            else 0
        ) or 0
        return FileInfoOut(
            **out.model_dump(),
            storage_key=node.storage_key,
            content_id=node.content_id,
            reference_count=int(refs),
        )
    except FSError as e:
        raise _err(e) from e


@router.post("/{node_id}/rename", response_model=FileNodeOut)
def rename(node_id: str, body: RenameRequest, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        node = fs.rename_node(node_id, body.name)
        return fs.to_out(node)
    except FSError as e:
        raise _err(e) from e


@router.post("/{node_id}/move", response_model=FileNodeOut)
def move(node_id: str, body: MoveRequest, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        node = fs.move_node(node_id, target_parent_id=body.target_parent_id, target_path=body.target_path)
        return fs.to_out(node)
    except FSError as e:
        raise _err(e) from e


@router.post("/{node_id}/copy", response_model=FileNodeOut, status_code=201)
def copy(node_id: str, body: CopyRequest, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        node = fs.copy_node(
            node_id,
            target_parent_id=body.target_parent_id,
            target_path=body.target_path,
            new_name=body.new_name,
        )
        return fs.to_out(node)
    except FSError as e:
        raise _err(e) from e


@router.delete("/{node_id}", status_code=204)
def delete(node_id: str, db: DbSession, storage: StorageDep):
    fs = FileService(db, storage)
    try:
        fs.delete_node(node_id)
    except FSError as e:
        raise _err(e) from e
