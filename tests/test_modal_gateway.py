from __future__ import annotations

import time

import httpx
from fastapi.testclient import TestClient

import modal_app
from backend.drive.direct_download import sign_download


def test_modal_gateway_streams_ordered_chunks_and_ranges(
    monkeypatch,
    tmp_path,
) -> None:
    signing_key = "modal-gateway-test-key"
    node_id = "gateway-node"
    expires = int(time.time()) + 120
    signature = sign_download(node_id, expires, signing_key)
    first = b"first-"
    second = b"second"
    for storage_key, content in (("aa-key", first), ("bb-key", second)):
        path = tmp_path / "files" / storage_key[:2] / storage_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    manifest = {
        "version": 1,
        "node_id": node_id,
        "content_id": "content-1",
        "filename": "gateway.bin",
        "size": len(first) + len(second),
        "mime_type": "application/octet-stream",
        "etag": '"gateway-etag"',
        "last_modified": "Tue, 28 Jul 2026 00:00:00 GMT",
        "chunks": [
            {"index": 0, "storage_key": "aa-key", "size": len(first)},
            {"index": 1, "storage_key": "bb-key", "size": len(second)},
        ],
    }
    callback_calls: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return manifest

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            callback_calls.append({"url": url, **kwargs})
            return FakeResponse()

    class FakeVolume:
        def reload(self):
            return None

    monkeypatch.setenv("DRIVE_DOWNLOAD_SIGNING_KEY", signing_key)
    monkeypatch.setenv("Z_LAB_API_URL", "https://z-lab.example.com")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(modal_app, "STORAGE_MOUNT", str(tmp_path))
    monkeypatch.setattr(modal_app, "volume", FakeVolume())

    gateway = TestClient(modal_app.download_gateway.get_raw_f()())
    params = {"expires": expires, "signature": signature}

    full = gateway.get(f"/download/{node_id}", params=params)
    assert full.status_code == 200
    assert full.content == first + second
    assert full.headers["x-download-provider"] == "modal"
    assert full.headers["content-length"] == str(len(first) + len(second))

    ranged = gateway.get(
        f"/download/{node_id}",
        params=params,
        headers={"Range": "bytes=4-9"},
    )
    assert ranged.status_code == 206
    assert ranged.content == (first + second)[4:10]
    assert ranged.headers["content-range"] == f"bytes 4-9/{len(first) + len(second)}"

    head = gateway.head(f"/download/{node_id}", params=params)
    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(first) + len(second))
    assert len(callback_calls) == 1

    rejected = gateway.get(
        f"/download/{node_id}",
        params={"expires": expires, "signature": "invalid"},
    )
    assert rejected.status_code == 401
    assert len(callback_calls) == 1
