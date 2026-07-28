from __future__ import annotations

from pathlib import PurePosixPath

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.drive.models import (
    DavProperty,
    FileNode,
    NodeType,
    StoredChunk,
    StoredObject,
    utcnow,
)
from backend.drive.schemas import ConflictPolicy, FileNodeOut
from backend.drive.utils import (
    guess_mime,
    new_id,
    sanitize_filename,
    split_ext,
    unique_name,
)


class FSError(Exception):
    def __init__(self, message: str, code: str = "fs_error", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class FileService:
    def __init__(self, db: Session, storage):
        self.db = db
        self.storage = storage

    # ---- path helpers ----

    def get_node(self, node_id: str | None) -> FileNode | None:
        if node_id is None:
            return None
        node = self.db.get(FileNode, node_id)
        if not node or node.is_trashed:
            raise FSError("Node not found", "not_found", 404)
        return node

    def ensure_directory(self, node_id: str | None) -> FileNode | None:
        if node_id is None:
            return None
        node = self.get_node(node_id)
        assert node is not None
        if node.node_type != NodeType.directory:
            raise FSError("Parent is not a directory", "not_directory", 400)
        return node

    def resolve_path(self, path: str) -> FileNode | None:
        """Resolve absolute virtual path like /a/b/c. Returns None for root."""
        path = path.strip()
        if not path or path == "/":
            return None
        parts = [p for p in PurePosixPath(path).parts if p != "/"]
        current_id = None
        node = None
        for part in parts:
            node = self._child_by_name(current_id, part)
            if node is None:
                raise FSError(f"Path not found: {path}", "not_found", 404)
            current_id = node.id
        return node

    def resolve_parent(self, parent_id: str | None = None, path: str | None = None) -> str | None:
        if parent_id is not None:
            self.ensure_directory(parent_id)
            return parent_id
        if path is not None:
            node = self.resolve_path(path)
            if node is None:
                return None
            if node.node_type != NodeType.directory:
                raise FSError("Path is not a directory", "not_directory", 400)
            return node.id
        return None

    def node_path(self, node: FileNode | None) -> str:
        if node is None:
            return "/"
        parts: list[str] = []
        current: FileNode | None = node
        seen = set()
        while current is not None:
            if current.id in seen:
                break
            seen.add(current.id)
            parts.append(current.name)
            if current.parent_id is None:
                break
            current = self.db.get(FileNode, current.parent_id)
        return "/" + "/".join(reversed(parts))

    def to_out(self, node: FileNode) -> FileNodeOut:
        chunk_count = int(node.content.chunk_count) if node.content_id and node.content else 0
        return FileNodeOut(
            id=node.id,
            parent_id=node.parent_id,
            name=node.name,
            node_type=node.node_type.value,  # type: ignore[arg-type]
            size=node.size or 0,
            mime_type=node.mime_type,
            extension=node.extension,
            sha256=node.sha256,
            chunk_count=chunk_count,
            storage_layout=(
                "metadata"
                if node.node_type == NodeType.directory
                else ("chunked" if chunk_count > 1 else "single")
            ),
            path=self.node_path(node),
            created_at=node.created_at,
            modified_at=node.modified_at,
        )

    def _child_by_name(self, parent_id: str | None, name: str) -> FileNode | None:
        q = select(FileNode).where(
            FileNode.parent_id == parent_id,
            FileNode.name == name,
            FileNode.is_trashed.is_(False),
        )
        return self.db.execute(q).scalar_one_or_none()

    def list_names(self, parent_id: str | None) -> set[str]:
        q = select(FileNode.name).where(
            FileNode.parent_id == parent_id,
            FileNode.is_trashed.is_(False),
        )
        return set(self.db.execute(q).scalars().all())

    def apply_conflict(
        self,
        parent_id: str | None,
        name: str,
        conflict: ConflictPolicy | str,
    ) -> tuple[str, FileNode | None]:
        """Return (final_name, existing_node_to_overwrite_or_None)."""
        if isinstance(conflict, str):
            conflict = ConflictPolicy(conflict)
        existing = self._child_by_name(parent_id, name)
        if existing is None:
            return name, None
        if conflict == ConflictPolicy.reject:
            raise FSError(f"File already exists: {name}", "conflict", 409)
        if conflict == ConflictPolicy.overwrite:
            if existing.node_type == NodeType.directory:
                raise FSError("Cannot overwrite a directory", "conflict", 409)
            return name, existing
        # rename
        names = self.list_names(parent_id)
        return unique_name(names, name), None

    # ---- directory ops ----

    def create_directory(self, name: str, parent_id: str | None = None, path: str | None = None) -> FileNode:
        parent_id = self.resolve_parent(parent_id, path)
        name = sanitize_filename(name)
        if self._child_by_name(parent_id, name):
            raise FSError(f"Directory already exists: {name}", "conflict", 409)
        node = FileNode(
            id=new_id(),
            parent_id=parent_id,
            name=name,
            node_type=NodeType.directory,
            size=0,
        )
        self.db.add(node)
        self.db.flush()
        return node

    def list_directory(
        self,
        parent_id: str | None = None,
        path: str | None = None,
    ) -> tuple[FileNode | None, list[FileNode]]:
        if path is not None and parent_id is None:
            parent = self.resolve_path(path)
            parent_id = parent.id if parent else None
        elif parent_id is not None:
            parent = self.ensure_directory(parent_id)
        else:
            parent = None

        q = (
            select(FileNode)
            .where(FileNode.parent_id == parent_id, FileNode.is_trashed.is_(False))
            .order_by(FileNode.node_type.desc(), FileNode.name.asc())
        )
        items = list(self.db.execute(q).scalars().all())
        return parent, items

    # ---- file registration ----

    def create_content_manifest(
        self,
        *,
        chunks: list[dict],
        total_size: int,
        sha256: str | None,
        chunk_size: int,
        backend: str | None = None,
    ) -> StoredObject:
        if not chunks:
            raise FSError("Content manifest has no chunks", "empty_manifest", 500)
        ordered = sorted(chunks, key=lambda item: int(item["index"]))
        if [int(item["index"]) for item in ordered] != list(range(len(ordered))):
            raise FSError("Content manifest is not contiguous", "bad_manifest", 500)
        if sum(int(item["size"]) for item in ordered) != int(total_size):
            raise FSError("Content manifest size mismatch", "bad_manifest", 500)
        content = StoredObject(
            id=new_id(),
            total_size=total_size,
            chunk_size=chunk_size,
            chunk_count=len(ordered),
            sha256=sha256,
            backend=backend or self.storage.backend_name(),
        )
        self.db.add(content)
        self.db.flush()
        for item in ordered:
            self.db.add(
                StoredChunk(
                    content_id=content.id,
                    chunk_index=int(item["index"]),
                    storage_key=str(item["storage_key"]),
                    size=int(item["size"]),
                    sha256=item.get("sha256"),
                )
            )
        self.db.flush()
        return content

    def register_file(
        self,
        name: str,
        storage_key: str,
        size: int,
        sha256: str | None,
        content_id: str | None = None,
        parent_id: str | None = None,
        conflict: ConflictPolicy | str = ConflictPolicy.rename,
        mime_type: str | None = None,
    ) -> FileNode:
        name = sanitize_filename(name)
        final_name, overwrite = self.apply_conflict(parent_id, name, conflict)
        _, ext = split_ext(final_name)
        mime = mime_type or guess_mime(final_name)

        if content_id is None:
            content = StoredObject(
                id=new_id(),
                total_size=size,
                chunk_size=size,
                chunk_count=1,
                sha256=sha256,
                backend=self.storage.backend_name(),
            )
            self.db.add(content)
            self.db.flush()
            self.db.add(
                StoredChunk(
                    content_id=content.id,
                    chunk_index=0,
                    storage_key=storage_key,
                    size=size,
                    sha256=sha256,
                )
            )
            self.db.flush()
            content_id = content.id

        if overwrite is not None:
            # Replace only the metadata reference. The old immutable content is
            # removed remotely only when no other copied node still references it.
            old_content_id = overwrite.content_id
            old_key = overwrite.storage_key if old_content_id is None else None
            overwrite.name = final_name
            overwrite.storage_key = storage_key if old_content_id is None and content_id is None else None
            overwrite.content_id = content_id
            overwrite.size = size
            overwrite.sha256 = sha256
            overwrite.mime_type = mime
            overwrite.extension = ext
            overwrite.modified_at = utcnow()
            self.db.flush()
            if old_content_id and old_content_id != content_id:
                self._delete_content_if_unreferenced(old_content_id)
            elif old_key and old_key != storage_key:
                self.storage.delete_file(old_key)
            return overwrite

        node = FileNode(
            id=new_id(),
            parent_id=parent_id,
            name=final_name,
            node_type=NodeType.file,
            storage_key=None if content_id else storage_key,
            content_id=content_id,
            size=size,
            mime_type=mime,
            extension=ext,
            sha256=sha256,
        )
        self.db.add(node)
        self.db.flush()
        return node

    def delete_node(self, node_id: str, recursive: bool = True) -> None:
        node = self.get_node(node_id)
        assert node is not None
        content_ids: set[str] = set()
        legacy_keys: set[str] = set()
        self._delete_recursive(node, content_ids, legacy_keys)
        self.db.flush()
        for content_id in content_ids:
            self._delete_content_if_unreferenced(content_id)
        for storage_key in legacy_keys:
            self.storage.delete_file(storage_key)

    def _delete_recursive(
        self, node: FileNode, content_ids: set[str], legacy_keys: set[str]
    ) -> None:
        if node.node_type == NodeType.directory:
            children = list(
                self.db.execute(
                    select(FileNode).where(FileNode.parent_id == node.id, FileNode.is_trashed.is_(False))
                ).scalars()
            )
            for child in children:
                self._delete_recursive(child, content_ids, legacy_keys)
        else:
            if node.content_id:
                content_ids.add(node.content_id)
            elif node.storage_key:
                legacy_keys.add(node.storage_key)
        self.db.execute(delete(DavProperty).where(DavProperty.node_key == node.id))
        self.db.delete(node)
        self.db.flush()

    def _delete_content_if_unreferenced(self, content_id: str) -> None:
        refs = self.db.execute(
            select(func.count()).select_from(FileNode).where(FileNode.content_id == content_id)
        ).scalar() or 0
        if refs:
            return
        content = self.db.get(StoredObject, content_id)
        if content is None:
            return
        chunks = list(
            self.db.execute(
                select(StoredChunk)
                .where(StoredChunk.content_id == content_id)
                .order_by(StoredChunk.chunk_index)
            ).scalars()
        )
        # This is the only physical-content deletion path. ModalStorage maps
        # each call directly to Volume.remove_file().
        for chunk in chunks:
            self.storage.delete_file(chunk.storage_key)
        self.db.delete(content)
        self.db.flush()

    def content_chunks(self, node: FileNode) -> list[StoredChunk]:
        if node.content_id:
            chunks = list(
                self.db.execute(
                    select(StoredChunk)
                    .where(StoredChunk.content_id == node.content_id)
                    .order_by(StoredChunk.chunk_index)
                ).scalars()
            )
            if chunks:
                return chunks
        if node.storage_key:
            # Compatibility for metadata created before the manifest migration.
            return [
                StoredChunk(
                    content_id=node.content_id or "",
                    chunk_index=0,
                    storage_key=node.storage_key,
                    size=int(node.size or 0),
                    sha256=node.sha256,
                )
            ]
        raise FSError("File has no storage content", "no_storage", 404)

    def rename_node(self, node_id: str, new_name: str) -> FileNode:
        node = self.get_node(node_id)
        assert node is not None
        new_name = sanitize_filename(new_name)
        other = self._child_by_name(node.parent_id, new_name)
        if other and other.id != node.id:
            raise FSError(f"Name already exists: {new_name}", "conflict", 409)
        node.name = new_name
        if node.node_type == NodeType.file:
            _, ext = split_ext(new_name)
            node.extension = ext
            node.mime_type = guess_mime(new_name)
        node.modified_at = utcnow()
        self.db.flush()
        return node

    def move_node(self, node_id: str, target_parent_id: str | None = None, target_path: str | None = None) -> FileNode:
        node = self.get_node(node_id)
        assert node is not None
        target_parent_id = self.resolve_parent(target_parent_id, target_path)

        # prevent moving into self/descendant
        if node.node_type == NodeType.directory and target_parent_id is not None:
            if target_parent_id == node.id or self._is_descendant(target_parent_id, node.id):
                raise FSError("Cannot move directory into itself", "invalid_move", 400)

        other = self._child_by_name(target_parent_id, node.name)
        if other and other.id != node.id:
            raise FSError(f"Name already exists in target: {node.name}", "conflict", 409)

        node.parent_id = target_parent_id
        node.modified_at = utcnow()
        self.db.flush()
        return node

    def _is_descendant(self, node_id: str, ancestor_id: str) -> bool:
        current = self.db.get(FileNode, node_id)
        seen = set()
        while current is not None:
            if current.id in seen:
                return False
            seen.add(current.id)
            if current.id == ancestor_id:
                return True
            if current.parent_id is None:
                return False
            current = self.db.get(FileNode, current.parent_id)
        return False

    def copy_node(
        self,
        node_id: str,
        target_parent_id: str | None = None,
        target_path: str | None = None,
        new_name: str | None = None,
    ) -> FileNode:
        node = self.get_node(node_id)
        assert node is not None
        target_parent_id = self.resolve_parent(target_parent_id, target_path)
        name = sanitize_filename(new_name or node.name)
        names = self.list_names(target_parent_id)
        name = unique_name(names, name)
        return self._copy_recursive(node, target_parent_id, name)

    def _copy_recursive(self, node: FileNode, parent_id: str | None, name: str) -> FileNode:
        if node.node_type == NodeType.directory:
            new_node = FileNode(
                id=new_id(),
                parent_id=parent_id,
                name=name,
                node_type=NodeType.directory,
                size=0,
            )
            self.db.add(new_node)
            self.db.flush()
            children = list(
                self.db.execute(
                    select(FileNode).where(FileNode.parent_id == node.id, FileNode.is_trashed.is_(False))
                ).scalars()
            )
            child_names = set()
            for child in children:
                cname = unique_name(child_names, child.name)
                child_names.add(cname)
                self._copy_recursive(child, new_node.id, cname)
            return new_node

        if not node.content_id and not node.storage_key:
            raise FSError("File has no storage", "no_storage", 500)
        new_node = FileNode(
            id=new_id(),
            parent_id=parent_id,
            name=name,
            node_type=NodeType.file,
            # Shared immutable content: no Modal read/write and no local cache.
            storage_key=None,
            content_id=node.content_id,
            size=node.size,
            mime_type=node.mime_type,
            extension=node.extension,
            sha256=node.sha256,
        )
        self.db.add(new_node)
        self.db.flush()
        return new_node

    def stats(self) -> dict:
        file_count = self.db.execute(
            select(func.count()).select_from(FileNode).where(
                FileNode.node_type == NodeType.file, FileNode.is_trashed.is_(False)
            )
        ).scalar() or 0
        dir_count = self.db.execute(
            select(func.count()).select_from(FileNode).where(
                FileNode.node_type == NodeType.directory, FileNode.is_trashed.is_(False)
            )
        ).scalar() or 0
        logical = self.db.execute(
            select(func.sum(FileNode.size)).where(
                FileNode.node_type == NodeType.file, FileNode.is_trashed.is_(False)
            )
        ).scalar() or 0
        physical = self.db.execute(select(func.sum(StoredObject.total_size))).scalar() or 0
        chunked = self.db.execute(
            select(func.count()).select_from(StoredObject).where(StoredObject.chunk_count > 1)
        ).scalar() or 0
        shared = self.db.execute(
            select(func.count())
            .select_from(
                select(FileNode.content_id)
                .where(FileNode.content_id.is_not(None))
                .group_by(FileNode.content_id)
                .having(func.count(FileNode.id) > 1)
                .subquery()
            )
        ).scalar() or 0
        return {
            "used_bytes": int(physical),
            "logical_bytes": int(logical),
            "saved_bytes": max(0, int(logical) - int(physical)),
            "chunked_files": int(chunked),
            "shared_contents": int(shared),
            "file_count": file_count,
            "directory_count": dir_count,
        }
