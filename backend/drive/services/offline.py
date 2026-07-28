from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from sqlalchemy.orm import Session

from backend.drive.config import Settings, get_settings
from backend.drive.models import OfflineStatus, OfflineTask, utcnow
from backend.drive.schemas import ConflictPolicy, CreateOfflineRequest
from backend.drive.services.fs import FSError, FileService
from backend.drive.utils import is_magnet, new_id, sanitize_filename, sha256_file

logger = logging.getLogger(__name__)


class OfflineService:
    def __init__(self, db: Session, storage, settings: Settings | None = None):
        self.db = db
        self.storage = storage
        self.settings = settings or get_settings()
        self.fs = FileService(db, storage)

    def create(self, req: CreateOfflineRequest) -> OfflineTask:
        url = req.url.strip()
        if not url:
            raise FSError("URL required", "bad_request", 400)
        parent_id = self.fs.resolve_parent(req.parent_id, req.path)
        magnet = is_magnet(url)
        filename = sanitize_filename(req.filename) if req.filename else None
        if not filename and not magnet:
            filename = self._guess_filename(url)

        task = OfflineTask(
            id=new_id(),
            url=url,
            filename=filename,
            parent_id=parent_id,
            status=OfflineStatus.pending,
            is_magnet=magnet,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def get(self, task_id: str) -> OfflineTask:
        task = self.db.get(OfflineTask, task_id)
        if not task:
            raise FSError("Task not found", "not_found", 404)
        # Merge live progress from Modal Dict when available
        if task.status in (OfflineStatus.pending, OfflineStatus.downloading):
            self._sync_progress_from_modal(task)
        return task

    def list_tasks(self, limit: int = 50) -> list[OfflineTask]:
        from sqlalchemy import select

        q = select(OfflineTask).order_by(OfflineTask.created_at.desc()).limit(limit)
        tasks = list(self.db.execute(q).scalars().all())
        for t in tasks:
            if t.status in (OfflineStatus.pending, OfflineStatus.downloading):
                self._sync_progress_from_modal(t)
        return tasks

    def _sync_progress_from_modal(self, task: OfflineTask) -> None:
        if getattr(self.storage, "backend_name", lambda: "local")() != "modal":
            return
        try:
            from backend.drive.modal_util import get_task_dict

            d = get_task_dict(self.settings)
            info = d[task.id]
            if not isinstance(info, dict):
                return
            if "progress" in info:
                task.progress = float(info["progress"] or 0)
            if "downloaded_size" in info:
                task.downloaded_size = int(info["downloaded_size"] or 0)
            if "total_size" in info:
                task.total_size = int(info["total_size"] or 0)
            st = info.get("status")
            if st == "failed" and task.status != OfflineStatus.failed:
                task.status = OfflineStatus.failed
                task.error_message = info.get("error")
                task.updated_at = utcnow()
            elif st == "cancelled":
                task.status = OfflineStatus.cancelled
                task.updated_at = utcnow()
            elif st == "downloading":
                task.status = OfflineStatus.downloading
                task.updated_at = utcnow()
            self.db.flush()
        except KeyError:
            pass
        except Exception as e:
            logger.debug("progress sync: %s", e)

    def cancel(self, task_id: str) -> OfflineTask:
        task = self.get(task_id)
        if task.status in (OfflineStatus.completed,):
            raise FSError("Cannot cancel completed task", "completed", 400)
        task.status = OfflineStatus.cancelled
        task.updated_at = utcnow()
        self.db.flush()
        if getattr(self.storage, "backend_name", lambda: "local")() == "modal":
            try:
                from backend.drive.modal_util import get_task_dict

                d = get_task_dict(self.settings)
                cur = {}
                try:
                    cur = dict(d[task_id])
                except Exception:
                    cur = {}
                cur["cancel"] = True
                cur["status"] = "cancelled"
                d[task_id] = cur
            except Exception as e:
                logger.warning("cancel flag: %s", e)
        self.storage.delete_offline(task_id)
        return task

    def delete(self, task_id: str) -> None:
        task = self.get(task_id)
        if task.status == OfflineStatus.downloading:
            raise FSError("Stop the task before deleting", "busy", 400)
        self.db.delete(task)
        self.db.flush()
        self.storage.delete_offline(task_id)

    @staticmethod
    def _guess_filename(url: str) -> str:
        path = unquote(urlparse(url).path)
        name = Path(path).name
        if name:
            return sanitize_filename(name)
        return f"download-{int(time.time())}"

    def start_async(self, task_id: str) -> None:
        """Kick off download: Modal Function on demand, or local thread."""
        backend = getattr(self.storage, "backend_name", lambda: "local")()
        if backend == "modal":
            t = threading.Thread(target=self._run_modal_job, args=(task_id,), daemon=True)
            t.start()
        else:
            t = threading.Thread(target=self._run_local_job, args=(task_id,), daemon=True)
            t.start()

    def _run_modal_job(self, task_id: str) -> None:
        """Spawn Modal offline_worker — container starts only for this job."""
        from backend.drive.database import session_scope
        from backend.drive.storage import create_storage

        with session_scope() as db:
            task = db.get(OfflineTask, task_id)
            if not task or task.status == OfflineStatus.cancelled:
                return
            storage_key = new_id().replace("-", "")
            task.status = OfflineStatus.downloading
            task.updated_at = utcnow()
            db.commit()

            job = {
                "task_id": task_id,
                "url": task.url,
                "filename": task.filename,
                "storage_key": storage_key,
                "is_magnet": task.is_magnet,
            }
            try:
                from backend.drive.modal_util import get_offline_function, get_task_dict

                get_task_dict(self.settings)[task_id] = {
                    "status": "pending",
                    "progress": 0,
                    "cancel": False,
                }
                fn = get_offline_function(self.settings)
                # spawn starts container; .get waits without holding a local web service
                call = fn.spawn(job)
                result = call.get()
            except Exception as e:
                logger.exception("Modal offline failed")
                task = db.get(OfflineTask, task_id)
                if task:
                    task.status = OfflineStatus.failed
                    task.error_message = str(e)[:2000]
                    task.updated_at = utcnow()
                    db.commit()
                return

            task = db.get(OfflineTask, task_id)
            if not task:
                return
            if task.status == OfflineStatus.cancelled:
                return

            if not result or not result.get("ok"):
                task.status = OfflineStatus.failed
                task.error_message = (result or {}).get("error", "unknown error")
                task.updated_at = utcnow()
                db.commit()
                return

            storage = create_storage(settings=self.settings, backend="modal")
            fs = FileService(db, storage)
            filename = sanitize_filename(result.get("filename") or task.filename or "download")
            chunks = result.get("chunks") or [
                {
                    "index": 0,
                    "storage_key": result["storage_key"],
                    "size": int(result["size"]),
                    "sha256": result.get("sha256"),
                }
            ]
            content = fs.create_content_manifest(
                chunks=chunks,
                total_size=int(result["size"]),
                sha256=result.get("sha256"),
                chunk_size=max(int(part["size"]) for part in chunks),
                backend="modal",
            )
            node = fs.register_file(
                name=filename,
                storage_key=result["storage_key"],
                size=int(result["size"]),
                sha256=result.get("sha256"),
                content_id=content.id,
                parent_id=task.parent_id,
                conflict=ConflictPolicy.rename,
            )
            task.status = OfflineStatus.completed
            task.progress = 100.0
            task.downloaded_size = int(result["size"])
            task.total_size = int(result["size"])
            task.result_node_id = node.id
            task.filename = filename
            task.completed_at = utcnow()
            task.updated_at = utcnow()
            db.commit()

    def _run_local_job(self, task_id: str) -> None:
        from backend.drive.database import session_scope
        from backend.drive.storage import create_storage

        with session_scope() as db:
            storage = create_storage(settings=self.settings, backend="local")
            OfflineService(db, storage, self.settings).run_download(task_id)

    def run_download(self, task_id: str) -> OfflineTask:
        """Synchronous local download (no Modal)."""
        task = self.get(task_id)
        if task.status in (OfflineStatus.cancelled, OfflineStatus.completed):
            return task

        task.status = OfflineStatus.downloading
        task.updated_at = utcnow()
        self.db.commit()

        work = self.storage.offline_dir(task_id)
        try:
            if task.is_magnet:
                out_file = self._download_magnet(task, work)
            else:
                out_file = self._download_http(task, work)

            if task.status == OfflineStatus.cancelled:
                return task

            filename = sanitize_filename(task.filename or out_file.name)
            storage_key = new_id().replace("-", "")
            size = out_file.stat().st_size
            digest = sha256_file(out_file)
            content_id = None
            if size > self.settings.large_file_threshold:
                chunks = []
                with out_file.open("rb") as source:
                    index = 0
                    while data := source.read(self.settings.large_file_threshold):
                        key = f"{storage_key}-{index:06d}"
                        self.storage.write_bytes_atomic(key, data)
                        chunks.append(
                            {
                                "index": index,
                                "storage_key": key,
                                "size": len(data),
                                "sha256": hashlib.sha256(data).hexdigest(),
                            }
                        )
                        index += 1
                content = self.fs.create_content_manifest(
                    chunks=chunks,
                    total_size=size,
                    sha256=digest,
                    chunk_size=self.settings.large_file_threshold,
                    backend=self.storage.backend_name(),
                )
                content_id = content.id
            else:
                self.storage.write_file_atomic(storage_key, out_file)
            node = self.fs.register_file(
                name=filename,
                storage_key=storage_key,
                size=size,
                sha256=digest,
                content_id=content_id,
                parent_id=task.parent_id,
                conflict=ConflictPolicy.rename,
            )
            task.status = OfflineStatus.completed
            task.progress = 100.0
            task.downloaded_size = size
            task.total_size = size
            task.result_node_id = node.id
            task.filename = filename
            task.completed_at = utcnow()
            task.updated_at = utcnow()
            self.db.commit()
            self.storage.delete_offline(task_id)
            return task
        except Exception as e:
            task.status = OfflineStatus.failed
            task.error_message = str(e)[:2000]
            task.updated_at = utcnow()
            self.db.commit()
            raise

    def _download_http(self, task: OfflineTask, work: Path) -> Path:
        out_name = task.filename or self._guess_filename(task.url)
        out_path = work / out_name
        aria2 = shutil.which("aria2c")
        if aria2:
            cmd = [
                aria2,
                "--console-log-level=warn",
                "--allow-overwrite=true",
                "--auto-file-renaming=false",
                "--summary-interval=1",
                f"--dir={work}",
                f"--out={out_name}",
                "--max-connection-per-server=8",
                "--split=8",
                "--continue=true",
                task.url,
            ]
            self._run_aria2(task, cmd, work)
        else:
            self._download_http_urllib(task, out_path)
        if not out_path.exists():
            files = [p for p in work.iterdir() if p.is_file() and not p.name.endswith(".aria2")]
            if not files:
                raise RuntimeError("Download finished but no file found")
            out_path = max(files, key=lambda p: p.stat().st_size)
        return out_path

    def _download_magnet(self, task: OfflineTask, work: Path) -> Path:
        aria2 = shutil.which("aria2c")
        if not aria2:
            raise RuntimeError("Magnet downloads require aria2c, or use Modal backend")
        cmd = [
            aria2,
            "--console-log-level=warn",
            "--seed-time=0",
            "--allow-overwrite=true",
            "--enable-dht=true",
            "--summary-interval=1",
            f"--dir={work}",
            "--continue=true",
            task.url,
        ]
        self._run_aria2(task, cmd, work)
        files = [
            p
            for p in work.rglob("*")
            if p.is_file() and not p.name.endswith(".aria2") and p.suffix != ".torrent"
        ]
        if not files:
            raise RuntimeError("Magnet download finished but no file found")
        out = max(files, key=lambda p: p.stat().st_size)
        if not task.filename:
            task.filename = out.name
        return out

    def _run_aria2(self, task: OfflineTask, cmd: list[str], work: Path) -> None:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(work)
        )
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self.db.refresh(task)
                if task.status == OfflineStatus.cancelled:
                    proc.terminate()
                    raise RuntimeError("Cancelled")
                m = re.search(r"\((\d+(?:\.\d+)?)%\)", line)
                if m:
                    task.progress = float(m.group(1))
                    task.updated_at = utcnow()
                    try:
                        self.db.commit()
                    except Exception:
                        self.db.rollback()
            code = proc.wait()
            if code != 0 and task.status != OfflineStatus.cancelled:
                raise RuntimeError(f"aria2c exited with code {code}")
        finally:
            if proc.poll() is None:
                proc.kill()

    def _download_http_urllib(self, task: OfflineTask, out_path: Path) -> None:
        import urllib.request

        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        try:
            with urllib.request.urlopen(task.url, timeout=60) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                task.total_size = total
                downloaded = 0
                last = time.time()
                while True:
                    self.db.refresh(task)
                    if task.status == OfflineStatus.cancelled:
                        raise RuntimeError("Cancelled")
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last >= 0.5:
                        task.downloaded_size = downloaded
                        task.progress = (downloaded / total * 100) if total else 0
                        task.updated_at = utcnow()
                        self.db.commit()
                        last = now
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, out_path)
            task.downloaded_size = downloaded
            task.total_size = downloaded if not total else total
            task.progress = 100.0
            self.db.commit()
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
