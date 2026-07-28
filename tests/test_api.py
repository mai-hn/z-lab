from __future__ import annotations

import os
import tempfile

os.environ["Z_LAB_DATA_ROOT"] = tempfile.mkdtemp(prefix="z-lab-test-")
os.environ["DRIVE_STORAGE_BACKEND"] = "local"

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.drive.app import find_frontend_dist  # noqa: E402


client = TestClient(app)


def test_inaccessible_legacy_frontend_path_does_not_block_api() -> None:
    class InaccessiblePath:
        def is_dir(self) -> bool:
            raise PermissionError("blocked by container user")

        def __str__(self) -> str:
            return "/root/frontend/dist"

    assert find_frontend_dist([InaccessiblePath()]) is None  # type: ignore[list-item]


def test_health_and_registry() -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert {item["id"] for item in health.json()["projects"]} == {
        "modal-drive",
        "deepl-router",
        "ai-model-checker",
    }
    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert all(item["api_prefix"].startswith("/api/") for item in projects.json())


def test_deepl_router_compatibility_routes() -> None:
    dashboard = client.get("/api/router/api/dashboard")
    assert dashboard.status_code == 200
    usage = client.get("/v2/usage")
    assert usage.status_code == 200
    assert usage.json()["router"] == "DeepRouter"


def test_model_checker_validates_credentials() -> None:
    response = client.post("/api/models/list", json={})
    assert response.status_code == 422


def test_chunked_upload_and_ordered_download() -> None:
    content = (b"0123456789abcdef" * (9 * 1024 * 1024 // 16 + 1))[: 9 * 1024 * 1024]
    create = client.post(
        "/api/drive/uploads",
        json={
            "filename": "large-test.bin",
            "total_size": len(content),
            "path": "/",
            "chunk_size": 4 * 1024 * 1024,
            "conflict": "rename",
        },
    )
    assert create.status_code == 201, create.text
    session = create.json()
    for index in range(session["total_chunks"]):
        start = index * session["chunk_size"]
        part = content[start : start + session["chunk_size"]]
        uploaded = client.put(
            f"/api/drive/uploads/{session['id']}/parts/{index}",
            files={"file": ("part", part, "application/octet-stream")},
        )
        assert uploaded.status_code == 200, uploaded.text
    complete = client.post(f"/api/drive/uploads/{session['id']}/complete", json={})
    assert complete.status_code == 200, complete.text
    node = complete.json()
    assert node["size"] == len(content)
    assert node["chunk_count"] == 3

    download = client.get(f"/api/drive/files/{node['id']}/content")
    assert download.status_code == 200
    assert int(download.headers["content-length"]) == len(content)
    assert download.headers["x-file-size"] == str(len(content))
    assert download.headers["x-chunk-count"] == "3"
    assert download.content == content

    partial = client.get(
        f"/api/drive/files/{node['id']}/content",
        headers={"Range": "bytes=4194296-4194312"},
    )
    assert partial.status_code == 206
    assert partial.content == content[4194296:4194313]

    deleted = client.delete(f"/api/drive/files/{node['id']}")
    assert deleted.status_code == 204


def test_webdav_full_file_lifecycle_and_custom_properties() -> None:
    options = client.request("OPTIONS", "/dav")
    assert options.status_code == 200
    assert options.headers["dav"] == "1, 2"
    assert {
        "PROPFIND",
        "PUT",
        "MKCOL",
        "MOVE",
        "COPY",
        "PROPPATCH",
    }.issubset(set(options.headers["allow"].split(", ")))

    created = client.request("MKCOL", "/dav/documents")
    assert created.status_code == 201, created.text

    content = b"WebDAV from Z-Lab"
    uploaded = client.put(
        "/dav/documents/hello.txt",
        content=content,
        headers={"Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 201, uploaded.text

    head = client.head("/dav/documents/hello.txt")
    assert head.status_code == 200
    assert int(head.headers["content-length"]) == len(content)
    assert head.headers["etag"]
    assert head.headers["last-modified"]

    downloaded = client.get("/dav/documents/hello.txt")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert downloaded.headers["x-file-size"] == str(len(content))

    properties = client.request(
        "PROPPATCH",
        "/dav/documents/hello.txt",
        content=(
            '<?xml version="1.0"?>'
            '<D:propertyupdate xmlns:D="DAV:" xmlns:Z="urn:z-lab">'
            "<D:set><D:prop><Z:favorite>yes</Z:favorite></D:prop></D:set>"
            "</D:propertyupdate>"
        ),
        headers={"Content-Type": "application/xml"},
    )
    assert properties.status_code == 207, properties.text

    listing = client.request("PROPFIND", "/dav/documents", headers={"Depth": "1"})
    assert listing.status_code == 207
    assert b"hello.txt" in listing.content
    assert b"favorite" in listing.content
    assert b"yes" in listing.content

    copied = client.request(
        "COPY",
        "/dav/documents/hello.txt",
        headers={"Destination": "/dav/documents/copy.txt"},
    )
    assert copied.status_code == 201, copied.text
    assert client.get("/dav/documents/copy.txt").content == content

    moved = client.request(
        "MOVE",
        "/dav/documents/hello.txt",
        headers={"Destination": "/dav/moved.txt"},
    )
    assert moved.status_code == 201, moved.text
    assert client.get("/dav/documents/hello.txt").status_code == 404
    assert client.get("/dav/moved.txt").content == content

    assert client.delete("/dav/documents/copy.txt").status_code == 204
    assert client.delete("/dav/documents").status_code == 204
    assert client.delete("/dav/moved.txt").status_code == 204


def test_webdav_put_chunks_files_larger_than_eight_mib() -> None:
    content = b"z" * (8 * 1024 * 1024 + 1)
    uploaded = client.put("/dav/large-dav.bin", content=content)
    assert uploaded.status_code == 201, uploaded.text

    listing = client.get("/api/drive/files", params={"path": "/"})
    assert listing.status_code == 200
    node = next(item for item in listing.json()["items"] if item["name"] == "large-dav.bin")
    assert node["size"] == len(content)
    assert node["chunk_count"] == 2
    assert client.get("/dav/large-dav.bin").content == content
    assert client.delete("/dav/large-dav.bin").status_code == 204
