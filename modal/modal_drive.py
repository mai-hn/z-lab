"""Modal Volume and rclone-backed file API for TOOLBOX.

Deploy with:
    MODAL_DRIVE_VOLUME_NAME=toolbox-drive modal deploy modal/modal_drive.py
    MODAL_RCLONE_CONFIG_PATH=~/.config/rclone/rclone.conf \
      modal deploy modal/modal_drive.py

Each remote from the rclone config appears at /Cloud/<remote-name>. Modal
Volume stores the other root entries. TOOLBOX databases stay on the local
Next.js host.
"""

import base64
import json
import mimetypes
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

import modal

APP_NAME = "toolbox-modal-drive"
MOUNT_PATH = Path("/drive")
CLOUD_ROOT = "/Cloud"
RCLONE_CONFIG_PATH = Path("/tmp/toolbox-rclone.conf")
RCLONE_SECRET_NAME = os.environ.get(
    "MODAL_RCLONE_SECRET_NAME",
    "toolbox-rclone-config",
)
VOLUME_NAME = os.environ.get("MODAL_DRIVE_VOLUME_NAME", "toolbox-drive")


def deployment_rclone_secret() -> modal.Secret:
    """Synchronize a local rclone config into a named Modal secret."""
    if not modal.is_local():
        return modal.Secret.from_name(RCLONE_SECRET_NAME)

    config_path_value = os.environ.get("MODAL_RCLONE_CONFIG_PATH", "").strip()
    secret_values: dict[str, str] = {}
    if config_path_value:
        config_path = Path(config_path_value).expanduser().resolve()
        if not config_path.is_file():
            raise RuntimeError(f"rclone config file not found: {config_path}")
        config_bytes = config_path.read_bytes()

        encoded_config = base64.b64encode(config_bytes).decode("ascii")
        if len(encoded_config) > 32_768:
            raise RuntimeError(
                "The base64-encoded rclone config exceeds Modal's 32 KiB "
                "per-secret-value limit"
            )
        secret_values["TOOLBOX_RCLONE_CONFIG_B64"] = encoded_config
        config_password = os.environ.get(
            "MODAL_RCLONE_CONFIG_PASSWORD",
            "",
        ).strip()
        if config_password:
            secret_values["RCLONE_CONFIG_PASS"] = config_password

    named_secret = modal.Secret.from_name(RCLONE_SECRET_NAME)
    try:
        named_secret.hydrate()
    except modal.exception.NotFoundError:
        modal.Secret.objects.create(RCLONE_SECRET_NAME, secret_values)
    else:
        if secret_values:
            named_secret.update(secret_values)
    return modal.Secret.from_name(RCLONE_SECRET_NAME)


app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "rclone")
    .uv_pip_install("fastapi[standard]", "httpx")
)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
rclone_secret = deployment_rclone_secret()
download_jobs = modal.Dict.from_name(
    f"{APP_NAME}-download-jobs",
    create_if_missing=True,
)
transfer_jobs = modal.Dict.from_name(
    f"{APP_NAME}-transfer-jobs",
    create_if_missing=True,
)
TERMINAL_DOWNLOAD_STATUSES = {"completed", "canceled", "failed"}


class DownloadCanceled(Exception):
    pass


class RcloneNotConfigured(Exception):
    pass


class RcloneCommandError(Exception):
    def __init__(self, message: str, return_code: int):
        super().__init__(message)
        self.return_code = return_code


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def update_download_job(job_id: str, **updates) -> dict:
    record = download_jobs.get(job_id, {})
    record.update(updates)
    record["updatedAt"] = utc_now()
    download_jobs.put(job_id, record)
    return record


def public_download_job(job_id: str, record: dict) -> dict:
    return {
        "ok": True,
        "jobId": job_id,
        **{
            key: value
            for key, value in record.items()
            if not key.startswith("_") and key != "cancelRequested"
        },
    }


def update_transfer_job(job_id: str, **updates) -> dict:
    record = transfer_jobs.get(job_id, {})
    record.update(updates)
    record["updatedAt"] = utc_now()
    transfer_jobs.put(job_id, record)
    return record


def public_transfer_job(job_id: str, record: dict) -> dict:
    return {
        "ok": True,
        "jobId": job_id,
        **{
            key: value
            for key, value in record.items()
            if not key.startswith("_") and key != "cancelRequested"
        },
    }


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


def is_cloud_path(value: str) -> bool:
    return value == CLOUD_ROOT or value.startswith(f"{CLOUD_ROOT}/")


def cloud_relative_path(value: str) -> str:
    if not is_cloud_path(value):
        raise ValueError("Path is outside the Cloud directory")
    return value[len(CLOUD_ROOT) :].lstrip("/")


def ensure_rclone_config() -> Path:
    encoded = os.environ.get("TOOLBOX_RCLONE_CONFIG_B64", "").strip()
    if not encoded:
        raise RcloneNotConfigured(
            "Cloud is not configured. Deploy with MODAL_RCLONE_CONFIG_PATH."
        )
    try:
        config_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise RcloneNotConfigured("The injected rclone config is invalid") from error
    if not RCLONE_CONFIG_PATH.exists() or RCLONE_CONFIG_PATH.read_bytes() != config_bytes:
        RCLONE_CONFIG_PATH.write_bytes(config_bytes)
        RCLONE_CONFIG_PATH.chmod(0o600)
    return RCLONE_CONFIG_PATH


def rclone_command(
    arguments: list[str],
    *,
    log_level: str = "ERROR",
) -> list[str]:
    config_path = ensure_rclone_config()
    return [
        "rclone",
        "--config",
        str(config_path),
        "--log-level",
        log_level,
        *arguments,
    ]


@lru_cache(maxsize=1)
def rclone_remotes() -> tuple[str, ...]:
    result = run_rclone(["listremotes"])
    remotes = []
    for line in result.stdout.splitlines():
        name = line.strip().rstrip(":")
        if not name:
            continue
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise RcloneCommandError(
                f"rclone remote name cannot be mapped into Cloud: {name}",
                1,
            )
        remotes.append(name)
    return tuple(sorted(set(remotes), key=str.casefold))


def split_cloud_path(remote_path: str) -> tuple[str | None, str]:
    relative = cloud_relative_path(remote_path)
    if not relative:
        return None, ""
    remote, separator, path = relative.partition("/")
    return remote, path if separator else ""


def is_cloud_remote_root(remote_path: str) -> bool:
    remote, relative = split_cloud_path(remote_path)
    return remote is not None and not relative


def rclone_target(remote_path: str) -> str:
    remote, relative = split_cloud_path(remote_path)
    if remote is None:
        raise RcloneCommandError("Cloud root is not an rclone remote", 3)
    if remote not in rclone_remotes():
        raise RcloneCommandError(f"rclone remote not found: {remote}", 3)
    return f"{remote}:{relative}" if relative else f"{remote}:"


def run_rclone(
    arguments: list[str],
    *,
    timeout: int = 60 * 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        rclone_command(arguments),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "rclone command failed"
        raise RcloneCommandError(message[:1000], result.returncode)
    return result


def cloud_entry(remote_path: str, item: dict | None = None) -> dict:
    normalized = normalize_remote_path(remote_path)
    if normalized == CLOUD_ROOT:
        return {
            "name": "Cloud",
            "path": CLOUD_ROOT,
            "type": "directory",
            "size": 0,
            "mimeType": None,
            "modifiedAt": utc_now(),
            "storage": "rclone",
        }

    if item is None and is_cloud_remote_root(normalized):
        remote, _ = split_cloud_path(normalized)
        if remote not in rclone_remotes():
            raise FileNotFoundError(normalized)
        return {
            "name": remote,
            "path": normalized,
            "type": "directory",
            "size": 0,
            "mimeType": None,
            "modifiedAt": utc_now(),
            "storage": "rclone",
            "remote": remote,
        }

    payload = item if item is not None else rclone_stat(normalized)
    if payload is None:
        raise FileNotFoundError(normalized)
    is_directory = bool(payload.get("IsDir"))
    name = str(payload.get("Name") or normalized.rsplit("/", 1)[-1])
    modified_at = str(payload.get("ModTime") or "")
    if not modified_at or modified_at.startswith("0001-"):
        modified_at = utc_now()
    return {
        "name": name,
        "path": normalized,
        "type": "directory" if is_directory else "file",
        "size": 0 if is_directory else max(0, int(payload.get("Size") or 0)),
        "mimeType": (
            None
            if is_directory
            else payload.get("MimeType") or mimetypes.guess_type(name)[0]
        ),
        "modifiedAt": modified_at,
        "storage": "rclone",
    }


def rclone_stat(remote_path: str) -> dict | None:
    if remote_path == CLOUD_ROOT:
        rclone_remotes()
        return {"Name": "Cloud", "IsDir": True, "Size": 0, "ModTime": utc_now()}
    if is_cloud_remote_root(remote_path):
        remote, _ = split_cloud_path(remote_path)
        if remote not in rclone_remotes():
            return None
        return {
            "Name": remote,
            "IsDir": True,
            "Size": 0,
            "ModTime": utc_now(),
        }
    result = run_rclone(["lsjson", rclone_target(remote_path), "--stat"], check=False)
    if result.returncode == 3:
        return None
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "rclone stat failed"
        raise RcloneCommandError(message[:1000], result.returncode)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RcloneCommandError("rclone returned invalid JSON", result.returncode) from error
    return payload if isinstance(payload, dict) else None


def list_cloud_directory(remote_path: str) -> list[dict]:
    if remote_path == CLOUD_ROOT:
        return [
            cloud_entry(f"{CLOUD_ROOT}/{remote}")
            for remote in rclone_remotes()
        ]
    result = run_rclone(["lsjson", rclone_target(remote_path)])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RcloneCommandError("rclone returned invalid JSON", result.returncode) from error
    if not isinstance(payload, list):
        raise RcloneCommandError("rclone returned an invalid directory listing", 1)
    entries = [
        cloud_entry(
            f"{remote_path.rstrip('/')}/{str(item.get('Name') or '').lstrip('/')}",
            item,
        )
        for item in payload
        if isinstance(item, dict) and item.get("Name")
    ]
    return sorted(
        entries,
        key=lambda item: (item["type"] != "directory", item["name"].lower()),
    )


def path_entry(remote_path: str) -> dict:
    if is_cloud_path(remote_path):
        return cloud_entry(remote_path)
    _, local_path = resolve_remote_path(remote_path)
    if not local_path.exists():
        raise FileNotFoundError(remote_path)
    return file_entry(local_path)


def path_exists(remote_path: str) -> bool:
    if is_cloud_path(remote_path):
        return rclone_stat(remote_path) is not None
    _, local_path = resolve_remote_path(remote_path)
    return local_path.exists()


def rclone_storage_path(remote_path: str) -> str:
    if is_cloud_path(remote_path):
        return rclone_target(remote_path)
    _, local_path = resolve_remote_path(remote_path)
    return str(local_path)


def safe_file_name(value: str | None) -> str:
    name = (value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."} or "\x00" in name or len(name) > 255:
        raise ValueError("Invalid file name")
    return name


def checked_download_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    if (
        not url
        or len(url) > 8192
        or parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only HTTP(S) download URLs without credentials are allowed")
    return url


def response_file_name(content_disposition: str | None, url: str, index: int) -> str:
    parameters: dict[str, str] = {}
    for part in (content_disposition or "").split(";")[1:]:
        key, separator, value = part.strip().partition("=")
        if separator:
            parameters[key.lower()] = value.strip().strip("\"'")

    encoded_name = parameters.get("filename*")
    if encoded_name:
        if "''" in encoded_name:
            encoded_name = encoded_name.split("''", 1)[1]
        candidate = unquote(encoded_name)
    else:
        candidate = parameters.get("filename") or unquote(
            urlsplit(url).path.rsplit("/", 1)[-1]
        )

    try:
        return safe_file_name(candidate)
    except ValueError:
        return f"download-{index + 1}"


def available_file_path(directory: Path, file_name: str) -> Path:
    target = directory / file_name
    if not target.exists():
        return target

    suffixes = "".join(target.suffixes)
    stem = target.name[: -len(suffixes)] if suffixes else target.name
    for number in range(1, 10_000):
        candidate = directory / f"{stem} ({number}){suffixes}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Unable to allocate a unique file name")


def file_entry(path: Path) -> dict:
    resolved_path = path.resolve()
    stat = resolved_path.stat()
    relative = resolved_path.relative_to(MOUNT_PATH.resolve()).as_posix()
    return {
        "name": resolved_path.name,
        "path": "/" + relative,
        "type": "directory" if resolved_path.is_dir() else "file",
        "size": 0 if resolved_path.is_dir() else stat.st_size,
        "mimeType": (
            None
            if resolved_path.is_dir()
            else mimetypes.guess_type(resolved_path.name)[0]
        ),
        "modifiedAt": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def parse_frame_rate(value: object) -> float | None:
    try:
        if not value or value == "0/0":
            return None
        return round(float(Fraction(str(value))), 4)
    except (ValueError, ZeroDivisionError):
        return None


def video_metadata(path: Path) -> dict | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,bit_rate,format_name:"
                    "stream=codec_type,codec_name,width,height,r_frame_rate"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None

    streams = payload.get("streams") if isinstance(payload, dict) else []
    streams = streams if isinstance(streams, list) else []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        {},
    )
    file_format = payload.get("format") if isinstance(payload, dict) else {}
    file_format = file_format if isinstance(file_format, dict) else {}

    def number(value: object, cast):
        try:
            return cast(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    return {
        "durationSeconds": number(file_format.get("duration"), float),
        "width": number(video.get("width"), int),
        "height": number(video.get("height"), int),
        "videoCodec": video.get("codec_name"),
        "audioCodec": audio.get("codec_name"),
        "frameRate": parse_frame_rate(video.get("r_frame_rate")),
        "bitRate": number(file_format.get("bit_rate"), int),
        "containerFormat": file_format.get("format_name"),
    }


def cloud_video_metadata(remote_path: str) -> dict | None:
    rclone_process: subprocess.Popen[bytes] | None = None
    try:
        rclone_process = subprocess.Popen(
            rclone_command(["cat", rclone_target(remote_path)]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,bit_rate,format_name:"
                    "stream=codec_type,codec_name,width,height,r_frame_rate"
                ),
                "-of",
                "json",
                "pipe:0",
            ],
            stdin=rclone_process.stdout,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if rclone_process.stdout:
            rclone_process.stdout.close()
        rclone_stderr = (
            rclone_process.stderr.read().decode("utf-8", errors="replace")
            if rclone_process.stderr
            else ""
        )
        rclone_code = rclone_process.wait(timeout=10)
        if result.returncode != 0 or rclone_code != 0:
            return None
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    finally:
        if rclone_process and rclone_process.poll() is None:
            rclone_process.terminate()

    streams = payload.get("streams") if isinstance(payload, dict) else []
    streams = streams if isinstance(streams, list) else []
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        {},
    )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        {},
    )
    file_format = payload.get("format") if isinstance(payload, dict) else {}
    file_format = file_format if isinstance(file_format, dict) else {}

    def number(value: object, cast):
        try:
            return cast(value) if value not in {None, ""} else None
        except (TypeError, ValueError):
            return None

    return {
        "durationSeconds": number(file_format.get("duration"), float),
        "width": number(video.get("width"), int),
        "height": number(video.get("height"), int),
        "videoCodec": video.get("codec_name"),
        "audioCodec": audio.get("codec_name"),
        "frameRate": parse_frame_rate(video.get("r_frame_rate")),
        "bitRate": number(file_format.get("bit_rate"), int),
        "containerFormat": file_format.get("format_name"),
    }


def available_cloud_path(directory: str, file_name: str) -> str:
    target = f"{directory.rstrip('/')}/{file_name}"
    if not path_exists(target):
        return target

    name_path = Path(file_name)
    suffixes = "".join(name_path.suffixes)
    stem = name_path.name[: -len(suffixes)] if suffixes else name_path.name
    for number in range(1, 10_000):
        candidate = f"{directory.rstrip('/')}/{stem} ({number}){suffixes}"
        if not path_exists(candidate):
            return candidate
    raise RuntimeError("Unable to allocate a unique cloud file name")


def offline_download_cloud_batch(job_id: str, remote_directory: str, urls: list[str]):
    import httpx

    started_at = utc_now()
    directory = rclone_stat(remote_directory)
    if not directory or not directory.get("IsDir"):
        raise FileNotFoundError("Cloud destination directory no longer exists")

    results = []
    completed = 0
    failed = 0
    total_bytes_downloaded = 0
    canceled = False
    update_download_job(
        job_id,
        status="downloading",
        startedAt=started_at,
        completed=0,
        failed=0,
        currentIndex=None,
        currentUrl=None,
        currentFileName=None,
        currentBytes=0,
        currentTotalBytes=None,
        bytesPerSecond=0,
        totalBytesDownloaded=0,
        results=[],
    )

    timeout = httpx.Timeout(connect=30, read=15, write=30, pool=30)
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "TOOLBOX-Modal-Drive/1.0"},
    ) as client:
        for index, url in enumerate(urls):
            process: subprocess.Popen[bytes] | None = None
            target: str | None = None
            try:
                if download_jobs.get(job_id, {}).get("cancelRequested"):
                    raise DownloadCanceled()
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    file_name = response_file_name(
                        response.headers.get("content-disposition"),
                        str(response.url),
                        index,
                    )
                    target = available_cloud_path(remote_directory, file_name)
                    try:
                        current_total_bytes = int(response.headers["content-length"])
                    except (KeyError, ValueError):
                        current_total_bytes = None

                    arguments = ["rcat", rclone_target(target)]
                    if current_total_bytes is not None:
                        arguments.extend(["--size", str(current_total_bytes)])
                    process = subprocess.Popen(
                        rclone_command(arguments),
                        stdin=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    if process.stdin is None:
                        raise RuntimeError("Unable to open the rclone upload stream")

                    current_bytes = 0
                    current_started = time.monotonic()
                    last_progress_update = 0.0
                    update_download_job(
                        job_id,
                        status="downloading",
                        currentIndex=index + 1,
                        currentUrl=url,
                        currentFileName=file_name,
                        currentBytes=0,
                        currentTotalBytes=current_total_bytes,
                        bytesPerSecond=0,
                    )
                    for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        process.stdin.write(chunk)
                        current_bytes += len(chunk)
                        now = time.monotonic()
                        if now - last_progress_update >= 0.75:
                            record = download_jobs.get(job_id, {})
                            if record.get("cancelRequested"):
                                raise DownloadCanceled()
                            elapsed = max(now - current_started, 0.001)
                            record.update(
                                {
                                    "status": "downloading",
                                    "currentBytes": current_bytes,
                                    "currentTotalBytes": current_total_bytes,
                                    "bytesPerSecond": round(current_bytes / elapsed),
                                    "updatedAt": utc_now(),
                                }
                            )
                            download_jobs.put(job_id, record)
                            last_progress_update = now

                    process.stdin.close()
                    stderr = (
                        process.stderr.read().decode("utf-8", errors="replace")
                        if process.stderr
                        else ""
                    )
                    return_code = process.wait(timeout=60 * 60)
                    if return_code != 0:
                        raise RcloneCommandError(
                            stderr.strip()[:1000] or "rclone upload failed",
                            return_code,
                        )

                completed += 1
                total_bytes_downloaded += current_bytes
                results.append(
                    {
                        "url": url,
                        "status": "completed",
                        "entry": cloud_entry(target),
                    }
                )
                update_download_job(
                    job_id,
                    completed=completed,
                    failed=failed,
                    totalBytesDownloaded=total_bytes_downloaded,
                    currentBytes=0,
                    currentTotalBytes=None,
                    bytesPerSecond=0,
                    results=results,
                )
            except DownloadCanceled:
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                if target:
                    run_rclone(["deletefile", rclone_target(target)], check=False)
                results.append(
                    {"url": url, "status": "canceled", "error": "Canceled by user"}
                )
                canceled = True
                break
            except Exception as error:
                if process and process.poll() is None:
                    process.terminate()
                if target:
                    run_rclone(["deletefile", rclone_target(target)], check=False)
                failed += 1
                results.append(
                    {
                        "url": url,
                        "status": "failed",
                        "error": str(error)[:500] or error.__class__.__name__,
                    }
                )
                update_download_job(
                    job_id,
                    completed=completed,
                    failed=failed,
                    currentBytes=0,
                    currentTotalBytes=None,
                    bytesPerSecond=0,
                    results=results,
                )

    result = {
        "status": "canceled" if canceled else "completed",
        "path": remote_directory,
        "total": len(urls),
        "completed": completed,
        "failed": failed,
        "startedAt": started_at,
        "completedAt": utc_now(),
        "currentIndex": None,
        "currentUrl": None,
        "currentFileName": None,
        "currentBytes": 0,
        "currentTotalBytes": None,
        "bytesPerSecond": 0,
        "totalBytesDownloaded": total_bytes_downloaded,
        "results": results,
    }
    update_download_job(job_id, **result)
    return result


def transfer_command(
    arguments: list[str],
    *,
    uses_cloud: bool,
    log_level: str = "ERROR",
) -> list[str]:
    if uses_cloud:
        return rclone_command(arguments, log_level=log_level)
    return ["rclone", "--log-level", log_level, *arguments]


def transfer_size(source_entry: dict) -> tuple[int, int]:
    if source_entry["type"] == "file":
        return int(source_entry.get("size") or 0), 1
    return 0, 0


def delete_transfer_source(source_path: str, source_entry: dict):
    if is_cloud_path(source_path):
        command = "purge" if source_entry["type"] == "directory" else "deletefile"
        run_rclone([command, rclone_target(source_path)])
        return

    _, source = resolve_remote_path(source_path)
    if source_entry["type"] == "directory":
        shutil.rmtree(source)
    else:
        source.unlink()
    volume.commit()


def cleanup_transfer_destination(destination_path: str):
    try:
        if is_cloud_path(destination_path):
            stat = rclone_stat(destination_path)
            if not stat:
                return
            command = "purge" if stat.get("IsDir") else "deletefile"
            run_rclone([command, rclone_target(destination_path)], check=False)
            return

        _, destination = resolve_remote_path(destination_path)
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        volume.commit()
    except Exception:
        pass


@app.function(
    image=image,
    volumes={str(MOUNT_PATH): volume},
    secrets=[rclone_secret],
    timeout=24 * 60 * 60,
    max_containers=1,
)
def transfer_entry_job(
    job_id: str,
    operation: str,
    source_path: str,
    destination_path: str,
):
    import queue
    import threading

    started_at = utc_now()
    process: subprocess.Popen[str] | None = None
    copy_completed = False
    volume.reload()
    update_transfer_job(
        job_id,
        status="preparing",
        startedAt=started_at,
        currentBytes=0,
        currentTotalBytes=None,
        bytesPerSecond=0,
        currentFileName=None,
        completedFiles=0,
        totalFiles=None,
    )

    try:
        if not path_exists(source_path):
            raise FileNotFoundError("Source file or folder no longer exists")
        if path_exists(destination_path):
            raise FileExistsError("Destination already exists")

        source_entry = path_entry(source_path)
        total_bytes, total_files = transfer_size(source_entry)
        if transfer_jobs.get(job_id, {}).get("cancelRequested"):
            result = {
                "status": "canceled",
                "completedAt": utc_now(),
                "bytesPerSecond": 0,
                "error": "Canceled by user",
            }
            update_transfer_job(job_id, **result)
            return result
        uses_cloud = is_cloud_path(source_path) or is_cloud_path(destination_path)
        arguments = [
            "copyto",
            rclone_storage_path(source_path),
            rclone_storage_path(destination_path),
            "--stats",
            "750ms",
            "--stats-log-level",
            "NOTICE",
            "--stats-file-name-length",
            "0",
            "--use-json-log",
        ]
        process = subprocess.Popen(
            transfer_command(arguments, uses_cloud=uses_cloud, log_level="INFO"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if process.stdout is None:
            raise RuntimeError("Unable to read rclone transfer progress")

        lines: queue.Queue[str | None] = queue.Queue()

        def read_output():
            assert process and process.stdout
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        canceled = False
        output_finished = False
        last_error = ""
        progress = {
            "currentBytes": 0,
            "currentTotalBytes": total_bytes or None,
            "bytesPerSecond": 0,
            "currentFileName": None,
            "completedFiles": 0,
            "totalFiles": total_files or None,
        }
        update_transfer_job(job_id, status="transferring", **progress)

        while process.poll() is None or not output_finished:
            record = transfer_jobs.get(job_id, {})
            if record.get("cancelRequested") and process.poll() is None:
                canceled = True
                process.terminate()

            try:
                line = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                output_finished = True
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("level") in {"error", "fatal"}:
                last_error = str(payload.get("msg") or "")[:1000]
            object_name = payload.get("object")
            if isinstance(object_name, str) and object_name:
                progress["currentFileName"] = object_name
            stats = payload.get("stats")
            if not isinstance(stats, dict):
                continue
            current_bytes = max(0, int(stats.get("bytes") or 0))
            stats_total = max(0, int(stats.get("totalBytes") or 0))
            progress.update(
                {
                    "currentBytes": current_bytes,
                    "currentTotalBytes": stats_total or total_bytes or None,
                    "bytesPerSecond": max(0, round(float(stats.get("speed") or 0))),
                    "completedFiles": max(0, int(stats.get("transfers") or 0)),
                    "totalFiles": max(
                        0,
                        int(stats.get("totalTransfers") or total_files or 0),
                    )
                    or None,
                }
            )
            update_transfer_job(job_id, status="transferring", **progress)

        return_code = process.wait()
        if canceled or transfer_jobs.get(job_id, {}).get("cancelRequested"):
            cleanup_transfer_destination(destination_path)
            result = {
                "status": "canceled",
                "completedAt": utc_now(),
                "bytesPerSecond": 0,
                "error": "Canceled by user; incomplete destination data was removed",
                **progress,
            }
            update_transfer_job(job_id, **result)
            return result
        if return_code != 0:
            raise RcloneCommandError(
                last_error or f"rclone transfer exited with code {return_code}",
                return_code,
            )

        copy_completed = True
        if not is_cloud_path(destination_path):
            volume.commit()
        if operation == "move":
            update_transfer_job(job_id, status="finalizing", bytesPerSecond=0)
            delete_transfer_source(source_path, source_entry)

        entry = path_entry(destination_path)
        completed_bytes = total_bytes or int(progress["currentBytes"] or 0)
        result = {
            "status": "completed",
            "completedAt": utc_now(),
            "entry": entry,
            "currentBytes": completed_bytes,
            "currentTotalBytes": completed_bytes,
            "bytesPerSecond": 0,
            "currentFileName": None,
            "completedFiles": total_files or progress["completedFiles"],
            "totalFiles": total_files or progress["totalFiles"],
        }
        update_transfer_job(job_id, **result)
        return result
    except Exception as error:
        if process and process.poll() is None:
            process.terminate()
        if not copy_completed:
            cleanup_transfer_destination(destination_path)
        result = {
            "status": "failed",
            "completedAt": utc_now(),
            "bytesPerSecond": 0,
            "error": str(error)[:1000] or error.__class__.__name__,
        }
        update_transfer_job(job_id, **result)
        return result


@app.function(
    image=image,
    volumes={str(MOUNT_PATH): volume},
    secrets=[rclone_secret],
    timeout=24 * 60 * 60,
    max_containers=1,
)
def offline_download_batch(job_id: str, remote_directory: str, urls: list[str]):
    import httpx

    if is_cloud_path(remote_directory):
        return offline_download_cloud_batch(job_id, remote_directory, urls)

    started_at = utc_now()
    volume.reload()
    _, local_directory = resolve_remote_path(remote_directory)
    results = []
    completed = 0
    failed = 0
    total_bytes_downloaded = 0

    update_download_job(
        job_id,
        status="downloading",
        startedAt=started_at,
        completed=0,
        failed=0,
        currentIndex=None,
        currentUrl=None,
        currentFileName=None,
        currentBytes=0,
        currentTotalBytes=None,
        bytesPerSecond=0,
        totalBytesDownloaded=0,
        results=[],
    )

    if not local_directory.exists() or not local_directory.is_dir():
        result = {
            "status": "failed",
            "path": remote_directory,
            "total": len(urls),
            "completed": 0,
            "failed": len(urls),
            "startedAt": started_at,
            "completedAt": utc_now(),
            "results": [
                {
                    "url": url,
                    "status": "failed",
                    "error": "Destination directory no longer exists",
                }
                for url in urls
            ],
        }
        update_download_job(job_id, **result)
        return result

    canceled = False
    timeout = httpx.Timeout(connect=30, read=15, write=30, pool=30)
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": "TOOLBOX-Modal-Drive/1.0"},
    ) as client:
        for index, url in enumerate(urls):
            temporary: Path | None = None
            try:
                if download_jobs.get(job_id, {}).get("cancelRequested"):
                    raise DownloadCanceled()

                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    file_name = response_file_name(
                        response.headers.get("content-disposition"),
                        str(response.url),
                        index,
                    )
                    target = available_file_path(local_directory, file_name)
                    temporary = local_directory / f".offline-{uuid.uuid4().hex}.part"
                    content_length = response.headers.get("content-length")
                    try:
                        current_total_bytes = (
                            int(content_length) if content_length is not None else None
                        )
                    except ValueError:
                        current_total_bytes = None

                    current_bytes = 0
                    current_started = time.monotonic()
                    last_progress_update = 0.0
                    update_download_job(
                        job_id,
                        status="downloading",
                        currentIndex=index + 1,
                        currentUrl=url,
                        currentFileName=target.name,
                        currentBytes=0,
                        currentTotalBytes=current_total_bytes,
                        bytesPerSecond=0,
                    )
                    with temporary.open("wb") as destination:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            destination.write(chunk)
                            current_bytes += len(chunk)
                            now = time.monotonic()
                            if now - last_progress_update >= 0.75:
                                record = download_jobs.get(job_id, {})
                                if record.get("cancelRequested"):
                                    raise DownloadCanceled()
                                elapsed = max(now - current_started, 0.001)
                                record.update(
                                    {
                                        "status": "downloading",
                                        "currentBytes": current_bytes,
                                        "currentTotalBytes": current_total_bytes,
                                        "bytesPerSecond": round(
                                            current_bytes / elapsed
                                        ),
                                        "updatedAt": utc_now(),
                                    }
                                )
                                download_jobs.put(job_id, record)
                                last_progress_update = now

                    if download_jobs.get(job_id, {}).get("cancelRequested"):
                        raise DownloadCanceled()
                    temporary.replace(target)

                volume.commit()
                completed += 1
                total_bytes_downloaded += current_bytes
                results.append(
                    {
                        "url": url,
                        "status": "completed",
                        "entry": file_entry(target),
                    }
                )
                update_download_job(
                    job_id,
                    completed=completed,
                    failed=failed,
                    totalBytesDownloaded=total_bytes_downloaded,
                    currentBytes=0,
                    currentTotalBytes=None,
                    bytesPerSecond=0,
                    results=results,
                )
            except DownloadCanceled:
                if temporary and temporary.exists():
                    temporary.unlink()
                results.append(
                    {
                        "url": url,
                        "status": "canceled",
                        "error": "Canceled by user",
                    }
                )
                canceled = True
                break
            except Exception as error:
                if temporary and temporary.exists():
                    temporary.unlink()
                failed += 1
                results.append(
                    {
                        "url": url,
                        "status": "failed",
                        "error": str(error)[:500] or error.__class__.__name__,
                    }
                )
                update_download_job(
                    job_id,
                    completed=completed,
                    failed=failed,
                    currentBytes=0,
                    currentTotalBytes=None,
                    bytesPerSecond=0,
                    results=results,
                )

    result = {
        "status": "canceled" if canceled else "completed",
        "path": remote_directory,
        "total": len(urls),
        "completed": completed,
        "failed": failed,
        "startedAt": started_at,
        "completedAt": utc_now(),
        "currentIndex": None,
        "currentUrl": None,
        "currentFileName": None,
        "currentBytes": 0,
        "currentTotalBytes": None,
        "bytesPerSecond": 0,
        "totalBytesDownloaded": total_bytes_downloaded,
        "results": results,
    }
    update_download_job(job_id, **result)
    return result


@app.function(
    image=image,
    volumes={str(MOUNT_PATH): volume},
    secrets=[rclone_secret],
    timeout=60 * 60,
)
@modal.asgi_app(requires_proxy_auth=True)
def drive_api():
    from fastapi import FastAPI, File, HTTPException, Query, UploadFile
    from fastapi.responses import FileResponse, StreamingResponse
    from pydantic import BaseModel, Field

    web = FastAPI(title="TOOLBOX Modal Drive API", docs_url=None, redoc_url=None)

    class FolderPayload(BaseModel):
        path: str = Field(min_length=1, max_length=4096)

    class RenamePayload(BaseModel):
        path: str = Field(min_length=1, max_length=4096)
        new_name: str = Field(alias="newName", min_length=1, max_length=255)

    class OfflineDownloadPayload(BaseModel):
        path: str = Field(default="/", min_length=1, max_length=4096)
        urls: list[str] = Field(min_length=1, max_length=50)

    class TransferPayload(BaseModel):
        source_path: str = Field(alias="sourcePath", min_length=1, max_length=4096)
        destination_path: str = Field(
            alias="destinationPath",
            min_length=1,
            max_length=4096,
        )

    def checked_remote_path(value: str | None) -> str:
        try:
            return normalize_remote_path(value)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    def checked_path(value: str | None) -> tuple[str, Path]:
        try:
            return resolve_remote_path(value)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    def cloud_failure(error: Exception):
        if isinstance(error, RcloneNotConfigured):
            raise HTTPException(status_code=503, detail=str(error)) from error
        if isinstance(error, RcloneCommandError):
            if error.return_code == 3:
                raise HTTPException(status_code=404, detail=str(error)) from error
            raise HTTPException(
                status_code=502,
                detail=f"rclone operation failed: {str(error)}",
            ) from error
        raise error

    @web.get("/health")
    def health():
        configured = bool(os.environ.get("TOOLBOX_RCLONE_CONFIG_B64"))
        remotes: list[str] = []
        if configured:
            try:
                remotes = list(rclone_remotes())
            except (RcloneNotConfigured, RcloneCommandError):
                pass
        return {
            "ok": True,
            "volume": VOLUME_NAME,
            "cloud": {
                "path": CLOUD_ROOT,
                "configured": configured,
                "remotes": remotes,
            },
        }

    @web.get("/files")
    def list_files(path: str = Query(default="/", max_length=4096)):
        remote_path = checked_remote_path(path)
        if is_cloud_path(remote_path):
            try:
                stat = rclone_stat(remote_path)
                if not stat:
                    raise HTTPException(status_code=404, detail="Directory not found")
                if not stat.get("IsDir"):
                    raise HTTPException(
                        status_code=400,
                        detail="Path is not a directory",
                    )
                entries = list_cloud_directory(remote_path)
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            return {"ok": True, "path": remote_path, "entries": entries}

        volume.reload()
        _, local_path = checked_path(remote_path)
        if not local_path.exists():
            raise HTTPException(status_code=404, detail="Directory not found")
        if not local_path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")

        local_entries = (
            file_entry(item)
            for item in local_path.iterdir()
            if not (remote_path == "/" and item.name == CLOUD_ROOT.lstrip("/"))
        )
        entries = sorted(
            local_entries,
            key=lambda item: (item["type"] != "directory", item["name"].lower()),
        )
        if remote_path == "/":
            entries.insert(0, cloud_entry(CLOUD_ROOT))
        return {"ok": True, "path": remote_path, "entries": entries}

    @web.post("/folders")
    def create_folder(payload: FolderPayload):
        remote_path = checked_remote_path(payload.path)
        if remote_path == CLOUD_ROOT:
            raise HTTPException(status_code=409, detail="Cloud already exists")
        if is_cloud_path(remote_path):
            parent = remote_path.rsplit("/", 1)[0] or "/"
            if parent == CLOUD_ROOT:
                raise HTTPException(
                    status_code=400,
                    detail="Select an existing Cloud remote before creating a folder",
                )
            try:
                if rclone_stat(remote_path):
                    raise HTTPException(status_code=409, detail="Path already exists")
                run_rclone(["mkdir", rclone_target(remote_path)])
                entry = cloud_entry(remote_path)
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            return {"ok": True, "path": remote_path, "entry": entry}

        volume.reload()
        _, local_path = checked_path(remote_path)
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
        remote_directory = checked_remote_path(path)
        try:
            file_name = safe_file_name(file.filename)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        if is_cloud_path(remote_directory):
            if remote_directory == CLOUD_ROOT:
                raise HTTPException(
                    status_code=400,
                    detail="Select a Cloud remote before uploading",
                )
            target = f"{remote_directory.rstrip('/')}/{file_name}"
            process: subprocess.Popen[bytes] | None = None
            try:
                directory = rclone_stat(remote_directory)
                if not directory or not directory.get("IsDir"):
                    raise HTTPException(status_code=404, detail="Directory not found")
                if not overwrite and rclone_stat(target):
                    raise HTTPException(status_code=409, detail="File already exists")

                arguments = ["rcat", rclone_target(target)]
                if file.size is not None:
                    arguments.extend(["--size", str(file.size)])
                process = subprocess.Popen(
                    rclone_command(arguments),
                    stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                if process.stdin is None:
                    raise RuntimeError("Unable to open the rclone upload stream")
                while chunk := await file.read(1024 * 1024):
                    process.stdin.write(chunk)
                process.stdin.close()
                stderr = (
                    process.stderr.read().decode("utf-8", errors="replace")
                    if process.stderr
                    else ""
                )
                return_code = process.wait(timeout=60 * 60)
                if return_code != 0:
                    raise RcloneCommandError(
                        stderr.strip()[:1000] or "rclone upload failed",
                        return_code,
                    )
                entry = cloud_entry(target)
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            finally:
                await file.close()
                if process and process.poll() is None:
                    process.terminate()
            return {"ok": True, "path": remote_directory, "entry": entry}

        volume.reload()
        _, local_directory = checked_path(remote_directory)
        if not local_directory.exists() or not local_directory.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")

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

    @web.post("/offline-download")
    def start_offline_download(payload: OfflineDownloadPayload):
        remote_directory = checked_remote_path(payload.path)
        if is_cloud_path(remote_directory):
            if remote_directory == CLOUD_ROOT:
                raise HTTPException(
                    status_code=400,
                    detail="Select a Cloud remote before starting an offline download",
                )
            try:
                directory = rclone_stat(remote_directory)
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            if not directory or not directory.get("IsDir"):
                raise HTTPException(status_code=404, detail="Directory not found")
        else:
            volume.reload()
            _, local_directory = checked_path(remote_directory)
            if not local_directory.exists() or not local_directory.is_dir():
                raise HTTPException(status_code=404, detail="Directory not found")

        try:
            urls = [checked_download_url(url) for url in payload.urls]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        job_id = uuid.uuid4().hex
        initial = {
            "status": "queued",
            "path": remote_directory,
            "total": len(urls),
            "completed": 0,
            "failed": 0,
            "currentIndex": None,
            "currentUrl": None,
            "currentFileName": None,
            "currentBytes": 0,
            "currentTotalBytes": None,
            "bytesPerSecond": 0,
            "totalBytesDownloaded": 0,
            "results": [],
            "createdAt": utc_now(),
            "cancelRequested": False,
        }
        download_jobs.put(job_id, initial)
        try:
            function_call = offline_download_batch.spawn(
                job_id,
                remote_directory,
                urls,
            )
        except Exception as error:
            update_download_job(
                job_id,
                status="failed",
                completedAt=utc_now(),
                error=f"Unable to start download: {str(error)[:500]}",
            )
            raise HTTPException(
                status_code=500,
                detail="Unable to start offline download",
            ) from error

        record = update_download_job(job_id, _callId=function_call.object_id)
        return public_download_job(job_id, record)

    @web.get("/offline-download")
    def offline_download_status(
        job_id: str = Query(alias="jobId", min_length=1, max_length=128),
    ):
        record = download_jobs.get(job_id)
        if not record:
            if not job_id.startswith("fc-"):
                raise HTTPException(status_code=404, detail="Download job not found")
            function_call = modal.FunctionCall.from_id(job_id)
            try:
                result = function_call.get(timeout=0)
            except TimeoutError:
                return {
                    "ok": True,
                    "jobId": job_id,
                    "status": "pending",
                    "legacy": True,
                }
            except modal.exception.OutputExpiredError as error:
                raise HTTPException(
                    status_code=404,
                    detail="Download result has expired",
                ) from error
            except Exception as error:
                raise HTTPException(
                    status_code=500,
                    detail=f"Offline download failed: {str(error)[:500]}",
                ) from error
            return {
                "ok": True,
                "jobId": job_id,
                "legacy": True,
                **result,
            }

        call_id = record.get("_callId")
        if record.get("status") not in TERMINAL_DOWNLOAD_STATUSES and call_id:
            function_call = modal.FunctionCall.from_id(call_id)
            try:
                result = function_call.get(timeout=0)
            except TimeoutError:
                pass
            except modal.exception.OutputExpiredError:
                record = update_download_job(
                    job_id,
                    status="failed",
                    completedAt=utc_now(),
                    error="Download result has expired",
                )
            except Exception as error:
                record = update_download_job(
                    job_id,
                    status="failed",
                    completedAt=utc_now(),
                    error=str(error)[:500] or error.__class__.__name__,
                )
            else:
                record = update_download_job(job_id, **result)

        return public_download_job(job_id, record)

    @web.delete("/offline-download")
    def stop_offline_download(
        job_id: str = Query(alias="jobId", min_length=1, max_length=128),
    ):
        record = download_jobs.get(job_id)
        if not record:
            if not job_id.startswith("fc-"):
                raise HTTPException(status_code=404, detail="Download job not found")
            modal.FunctionCall.from_id(job_id).cancel(terminate_containers=True)
            return {
                "ok": True,
                "jobId": job_id,
                "status": "canceled",
                "legacy": True,
            }
        if record.get("status") in TERMINAL_DOWNLOAD_STATUSES:
            return public_download_job(job_id, record)

        record = update_download_job(
            job_id,
            status="canceling",
            cancelRequested=True,
        )
        return public_download_job(job_id, record)

    @web.patch("/files")
    def rename_file(payload: RenamePayload):
        remote_path = checked_remote_path(payload.path)
        if remote_path in {"/", CLOUD_ROOT} or (
            is_cloud_path(remote_path) and is_cloud_remote_root(remote_path)
        ):
            raise HTTPException(status_code=400, detail="Cannot rename this root")

        try:
            new_name = safe_file_name(payload.new_name)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        parent = remote_path.rsplit("/", 1)[0] or "/"
        destination_path = normalize_remote_path(
            f"{parent.rstrip('/')}/{new_name}"
        )

        if is_cloud_path(remote_path):
            try:
                if not rclone_stat(remote_path):
                    raise HTTPException(
                        status_code=404,
                        detail="File or folder not found",
                    )
                if rclone_stat(destination_path):
                    raise HTTPException(
                        status_code=409,
                        detail="Destination already exists",
                    )
                run_rclone(
                    [
                        "moveto",
                        rclone_target(remote_path),
                        rclone_target(destination_path),
                    ]
                )
                entry = cloud_entry(destination_path)
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            return {
                "ok": True,
                "sourcePath": remote_path,
                "destinationPath": destination_path,
                "entry": entry,
            }

        volume.reload()
        _, local_path = checked_path(remote_path)
        if not local_path.exists():
            raise HTTPException(status_code=404, detail="File or folder not found")

        destination = local_path.with_name(new_name)
        if destination.exists():
            raise HTTPException(status_code=409, detail="Destination already exists")
        local_path.rename(destination)
        volume.commit()
        return {
            "ok": True,
            "sourcePath": remote_path,
            "destinationPath": destination_path,
            "entry": file_entry(destination),
        }

    @web.delete("/files")
    def delete_file(
        path: str = Query(min_length=1, max_length=4096),
        recursive: bool = Query(default=False),
    ):
        remote_path = checked_remote_path(path)
        if remote_path in {"/", CLOUD_ROOT} or (
            is_cloud_path(remote_path) and is_cloud_remote_root(remote_path)
        ):
            raise HTTPException(status_code=400, detail="Cannot delete this root")
        if is_cloud_path(remote_path):
            try:
                stat = rclone_stat(remote_path)
                if not stat:
                    raise HTTPException(
                        status_code=404,
                        detail="File or folder not found",
                    )
                if stat.get("IsDir"):
                    command = "purge" if recursive else "rmdir"
                    run_rclone([command, rclone_target(remote_path)])
                else:
                    run_rclone(["deletefile", rclone_target(remote_path)])
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            return {"ok": True, "path": remote_path}

        volume.reload()
        _, local_path = checked_path(remote_path)
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

    def start_transfer(payload: TransferPayload, operation: str):
        source_path = checked_remote_path(payload.source_path)
        destination_path = checked_remote_path(payload.destination_path)
        if source_path in {"/", CLOUD_ROOT} or (
            is_cloud_path(source_path) and is_cloud_remote_root(source_path)
        ):
            raise HTTPException(status_code=400, detail="Cannot transfer this root")
        if destination_path in {"/", CLOUD_ROOT} or (
            is_cloud_path(destination_path)
            and is_cloud_remote_root(destination_path)
        ):
            raise HTTPException(
                status_code=400,
                detail="Destination must include a file or folder name",
            )
        if source_path == destination_path:
            raise HTTPException(
                status_code=400,
                detail="Source and destination must be different",
            )

        volume.reload()
        try:
            if not path_exists(source_path):
                raise HTTPException(
                    status_code=404,
                    detail="Source file or folder not found",
                )
            if path_exists(destination_path):
                raise HTTPException(
                    status_code=409,
                    detail="Destination already exists",
                )
        except (RcloneNotConfigured, RcloneCommandError) as error:
            cloud_failure(error)

        job_id = uuid.uuid4().hex
        initial = {
            "status": "queued",
            "operation": operation,
            "sourcePath": source_path,
            "destinationPath": destination_path,
            "currentBytes": 0,
            "currentTotalBytes": None,
            "bytesPerSecond": 0,
            "currentFileName": None,
            "completedFiles": 0,
            "totalFiles": None,
            "createdAt": utc_now(),
            "cancelRequested": False,
        }
        transfer_jobs.put(job_id, initial)
        try:
            function_call = transfer_entry_job.spawn(
                job_id,
                operation,
                source_path,
                destination_path,
            )
        except Exception as error:
            update_transfer_job(
                job_id,
                status="failed",
                completedAt=utc_now(),
                error=f"Unable to start transfer: {str(error)[:500]}",
            )
            raise HTTPException(
                status_code=500,
                detail="Unable to start transfer",
            ) from error
        record = update_transfer_job(job_id, _callId=function_call.object_id)
        return public_transfer_job(job_id, record)

    @web.post("/copy")
    def copy_entry(payload: TransferPayload):
        return start_transfer(payload, "copy")

    @web.post("/move")
    def move_entry(payload: TransferPayload):
        return start_transfer(payload, "move")

    @web.get("/transfer")
    def transfer_status(
        job_id: str = Query(alias="jobId", min_length=1, max_length=128),
    ):
        record = transfer_jobs.get(job_id)
        if not record:
            raise HTTPException(status_code=404, detail="Transfer job not found")

        call_id = record.get("_callId")
        if record.get("status") not in TERMINAL_DOWNLOAD_STATUSES and call_id:
            function_call = modal.FunctionCall.from_id(call_id)
            try:
                result = function_call.get(timeout=0)
            except TimeoutError:
                pass
            except modal.exception.OutputExpiredError:
                record = update_transfer_job(
                    job_id,
                    status="failed",
                    completedAt=utc_now(),
                    error="Transfer result has expired",
                )
            except Exception as error:
                record = update_transfer_job(
                    job_id,
                    status="failed",
                    completedAt=utc_now(),
                    error=str(error)[:500] or error.__class__.__name__,
                )
            else:
                record = update_transfer_job(job_id, **result)
        return public_transfer_job(job_id, record)

    @web.delete("/transfer")
    def stop_transfer(
        job_id: str = Query(alias="jobId", min_length=1, max_length=128),
    ):
        record = transfer_jobs.get(job_id)
        if not record:
            raise HTTPException(status_code=404, detail="Transfer job not found")
        if record.get("status") in TERMINAL_DOWNLOAD_STATUSES:
            return public_transfer_job(job_id, record)
        record = update_transfer_job(
            job_id,
            status="canceling",
            cancelRequested=True,
        )
        return public_transfer_job(job_id, record)

    @web.get("/download")
    def download_file(path: str = Query(min_length=1, max_length=4096)):
        remote_path = checked_remote_path(path)
        if is_cloud_path(remote_path):
            try:
                stat = rclone_stat(remote_path)
                if not stat or stat.get("IsDir"):
                    raise HTTPException(status_code=404, detail="File not found")
                entry = cloud_entry(remote_path, stat)
                process = subprocess.Popen(
                    rclone_command(["cat", rclone_target(remote_path)]),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)

            def stream_cloud_file():
                try:
                    if process.stdout:
                        while chunk := process.stdout.read(1024 * 1024):
                            yield chunk
                    return_code = process.wait()
                    if return_code != 0:
                        stderr = (
                            process.stderr.read().decode("utf-8", errors="replace")
                            if process.stderr
                            else ""
                        )
                        raise RuntimeError(stderr.strip() or "rclone download failed")
                finally:
                    if process.poll() is None:
                        process.terminate()

            encoded_name = quote(entry["name"])
            return StreamingResponse(
                stream_cloud_file(),
                media_type=entry.get("mimeType") or "application/octet-stream",
                headers={
                    "Content-Length": str(entry["size"]),
                    "Content-Disposition": (
                        f"attachment; filename*=UTF-8''{encoded_name}"
                    ),
                },
            )

        volume.reload()
        _, local_path = checked_path(remote_path)
        if remote_path == "/" or not local_path.exists() or not local_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        media_type, _ = mimetypes.guess_type(local_path.name)
        return FileResponse(
            path=local_path,
            filename=local_path.name,
            media_type=media_type or "application/octet-stream",
        )

    @web.get("/metadata")
    def metadata(path: str = Query(min_length=1, max_length=4096)):
        remote_path = checked_remote_path(path)
        if is_cloud_path(remote_path):
            try:
                stat = rclone_stat(remote_path)
                if not stat or stat.get("IsDir"):
                    raise HTTPException(status_code=404, detail="File not found")
                entry = cloud_entry(remote_path, stat)
                media = (
                    cloud_video_metadata(remote_path)
                    if str(entry.get("mimeType") or "").startswith("video/")
                    else None
                )
            except (RcloneNotConfigured, RcloneCommandError) as error:
                cloud_failure(error)
            return {"entry": entry, "video": media}

        volume.reload()
        _, local_path = checked_path(remote_path)
        if remote_path == "/" or not local_path.exists() or not local_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        entry = file_entry(local_path)
        media = (
            video_metadata(local_path)
            if str(entry.get("mimeType") or "").startswith("video/")
            else None
        )
        return {"entry": entry, "video": media}

    return web
