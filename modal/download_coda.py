#!/usr/bin/env python3
"""Recursively download the public CODa dataset directory.

The default destination is the ``CODa`` directory next to this script. Files
are first written with a ``.part`` suffix and atomically renamed when complete.
Re-running the script skips completed files and resumes partial downloads when
the server supports HTTP Range requests.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_URL = "https://web.corral.tacc.utexas.edu/texasrobotics/web_CODa/"
DEFAULT_DESTINATION = Path(__file__).resolve().parent / "CODa"
USER_AGENT = "CODa-dataset-downloader/1.0"
CHUNK_SIZE = 8 * 1024 * 1024


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() != "a":
            return
        for name, value in attrs:
            if name.casefold() == "href" and value:
                self.links.append(value)
                break


@dataclass(frozen=True)
class Download:
    url: str
    relative_path: Path


class Progress:
    def __init__(self, file_count: int) -> None:
        self.file_count = file_count
        self.finished = 0
        self.skipped = 0
        self.downloaded = 0
        self.failed = 0
        self.started_at = time.monotonic()
        self.last_printed_at = 0.0
        self.lock = threading.Lock()

    def add_bytes(self, byte_count: int) -> None:
        with self.lock:
            self.downloaded += byte_count
            now = time.monotonic()
            if now - self.last_printed_at >= 2:
                self.last_printed_at = now
                elapsed = max(now - self.started_at, 0.001)
                speed = human_size(self.downloaded / elapsed) + "/s"
                print(
                    f"\r进度: {self.finished + self.skipped}/{self.file_count} 个文件, "
                    f"本次下载 {human_size(self.downloaded)}, {speed}",
                    end="",
                    flush=True,
                )

    def mark(self, result: str) -> None:
        with self.lock:
            if result == "downloaded":
                self.finished += 1
            elif result == "skipped":
                self.skipped += 1
            else:
                self.failed += 1


def human_size(value: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def normalize_root_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("源地址必须是有效的 HTTP(S) URL")
    path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def request_bytes(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def retry(operation, retries: int, description: str):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return operation()
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt == retries:
                break
            delay = min(2 ** (attempt - 1), 30)
            print(
                f"\n{description}失败（第 {attempt}/{retries} 次）：{error}；"
                f"{delay} 秒后重试",
                file=sys.stderr,
            )
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def relative_path_for_url(url: str, root_url: str) -> Path | None:
    parsed = urlsplit(url)
    root = urlsplit(root_url)
    if parsed.scheme != root.scheme or parsed.netloc != root.netloc:
        return None
    if not parsed.path.startswith(root.path):
        return None

    encoded_relative = parsed.path[len(root.path) :]
    if not encoded_relative:
        return Path()

    decoded_parts: list[str] = []
    for encoded_part in PurePosixPath(encoded_relative).parts:
        part = unquote(encoded_part)
        if part in {"", ".", ".."} or "/" in part or "\\" in part or "\x00" in part:
            return None
        decoded_parts.append(part)
    return Path(*decoded_parts)


def discover_files(
    root_url: str, destination: Path, timeout: float, retries: int
) -> list[Download]:
    pending = deque([root_url])
    visited_directories: set[str] = set()
    files: dict[str, Download] = {}

    while pending:
        directory_url = pending.popleft()
        if directory_url in visited_directories:
            continue
        visited_directories.add(directory_url)
        relative_directory = relative_path_for_url(directory_url, root_url)
        shown_directory = str(relative_directory or Path("."))
        print(f"扫描目录: {shown_directory}")

        page = retry(
            lambda: request_bytes(directory_url, timeout),
            retries,
            f"读取目录 {directory_url}",
        )
        parser = LinkParser()
        parser.feed(page.decode("utf-8", errors="replace"))

        for href in parser.links:
            joined = urljoin(directory_url, href)
            parsed = urlsplit(joined)
            clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            relative_path = relative_path_for_url(clean_url, root_url)
            if relative_path is None or not relative_path.parts:
                continue

            if parsed.path.endswith("/"):
                if clean_url not in visited_directories:
                    pending.append(clean_url)
                (destination / relative_path).mkdir(parents=True, exist_ok=True)
            else:
                files.setdefault(
                    clean_url,
                    Download(url=clean_url, relative_path=relative_path),
                )

    return sorted(files.values(), key=lambda item: str(item.relative_path))


def download_once(
    item: Download,
    destination: Path,
    timeout: float,
    progress: Progress,
) -> str:
    target = destination / item.relative_path
    partial = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.is_file():
        return "skipped"
    if target.exists():
        raise OSError(f"目标路径存在但不是普通文件: {target}")

    existing_size = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing_size:
        headers["Range"] = f"bytes={existing_size}-"

    request = Request(item.url, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        if error.code == 416 and existing_size:
            content_range = error.headers.get("Content-Range", "")
            if content_range == f"bytes */{existing_size}":
                os.replace(partial, target)
                return "downloaded"
        raise

    with response:
        status = getattr(response, "status", response.getcode())
        append = existing_size > 0 and status == 206
        if append:
            content_range = response.headers.get("Content-Range", "")
            if not content_range.startswith(f"bytes {existing_size}-"):
                raise OSError(
                    f"服务器返回了不匹配的 Content-Range: {content_range!r}"
                )
        mode = "ab" if append else "wb"
        expected = response.headers.get("Content-Length")
        expected_bytes = int(expected) if expected and expected.isdigit() else None
        received = 0
        with partial.open(mode) as output:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                progress.add_bytes(len(chunk))

        if expected_bytes is not None and received != expected_bytes:
            raise OSError(
                f"响应不完整：应收到 {expected_bytes} 字节，实际收到 {received} 字节"
            )

    os.replace(partial, target)
    return "downloaded"


def download_with_retries(
    item: Download,
    destination: Path,
    timeout: float,
    retries: int,
    progress: Progress,
) -> tuple[Download, str, Exception | None]:
    try:
        result = retry(
            lambda: download_once(item, destination, timeout, progress),
            retries,
            f"下载 {item.relative_path}",
        )
        progress.mark(result)
        return item, result, None
    except Exception as error:
        progress.mark("failed")
        return item, "failed", error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="递归下载 CODa 数据集，支持断点续传。"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="目录索引根 URL")
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help=f"保存目录（默认：{DEFAULT_DESTINATION}）",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="并行下载数（默认：3）",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="每个请求的最大尝试次数（默认：5）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="HTTP 连接/读取超时秒数（默认：60）",
    )
    args = parser.parse_args()
    if args.workers < 1 or args.retries < 1 or args.timeout <= 0:
        parser.error("--workers、--retries 和 --timeout 必须大于 0")
    return args


def main() -> int:
    args = parse_args()
    try:
        root_url = normalize_root_url(args.url)
    except ValueError as error:
        print(f"参数错误: {error}", file=sys.stderr)
        return 2

    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    print(f"源地址: {root_url}")
    print(f"保存到: {destination}")
    print("正在扫描远端目录……")

    try:
        files = discover_files(
            root_url, destination, args.timeout, args.retries
        )
    except Exception as error:
        print(f"\n扫描失败: {error}", file=sys.stderr)
        return 1

    print(f"扫描完成，共发现 {len(files)} 个文件。")
    if not files:
        return 0

    progress = Progress(len(files))
    failures: list[tuple[Download, Exception]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        futures = [
            executor.submit(
                download_with_retries,
                item,
                destination,
                args.timeout,
                args.retries,
                progress,
            )
            for item in files
        ]
        for future in concurrent.futures.as_completed(futures):
            item, result, error = future.result()
            if result == "failed" and error is not None:
                failures.append((item, error))
                print(f"\n最终失败: {item.relative_path}: {error}", file=sys.stderr)

    elapsed = max(time.monotonic() - progress.started_at, 0.001)
    print(
        f"\n完成：下载 {progress.finished}，跳过 {progress.skipped}，"
        f"失败 {progress.failed}；本次传输 {human_size(progress.downloaded)}，"
        f"耗时 {elapsed / 3600:.2f} 小时。"
    )
    if failures:
        print("重新运行同一命令可续传失败文件。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
