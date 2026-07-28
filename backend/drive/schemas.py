from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ConflictPolicy(str, Enum):
    reject = "reject"
    overwrite = "overwrite"
    rename = "rename"


class NodeType(str, Enum):
    file = "file"
    directory = "directory"


class FileNodeOut(BaseModel):
    id: str
    parent_id: Optional[str] = None
    name: str
    node_type: NodeType
    size: int = 0
    mime_type: Optional[str] = None
    extension: Optional[str] = None
    sha256: Optional[str] = None
    chunk_count: int = 0
    storage_layout: str = "metadata"
    path: str = "/"
    created_at: datetime
    modified_at: datetime

    model_config = {"from_attributes": True}


class DirectoryListing(BaseModel):
    path: str
    node: Optional[FileNodeOut] = None
    items: List[FileNodeOut]
    total: int


class CreateDirectoryRequest(BaseModel):
    parent_id: Optional[str] = None
    path: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=512)


class RenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)


class MoveRequest(BaseModel):
    target_parent_id: Optional[str] = None
    target_path: Optional[str] = None


class CopyRequest(BaseModel):
    target_parent_id: Optional[str] = None
    target_path: Optional[str] = None
    new_name: Optional[str] = None


class FileInfoOut(FileNodeOut):
    storage_key: Optional[str] = None
    content_id: Optional[str] = None
    reference_count: int = 0


class StorageStats(BaseModel):
    used_bytes: int
    logical_bytes: int = 0
    saved_bytes: int = 0
    chunked_files: int = 0
    shared_contents: int = 0
    file_count: int
    directory_count: int
    upload_sessions: int
    offline_tasks: int


class CreateUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=512)
    total_size: int = Field(..., gt=0)
    parent_id: Optional[str] = None
    path: Optional[str] = None
    chunk_size: Optional[int] = None
    file_hash: Optional[str] = None
    conflict: ConflictPolicy = ConflictPolicy.rename


class UploadSessionOut(BaseModel):
    id: str
    filename: str
    parent_id: Optional[str] = None
    total_size: int
    chunk_size: int
    total_chunks: int
    completed_chunks: int
    completed_indices: List[int]
    missing_indices: List[int]
    file_hash: Optional[str] = None
    conflict: ConflictPolicy
    status: str
    result_node_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    progress: float

    model_config = {"from_attributes": True}


class CompleteUploadRequest(BaseModel):
    file_hash: Optional[str] = None


class ChunkUploadResult(BaseModel):
    upload_id: str
    chunk_index: int
    completed_chunks: int
    total_chunks: int
    progress: float
    already_uploaded: bool = False


class SearchQuery(BaseModel):
    q: Optional[str] = None
    extension: Optional[str] = None
    mime_prefix: Optional[str] = None
    file_type: Optional[
        Literal["file", "directory", "image", "video", "audio", "document", "archive", "other"]
    ] = None
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    modified_after: Optional[datetime] = None
    modified_before: Optional[datetime] = None
    parent_id: Optional[str] = None
    path: Optional[str] = None
    recursive: bool = True
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    items: List[FileNodeOut]
    total: int
    limit: int
    offset: int


class CreateOfflineRequest(BaseModel):
    url: str = Field(..., min_length=1)
    parent_id: Optional[str] = None
    path: Optional[str] = None
    filename: Optional[str] = None


class OfflineTaskOut(BaseModel):
    id: str
    url: str
    filename: Optional[str] = None
    parent_id: Optional[str] = None
    status: str
    progress: float
    downloaded_size: int
    total_size: int
    speed: float
    error_message: Optional[str] = None
    result_node_id: Optional[str] = None
    is_magnet: bool
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ApiError(BaseModel):
    detail: str
    code: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
