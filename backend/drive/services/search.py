from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from backend.drive.models import FileNode, NodeType
from backend.drive.schemas import SearchQuery
from backend.drive.services.fs import FileService
TYPE_FILTERS = {
    "image": ("image/", {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "heic"}),
    "video": ("video/", {"mp4", "mkv", "webm", "avi", "mov", "flv", "m4v"}),
    "audio": ("audio/", {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}),
    "document": (
        None,
        {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv", "rtf", "epub"},
    ),
    "archive": (None, {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz"}),
}


class SearchService:
    def __init__(self, db: Session, storage):
        self.db = db
        self.fs = FileService(db, storage)

    def _collect_descendant_ids(self, root_id: str | None) -> set[str] | None:
        """If root_id is None and recursive global — return None (no filter).
        Otherwise return set of allowed parent_ids including root's children tree.
        """
        if root_id is None:
            return None

        # BFS all directory ids under root, then nodes whose parent is in that set or is root
        allowed_parents = {root_id}
        queue = [root_id]
        while queue:
            pid = queue.pop()
            rows = self.db.execute(
                select(FileNode.id).where(
                    FileNode.parent_id == pid,
                    FileNode.node_type == NodeType.directory,
                    FileNode.is_trashed.is_(False),
                )
            ).scalars().all()
            for cid in rows:
                if cid not in allowed_parents:
                    allowed_parents.add(cid)
                    queue.append(cid)
        return allowed_parents

    def search(self, query: SearchQuery):
        parent_id = query.parent_id
        if query.path is not None and parent_id is None:
            node = self.fs.resolve_path(query.path) if query.path not in ("", "/") else None
            parent_id = node.id if node else None

        conditions = [FileNode.is_trashed.is_(False)]

        if query.q:
            conditions.append(FileNode.name.ilike(f"%{query.q}%"))

        if query.extension:
            ext = query.extension.lstrip(".").lower()
            conditions.append(FileNode.extension == ext)

        if query.mime_prefix:
            conditions.append(FileNode.mime_type.ilike(f"{query.mime_prefix}%"))

        if query.file_type == "file":
            conditions.append(FileNode.node_type == NodeType.file)
        elif query.file_type == "directory":
            conditions.append(FileNode.node_type == NodeType.directory)
        elif query.file_type == "other":
            conditions.append(FileNode.node_type == NodeType.file)
            # exclude known categories
            known_exts = set()
            for _mime, exts in TYPE_FILTERS.values():
                known_exts |= exts
            conditions.append(
                or_(
                    FileNode.extension.is_(None),
                    FileNode.extension.notin_(known_exts),
                )
            )
        elif query.file_type in TYPE_FILTERS:
            mime_prefix, exts = TYPE_FILTERS[query.file_type]
            parts = [FileNode.extension.in_(exts)]
            if mime_prefix:
                parts.append(FileNode.mime_type.ilike(f"{mime_prefix}%"))
            conditions.append(and_(FileNode.node_type == NodeType.file, or_(*parts)))

        if query.min_size is not None:
            conditions.append(FileNode.size >= query.min_size)
        if query.max_size is not None:
            conditions.append(FileNode.size <= query.max_size)
        if query.created_after is not None:
            conditions.append(FileNode.created_at >= query.created_after.replace(tzinfo=None))
        if query.created_before is not None:
            conditions.append(FileNode.created_at <= query.created_before.replace(tzinfo=None))
        if query.modified_after is not None:
            conditions.append(FileNode.modified_at >= query.modified_after.replace(tzinfo=None))
        if query.modified_before is not None:
            conditions.append(FileNode.modified_at <= query.modified_before.replace(tzinfo=None))

        if not query.recursive:
            conditions.append(FileNode.parent_id == parent_id)
        else:
            if parent_id is not None:
                allowed = self._collect_descendant_ids(parent_id)
                # include nodes under these parents; also optionally the root itself? usually search contents
                conditions.append(FileNode.parent_id.in_(allowed))  # type: ignore[arg-type]

        base = select(FileNode).where(and_(*conditions))
        count_q = select(func.count()).select_from(base.subquery())
        total = self.db.execute(count_q).scalar() or 0

        rows = list(
            self.db.execute(
                base.order_by(FileNode.modified_at.desc())
                .offset(query.offset)
                .limit(query.limit)
            ).scalars().all()
        )
        return rows, total
