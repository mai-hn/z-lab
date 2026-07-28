"""Physical storage: local disk OR Modal Volume client SDK (no always-on service)."""

from __future__ import annotations

import io
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Protocol, Union

from backend.drive.config import Settings, get_settings
from backend.drive.modal_util import (
    get_volume,
    resolve_backend,
    volume_file_path,
)

logger = logging.getLogger(__name__)

CommitCallback = Callable[[], None]


class StorageProtocol(Protocol):
    def write_file_atomic(self, storage_key: str, source: Path) -> Path: ...
    def write_bytes_atomic(self, storage_key: str, data: bytes) -> Path: ...
    def write_stream_atomic(
        self, storage_key: str, stream: BinaryIO, chunk_size: int = 1024 * 1024
    ) -> tuple[Path, int]: ...
    def write_chunk(self, upload_id: str, index: int, data: bytes | BinaryIO) -> Path: ...
    def upload_chunk_key(self, upload_id: str, index: int) -> str: ...
    def merge_chunks(
        self,
        upload_id: str,
        storage_key: str,
        total_chunks: int,
        expected_size: int | None = None,
    ) -> tuple[Path, int, str]: ...
    def delete_file(self, storage_key: str) -> None: ...
    def delete_upload(self, upload_id: str) -> None: ...
    def delete_offline(self, task_id: str) -> None: ...
    def copy_storage_key(self, src_key: str, dest_key: str) -> Path: ...
    def iter_file(
        self, storage_key: str, start: int = 0, end: int | None = None, chunk_size: int = 1024 * 1024
    ) -> Iterator[bytes]: ...
    def file_size(self, storage_key: str) -> int: ...
    def used_bytes(self) -> int: ...
    def upload_dir(self, upload_id: str) -> Path: ...
    def chunk_path(self, upload_id: str, index: int) -> Path: ...
    def offline_dir(self, task_id: str) -> Path: ...
    def tmp_path(self, name: str) -> Path: ...
    def backend_name(self) -> str: ...


class LocalStorage:
    """Atomic file ops on local filesystem (dev / offline fallback)."""

    def __init__(self, settings: Settings | None = None, on_commit: CommitCallback | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.settings.files_dir.mkdir(parents=True, exist_ok=True)
        self.on_commit = on_commit

    def backend_name(self) -> str:
        return "local"

    def commit(self) -> None:
        if self.on_commit:
            self.on_commit()

    def file_path(self, storage_key: str) -> Path:
        shard = storage_key[:2]
        return self.settings.files_dir / shard / storage_key

    def upload_dir(self, upload_id: str) -> Path:
        d = self.settings.uploads_dir / upload_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def chunk_path(self, upload_id: str, index: int) -> Path:
        return self.upload_dir(upload_id) / f"part_{index:06d}"

    def upload_chunk_key(self, upload_id: str, index: int) -> str:
        return f"{upload_id.replace('-', '')}-{index:06d}"

    def offline_dir(self, task_id: str) -> Path:
        d = self.settings.offline_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def tmp_path(self, name: str) -> Path:
        self.settings.tmp_dir.mkdir(parents=True, exist_ok=True)
        return self.settings.tmp_dir / name

    def write_file_atomic(self, storage_key: str, source: Path) -> Path:
        dest = self.file_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp_path(f".{storage_key}.tmp")
        if source.resolve() != tmp.resolve():
            shutil.copy2(source, tmp)
        os.replace(tmp, dest)
        self.commit()
        return dest

    def write_bytes_atomic(self, storage_key: str, data: bytes) -> Path:
        dest = self.file_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp_path(f".{storage_key}.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
        self.commit()
        return dest

    def write_stream_atomic(
        self, storage_key: str, stream: BinaryIO, chunk_size: int = 1024 * 1024
    ) -> tuple[Path, int]:
        dest = self.file_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp_path(f".{storage_key}.tmp")
        size = 0
        try:
            with open(tmp, "wb") as f:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
            self.commit()
            return dest, size
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def write_chunk(self, upload_id: str, index: int, data: bytes | BinaryIO) -> Path:
        path = self.chunk_path(upload_id, index)
        tmp = path.with_suffix(".tmp")
        try:
            if isinstance(data, bytes):
                with open(tmp, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            else:
                with open(tmp, "wb") as f:
                    shutil.copyfileobj(data, f)
                    f.flush()
                    os.fsync(f.fileno())
            os.replace(tmp, path)
            self.commit()
            return path
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def merge_chunks(
        self,
        upload_id: str,
        storage_key: str,
        total_chunks: int,
        expected_size: int | None = None,
    ) -> tuple[Path, int, str]:
        from backend.drive.utils import sha256_file

        dest = self.file_path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.tmp_path(f".{storage_key}.merge.tmp")
        size = 0
        try:
            with open(tmp, "wb") as out:
                for i in range(total_chunks):
                    part = self.chunk_path(upload_id, i)
                    if not part.exists():
                        raise FileNotFoundError(f"Missing chunk {i}")
                    with open(part, "rb") as inp:
                        while True:
                            chunk = inp.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            if expected_size is not None and size != expected_size:
                raise ValueError(f"Size mismatch: expected {expected_size}, got {size}")
            digest = sha256_file(tmp)
            os.replace(tmp, dest)
            self.commit()
            return dest, size, digest
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def delete_file(self, storage_key: str) -> None:
        path = self.file_path(storage_key)
        if path.exists():
            path.unlink()
            self.commit()

    def delete_upload(self, upload_id: str) -> None:
        d = self.settings.uploads_dir / upload_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            self.commit()

    def delete_offline(self, task_id: str) -> None:
        d = self.settings.offline_dir / task_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            self.commit()

    def copy_storage_key(self, src_key: str, dest_key: str) -> Path:
        src = self.file_path(src_key)
        if not src.exists():
            raise FileNotFoundError(src_key)
        return self.write_file_atomic(dest_key, src)

    def open_file(self, storage_key: str) -> Path:
        path = self.file_path(storage_key)
        if not path.exists():
            raise FileNotFoundError(storage_key)
        return path

    def iter_file(
        self,
        storage_key: str,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        path = self.open_file(storage_key)
        with open(path, "rb") as f:
            f.seek(start)
            remaining = None if end is None else (end - start + 1)
            while True:
                if remaining is not None and remaining <= 0:
                    break
                to_read = chunk_size if remaining is None else min(chunk_size, remaining)
                data = f.read(to_read)
                if not data:
                    break
                if remaining is not None:
                    remaining -= len(data)
                yield data

    def file_size(self, storage_key: str) -> int:
        return self.open_file(storage_key).stat().st_size

    def used_bytes(self) -> int:
        total = 0
        files_dir = self.settings.files_dir
        if not files_dir.exists():
            return 0
        for root, _dirs, files in os.walk(files_dir):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    pass
        return total


class ModalVolumeStorage:
    """Store file blobs on Modal Volume via client SDK.

    - Upload: local temp → volume.batch_upload() → delete local temp
    - Download: volume.read_file() stream (no container)
    - Chunks/merge: local temp only, final object on Volume
    - No always-on Modal web service required
    """

    def __init__(self, settings: Settings | None = None, on_commit: CommitCallback | None = None):
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.on_commit = on_commit
        self._vol = get_volume(self.settings)

    def backend_name(self) -> str:
        return "modal"

    def _remote(self, storage_key: str) -> str:
        return volume_file_path(storage_key)

    def upload_dir(self, upload_id: str) -> Path:
        d = self.settings.uploads_dir / upload_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def chunk_path(self, upload_id: str, index: int) -> Path:
        # Compatibility-only local path. Modal parts are written directly to
        # the Volume and are tracked in upload_parts.
        return self.upload_dir(upload_id) / f"part_{index:06d}"

    def upload_chunk_key(self, upload_id: str, index: int) -> str:
        return f"{upload_id.replace('-', '')}-{index:06d}"

    def offline_dir(self, task_id: str) -> Path:
        d = self.settings.offline_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def tmp_path(self, name: str) -> Path:
        self.settings.tmp_dir.mkdir(parents=True, exist_ok=True)
        return self.settings.tmp_dir / name

    def _put_local_file(self, local_path: Path, remote_path: str) -> None:
        # Ensure parent "directories" exist in listing by uploading under full path
        remote_path = remote_path.lstrip("/")
        with self._vol.batch_upload(force=True) as batch:
            batch.put_file(str(local_path), remote_path)
        # Fresh client view after write (avoids stale / missing block reads)
        self._refresh_volume()

    def _put_bytes(self, data: bytes, remote_path: str, *, refresh: bool = True) -> None:
        remote_path = remote_path.lstrip("/")
        with self._vol.batch_upload(force=True) as batch:
            batch.put_file(io.BytesIO(data), remote_path)
        if refresh:
            self._refresh_volume()

    def _refresh_volume(self) -> None:
        try:
            from backend.drive.modal_util import clear_volume_cache, get_volume

            clear_volume_cache()
            self._vol = get_volume(self.settings)
            try:
                self._vol.reload()
            except Exception:
                pass
        except Exception as e:
            logger.debug("volume refresh: %s", e)

    def write_file_atomic(self, storage_key: str, source: Path) -> Path:
        remote = self._remote(storage_key)
        self._put_local_file(source, remote)
        return Path(remote)

    def write_bytes_atomic(self, storage_key: str, data: bytes) -> Path:
        remote = self._remote(storage_key)
        self._put_bytes(data, remote)
        return Path(remote)

    def write_stream_atomic(
        self, storage_key: str, stream: BinaryIO, chunk_size: int = 1024 * 1024
    ) -> tuple[Path, int]:
        """Buffer to local temp (not permanent cache), then batch_upload to Volume."""
        tmp = self.tmp_path(f".upload-{storage_key}.tmp")
        size = 0
        try:
            with open(tmp, "wb") as f:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                f.flush()
                os.fsync(f.fileno())
            remote = self._remote(storage_key)
            self._put_local_file(tmp, remote)
            return Path(remote), size
        finally:
            tmp.unlink(missing_ok=True)

    def write_chunk(self, upload_id: str, index: int, data: bytes | BinaryIO) -> Path:
        # A browser part is at most the configured chunk size (5 MiB by
        # default), so upload it directly and never build a full local copy.
        raw = data if isinstance(data, bytes) else data.read()
        key = self.upload_chunk_key(upload_id, index)
        remote = self._remote(key)
        # Upload completion uses the SQLite manifest and does not immediately
        # read the part, so skip a Volume reload API call for every chunk.
        self._put_bytes(raw, remote, refresh=False)
        return Path(remote)

    def merge_chunks(
        self,
        upload_id: str,
        storage_key: str,
        total_chunks: int,
        expected_size: int | None = None,
    ) -> tuple[Path, int, str]:
        """Merge locally then upload final object to Volume; wipe local chunks."""
        from backend.drive.utils import sha256_file

        tmp = self.tmp_path(f".{storage_key}.merge.tmp")
        size = 0
        try:
            with open(tmp, "wb") as out:
                for i in range(total_chunks):
                    part = self.chunk_path(upload_id, i)
                    if not part.exists():
                        raise FileNotFoundError(f"Missing chunk {i}")
                    with open(part, "rb") as inp:
                        while True:
                            chunk = inp.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            if expected_size is not None and size != expected_size:
                raise ValueError(f"Size mismatch: expected {expected_size}, got {size}")
            digest = sha256_file(tmp)
            remote = self._remote(storage_key)
            self._put_local_file(tmp, remote)
            return Path(remote), size, digest
        finally:
            tmp.unlink(missing_ok=True)
            self.delete_upload(upload_id)

    def delete_file(self, storage_key: str) -> None:
        remote = self._remote(storage_key)
        try:
            self._vol.remove_file(remote)
        except FileNotFoundError:
            # Deletion is idempotent; the desired remote state already holds.
            return
        except Exception as e:
            logger.warning("remove_file %s: %s", remote, e)
            raise

    def delete_upload(self, upload_id: str) -> None:
        d = self.settings.uploads_dir / upload_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    def delete_offline(self, task_id: str) -> None:
        d = self.settings.offline_dir / task_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        # remote offline scratch if any
        try:
            self._vol.remove_file(f"offline/{task_id}", recursive=True)
        except Exception:
            pass

    def copy_storage_key(self, src_key: str, dest_key: str) -> Path:
        src = self._remote(src_key)
        dest = self._remote(dest_key)
        # Ensure we get exact dest name: download to temp and re-upload is reliable
        tmp = self.tmp_path(f".copy-{dest_key}.tmp")
        try:
            with open(tmp, "wb") as f:
                self._vol.read_file_into_fileobj(src, f)
            self._put_local_file(tmp, dest)
            return Path(dest)
        finally:
            tmp.unlink(missing_ok=True)

    def iter_file(
        self,
        storage_key: str,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        """Stream Volume blocks without a permanent or spooled local cache."""
        remote = self._remote(storage_key).lstrip("/")
        offset = 0
        wanted_end = end
        try:
            blocks = self._vol.read_file(remote)
            for block in blocks:
                block_end = offset + len(block) - 1
                if block_end < start:
                    offset += len(block)
                    continue
                left = max(0, start - offset)
                right = len(block)
                if wanted_end is not None:
                    right = min(right, wanted_end - offset + 1)
                if right > left:
                    view = memoryview(block)[left:right]
                    for pos in range(0, len(view), chunk_size):
                        yield bytes(view[pos : pos + chunk_size])
                offset += len(block)
                if wanted_end is not None and offset > wanted_end:
                    break
        except FileNotFoundError:
            raise
        except Exception:
            # One retry is handled by the SDK itself; refreshing here makes a
            # subsequent HTTP Range retry see newly committed Volume content.
            self._refresh_volume()
            raise

    def file_size(self, storage_key: str) -> int:
        remote = self._remote(storage_key).lstrip("/")
        parent = str(Path(remote).parent).replace("\\", "/")
        name = Path(remote).name
        try:
            entries = self._vol.listdir(parent, recursive=False)
            for e in entries:
                ep = e.path.rstrip("/").split("/")[-1]
                if ep == name or e.path.rstrip("/").endswith(remote):
                    return int(e.size)
        except Exception as e:
            logger.debug("listdir size %s: %s", remote, e)
        # fallback via full read into spooled (still no permanent local cache)
        spooled = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        try:
            self._vol.read_file_into_fileobj(remote, spooled)
            spooled.seek(0, os.SEEK_END)
            return spooled.tell()
        finally:
            spooled.close()

    def used_bytes(self) -> int:
        total = 0
        try:
            for entry in self._vol.listdir("files", recursive=True):
                # FileEntryType: FILE vs DIRECTORY
                if getattr(entry, "size", None) and not str(entry.path).endswith("/"):
                    total += int(entry.size)
        except Exception as e:
            logger.warning("used_bytes listing failed: %s", e)
        return total


# Back-compat alias
Storage = LocalStorage


def create_storage(
    settings: Settings | None = None,
    on_commit: CommitCallback | None = None,
    backend: str | None = None,
) -> Union[LocalStorage, ModalVolumeStorage]:
    settings = settings or get_settings()
    settings.ensure_dirs()
    name = backend or resolve_backend(settings)
    if name == "modal":
        return ModalVolumeStorage(settings=settings, on_commit=on_commit)
    return LocalStorage(settings=settings, on_commit=on_commit)
