"""Modal App — scale-to-zero download gateway and on-demand workers.

Cost model:
  - Upload: local API + Volume SDK (batch_upload).
  - Download: signed Web Function starts on demand and streams Volume chunks
    directly to the browser. No file bytes pass through the local API.
  - Offline download / heavy processing: spawn Function below → container
    starts only for that job, then exits.

Deploy once (registers functions; does not keep them running):
  uv run modal setup
  uv run modal deploy modal_app.py

Local API (always on your machine):
  uv run python run_local.py
"""

import os

import modal

APP_NAME = "modal-drive"
VOLUME_NAME = "modal-drive-storage"
STORAGE_MOUNT = "/storage"
TASK_DICT_NAME = "modal-drive-tasks"
DOWNLOAD_SECRET_NAME = os.getenv(
    "DRIVE_MODAL_DOWNLOAD_SECRET_NAME",
    "modal-drive-download",
)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("aria2", "ca-certificates")
    .pip_install(
        "httpx>=0.27.0",
    )
)

download_image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi[standard]",
    "httpx>=0.27.0",
)

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
task_dict = modal.Dict.from_name(TASK_DICT_NAME, create_if_missing=True)
download_secret = modal.Secret.from_name(
    DOWNLOAD_SECRET_NAME,
    required_keys=["DRIVE_DOWNLOAD_SIGNING_KEY", "Z_LAB_API_URL"],
)


def _set_progress(task_id: str, **fields) -> None:
    cur = {}
    try:
        cur = dict(task_dict[task_id])  # type: ignore[index]
    except Exception:
        cur = {}
    cur.update(fields)
    task_dict[task_id] = cur


def _cancelled(task_id: str) -> bool:
    try:
        cur = task_dict[task_id]
        return bool(cur.get("cancel"))
    except Exception:
        return False


@app.function(
    image=download_image,
    volumes={STORAGE_MOUNT: volume.with_mount_options(read_only=True)},
    secrets=[download_secret],
    timeout=60 * 60,
    startup_timeout=60,
    memory=512,
    cpu=0.25,
    min_containers=0,
    max_containers=10,
    scaledown_window=30,
)
@modal.asgi_app()
def download_gateway():
    """Scale-to-zero HTTP gateway: Volume -> browser, never through Z-Lab."""
    import asyncio
    import hashlib
    import hmac
    import re
    import time
    from pathlib import Path
    from urllib.parse import quote

    import httpx
    from fastapi import FastAPI, HTTPException, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse

    web = FastAPI(title="Modal Drive direct download", docs_url=None, redoc_url=None)
    web.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["Range", "If-Range"],
        expose_headers=[
            "Accept-Ranges",
            "Content-Disposition",
            "Content-Length",
            "Content-Range",
            "ETag",
            "Last-Modified",
            "X-Chunk-Count",
            "X-Download-Provider",
            "X-File-Size",
        ],
    )
    range_pattern = re.compile(r"bytes=(\d*)-(\d*)")
    storage_key_pattern = re.compile(r"[A-Za-z0-9._-]{1,160}")
    manifest_cache: dict[tuple[str, int, str], tuple[float, dict]] = {}

    async def fetch_manifest(node_id: str, expires: int, signature: str) -> dict:
        if expires < int(time.time()):
            raise HTTPException(410, "Download link has expired")
        signed_payload = f"v1\n{node_id}\n{expires}".encode()
        expected = hmac.new(
            os.environ["DRIVE_DOWNLOAD_SIGNING_KEY"].encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(401, "Invalid download signature")
        cache_key = (node_id, expires, signature)
        cached = manifest_cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return cached[1]

        api_url = os.environ["Z_LAB_API_URL"].rstrip("/")
        callback_url = f"{api_url}/internal/drive/download-manifests/{node_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    callback_url,
                    params={"expires": expires, "signature": signature},
                    headers={"User-Agent": "Z-Lab-Modal-Download/1.0"},
                )
        except httpx.HTTPError as error:
            raise HTTPException(502, f"Cannot query Z-Lab manifest: {error}") from error
        if response.status_code != 200:
            detail = response.text[:500] or "Manifest request rejected"
            raise HTTPException(response.status_code, detail)
        manifest = response.json()
        cache_seconds = min(30, max(1, expires - int(time.time())))
        manifest_cache[cache_key] = (time.monotonic() + cache_seconds, manifest)
        return manifest

    def chunk_path(storage_key: str) -> Path:
        if (
            not storage_key_pattern.fullmatch(storage_key)
            or storage_key in {".", ".."}
            or ".." in storage_key
        ):
            raise HTTPException(502, "Manifest contains an invalid storage key")
        return Path(STORAGE_MOUNT) / "files" / storage_key[:2] / storage_key

    @web.get("/health")
    async def health():
        return {"status": "ok", "service": "modal-drive-download"}

    @web.api_route("/download/{node_id}", methods=["GET", "HEAD"])
    async def download(
        node_id: str,
        request: Request,
        expires: int,
        signature: str,
    ):
        manifest = await fetch_manifest(node_id, expires, signature)
        chunks = sorted(manifest["chunks"], key=lambda item: int(item["index"]))
        file_size = int(manifest["size"])
        mime_type = manifest.get("mime_type") or "application/octet-stream"
        disposition = f"attachment; filename*=UTF-8''{quote(manifest['filename'])}"
        paths = [(chunk_path(str(chunk["storage_key"])), int(chunk["size"])) for chunk in chunks]

        try:
            await asyncio.to_thread(volume.reload)
        except Exception:
            # A fresh container already has the latest committed snapshot. A
            # concurrent open file can make reload fail, so let reads proceed.
            pass
        if any(not path.is_file() for path, _size in paths):
            raise HTTPException(404, "One or more Volume chunks are missing")

        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "Content-Disposition": disposition,
            "Content-Type": mime_type,
            "ETag": str(manifest["etag"]),
            "Last-Modified": str(manifest["last_modified"]),
            "X-Chunk-Count": str(len(paths)),
            "X-Download-Provider": "modal",
            "X-File-Size": str(file_size),
        }

        start = 0
        end = file_size - 1
        status_code = 200
        range_header = request.headers.get("range")
        if range_header:
            matched = range_pattern.fullmatch(range_header.strip())
            if not matched:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}", **headers},
                )
            start_text, end_text = matched.groups()
            if not start_text and not end_text:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}", **headers},
                )
            if not start_text:
                suffix = int(end_text)
                if suffix <= 0:
                    return Response(
                        status_code=416,
                        headers={"Content-Range": f"bytes */{file_size}", **headers},
                    )
                start = max(file_size - suffix, 0)
            else:
                start = int(start_text)
                end = int(end_text) if end_text else file_size - 1
            if start >= file_size or end >= file_size or start > end:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}", **headers},
                )
            status_code = 206
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

        length = max(0, end - start + 1)
        headers["Content-Length"] = str(length)
        if request.method == "HEAD":
            return Response(status_code=status_code, headers=headers)

        def iter_content():
            global_offset = 0
            bytes_left = length
            for path, chunk_size in paths:
                chunk_end = global_offset + chunk_size - 1
                if chunk_end < start:
                    global_offset += chunk_size
                    continue
                if global_offset > end or bytes_left <= 0:
                    break
                local_start = max(0, start - global_offset)
                local_end = min(chunk_size - 1, end - global_offset)
                wanted = local_end - local_start + 1
                with path.open("rb") as stream:
                    stream.seek(local_start)
                    while wanted > 0:
                        block = stream.read(min(1024 * 1024, wanted))
                        if not block:
                            raise IOError(f"Unexpected end of Volume chunk: {path.name}")
                        wanted -= len(block)
                        bytes_left -= len(block)
                        yield block
                global_offset += chunk_size

        return StreamingResponse(
            iter_content(),
            status_code=status_code,
            headers=headers,
            media_type=mime_type,
        )

    return web


@app.function(
    image=image,
    volumes={STORAGE_MOUNT: volume},
    timeout=60 * 60 * 12,
    memory=4096,
    cpu=2.0,
)
def offline_worker(job: dict) -> dict:
    """Download URL/magnet into Volume. Invoked only when user starts offline task.

    job keys:
      task_id, url, filename?, storage_key, is_magnet
    returns:
      ok, storage_key, size, sha256, filename, error?
    """
    import hashlib
    import os
    import re
    import shutil
    import subprocess
    import time
    from pathlib import Path
    from urllib.parse import unquote, urlparse
    from urllib.request import urlopen

    task_id = job["task_id"]
    url = job["url"]
    storage_key = job["storage_key"]
    is_magnet = bool(job.get("is_magnet"))
    filename = job.get("filename")

    work = Path(STORAGE_MOUNT) / "offline" / task_id
    work.mkdir(parents=True, exist_ok=True)
    files_dir = Path(STORAGE_MOUNT) / "files" / storage_key[:2]
    files_dir.mkdir(parents=True, exist_ok=True)

    _set_progress(task_id, status="downloading", progress=0.0, error=None)

    def guess_name(u: str) -> str:
        name = Path(unquote(urlparse(u).path)).name
        return name or f"download-{int(time.time())}"

    def parse_size(s: str) -> int:
        m = re.match(r"([\d.]+)([A-Za-z]*)", s.strip())
        if not m:
            return 0
        val = float(m.group(1))
        unit = (m.group(2) or "B").upper()
        mult = {
            "B": 1,
            "KB": 1000,
            "MB": 1000**2,
            "GB": 1000**3,
            "KIB": 1024,
            "MIB": 1024**2,
            "GIB": 1024**3,
        }.get(unit, 1)
        return int(val * mult)

    def sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                b = f.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    try:
        if _cancelled(task_id):
            _set_progress(task_id, status="cancelled")
            return {"ok": False, "error": "cancelled", "task_id": task_id}

        aria2 = shutil.which("aria2c")
        out_path: Path

        if is_magnet:
            if not aria2:
                raise RuntimeError("aria2c required for magnet links")
            cmd = [
                aria2,
                "--console-log-level=warn",
                "--seed-time=0",
                "--allow-overwrite=true",
                "--enable-dht=true",
                "--summary-interval=1",
                f"--dir={work}",
                "--continue=true",
                url,
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            assert proc.stdout is not None
            for line in proc.stdout:
                if _cancelled(task_id):
                    proc.terminate()
                    _set_progress(task_id, status="cancelled")
                    return {"ok": False, "error": "cancelled", "task_id": task_id}
                m = re.search(r"\((\d+(?:\.\d+)?)%\)", line)
                if m:
                    _set_progress(task_id, status="downloading", progress=float(m.group(1)))
            if proc.wait() != 0:
                raise RuntimeError(f"aria2c exited {proc.returncode}")
            files = [
                p
                for p in work.rglob("*")
                if p.is_file() and not p.name.endswith(".aria2") and p.suffix != ".torrent"
            ]
            if not files:
                raise RuntimeError("No file after magnet download")
            out_path = max(files, key=lambda p: p.stat().st_size)
            filename = filename or out_path.name
        else:
            filename = filename or guess_name(url)
            out_path = work / filename
            if aria2:
                cmd = [
                    aria2,
                    "--console-log-level=warn",
                    "--allow-overwrite=true",
                    "--auto-file-renaming=false",
                    "--summary-interval=1",
                    f"--dir={work}",
                    f"--out={filename}",
                    "--max-connection-per-server=8",
                    "--split=8",
                    "--continue=true",
                    url,
                ]
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    if _cancelled(task_id):
                        proc.terminate()
                        _set_progress(task_id, status="cancelled")
                        return {"ok": False, "error": "cancelled", "task_id": task_id}
                    m = re.search(r"\((\d+(?:\.\d+)?)%\)", line)
                    if m:
                        _set_progress(task_id, status="downloading", progress=float(m.group(1)))
                    m2 = re.search(r"([\d.]+[KkMmGg]?i?B)/([\d.]+[KkMmGg]?i?B)", line)
                    if m2:
                        _set_progress(
                            task_id,
                            downloaded_size=parse_size(m2.group(1)),
                            total_size=parse_size(m2.group(2)),
                        )
                if proc.wait() != 0:
                    raise RuntimeError(f"aria2c exited {proc.returncode}")
                if not out_path.exists():
                    cands = [p for p in work.iterdir() if p.is_file() and not p.name.endswith(".aria2")]
                    if not cands:
                        raise RuntimeError("Download finished but file missing")
                    out_path = max(cands, key=lambda p: p.stat().st_size)
            else:
                # fallback urllib
                tmp = out_path.with_suffix(out_path.suffix + ".tmp")
                with urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
                    total = int(resp.headers.get("Content-Length") or 0)
                    got = 0
                    while True:
                        if _cancelled(task_id):
                            _set_progress(task_id, status="cancelled")
                            return {"ok": False, "error": "cancelled", "task_id": task_id}
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        pct = (got / total * 100) if total else 0
                        _set_progress(
                            task_id,
                            status="downloading",
                            progress=pct,
                            downloaded_size=got,
                            total_size=total or got,
                        )
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, out_path)

        size = out_path.stat().st_size
        digest = sha256_file(out_path)
        # Files above 8 MiB stay physically chunked on the Volume. The local
        # API stores this ordered manifest in SQLite and streams it on demand.
        chunk_limit = 8 * 1024 * 1024
        chunks = []
        with out_path.open("rb") as source:
            index = 0
            while True:
                data = source.read(chunk_limit)
                if not data:
                    break
                key = storage_key if size <= chunk_limit else f"{storage_key}-{index:06d}"
                chunk_dir = Path(STORAGE_MOUNT) / "files" / key[:2]
                chunk_dir.mkdir(parents=True, exist_ok=True)
                chunk_dest = chunk_dir / key
                tmp_dest = chunk_dest.with_suffix(".tmp")
                tmp_dest.write_bytes(data)
                os.replace(tmp_dest, chunk_dest)
                chunks.append(
                    {
                        "index": index,
                        "storage_key": key,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
                index += 1
        volume.commit()

        # cleanup work dir
        shutil.rmtree(work, ignore_errors=True)
        volume.commit()

        result = {
            "ok": True,
            "task_id": task_id,
            "storage_key": storage_key,
            "size": size,
            "sha256": digest,
            "filename": filename or out_path.name,
            "chunks": chunks,
        }
        _set_progress(
            task_id,
            status="completed",
            progress=100.0,
            downloaded_size=size,
            total_size=size,
            result=result,
        )
        return result
    except Exception as e:
        _set_progress(task_id, status="failed", error=str(e)[:2000])
        try:
            volume.commit()
        except Exception:
            pass
        return {"ok": False, "task_id": task_id, "error": str(e)[:2000]}


@app.function(
    image=image,
    volumes={STORAGE_MOUNT: volume},
    timeout=60 * 30,
    memory=2048,
)
def process_job(job: dict) -> dict:
    """Generic heavy-processing hook (hash large tree, etc.). On-demand only."""
    kind = job.get("kind", "")
    if kind == "ping":
        return {"ok": True, "kind": "ping"}
    if kind == "rechunk":
        import hashlib
        import os
        from pathlib import Path

        storage_key = str(job["storage_key"])
        chunk_limit = min(
            max(int(job.get("chunk_size") or 8 * 1024 * 1024), 256 * 1024),
            8 * 1024 * 1024,
        )
        source = Path(STORAGE_MOUNT) / "files" / storage_key[:2] / storage_key
        if not source.is_file():
            return {"ok": False, "error": f"source not found: {storage_key}"}
        size = source.stat().st_size
        if size <= chunk_limit:
            return {
                "ok": True,
                "storage_key": storage_key,
                "size": size,
                "chunks": [
                    {
                        "index": 0,
                        "storage_key": storage_key,
                        "size": size,
                        "sha256": None,
                    }
                ],
            }

        chunks = []
        created: list[Path] = []
        try:
            with source.open("rb") as inp:
                index = 0
                while True:
                    data = inp.read(chunk_limit)
                    if not data:
                        break
                    key = f"{storage_key}-{index:06d}"
                    dest_dir = Path(STORAGE_MOUNT) / "files" / key[:2]
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / key
                    tmp = dest.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    os.replace(tmp, dest)
                    created.append(dest)
                    chunks.append(
                        {
                            "index": index,
                            "storage_key": key,
                            "size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        }
                    )
                    index += 1
            volume.commit()
            return {
                "ok": True,
                "storage_key": storage_key,
                "size": size,
                "chunks": chunks,
            }
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            volume.commit()
            raise
    return {"ok": False, "error": f"unknown kind: {kind}"}


@app.local_entrypoint()
def main():
    print("Modal Drive workers")
    print(f"  app:    {APP_NAME}")
    print(f"  volume: {VOLUME_NAME}")
    print("  deploy: uv run modal deploy modal_app.py")
    print("  download_gateway: scale-to-zero Volume -> browser streaming")
    print("  offline_worker: starts only for an offline download job")
