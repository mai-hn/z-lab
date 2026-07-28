from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from pathlib import Path

INVALID_NAME_RE = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def new_id() -> str:
    return str(uuid.uuid4())


def sanitize_filename(name: str) -> str:
    name = name.strip().replace("\x00", "")
    name = INVALID_NAME_RE.sub("_", name)
    name = name.rstrip(". ")
    if not name or name in (".", ".."):
        name = "unnamed"
    return name[:512]


def split_ext(name: str) -> tuple[str, str | None]:
    p = Path(name)
    if not p.suffix:
        return name, None
    return p.stem, p.suffix.lstrip(".").lower()


def guess_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


def file_type_category(mime: str | None, ext: str | None) -> str:
    if not mime and not ext:
        return "other"
    m = (mime or "").lower()
    e = (ext or "").lower()
    if m.startswith("image/") or e in {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "heic"}:
        return "image"
    if m.startswith("video/") or e in {"mp4", "mkv", "webm", "avi", "mov", "flv", "m4v"}:
        return "video"
    if m.startswith("audio/") or e in {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}:
        return "audio"
    if e in {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv", "rtf", "epub"}:
        return "document"
    if e in {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz"}:
        return "archive"
    return "other"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_name(existing: set[str], name: str) -> str:
    if name not in existing:
        return name
    stem, ext = split_ext(name)
    ext_part = f".{ext}" if ext else ""
    i = 1
    while True:
        candidate = f"{stem} ({i}){ext_part}"
        if candidate not in existing:
            return candidate
        i += 1


def parse_completed_set(raw: str) -> set[int]:
    if not raw or not raw.strip():
        return set()
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def serialize_completed_set(indices: set[int]) -> str:
    return ",".join(str(i) for i in sorted(indices))


def is_magnet(url: str) -> bool:
    return url.strip().lower().startswith("magnet:?")


def format_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.2f} {u}" if u != "B" else f"{int(size)} {u}"
        size /= 1024
    return f"{n} B"
