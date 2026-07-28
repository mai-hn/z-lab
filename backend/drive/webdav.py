from __future__ import annotations

import hashlib
from datetime import timezone
from email.utils import format_datetime
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from backend.drive.config import Settings
from backend.drive.deps import DbSession, require_token
from backend.drive.models import DavProperty, FileNode, NodeType
from backend.drive.routers.download import download_file, head_file
from backend.drive.schemas import ConflictPolicy
from backend.drive.services.fs import FSError, FileService
from backend.drive.utils import new_id, sanitize_filename

DAV = "DAV:"
ROOT_KEY = "__root__"
DAV_METHODS = "OPTIONS, PROPFIND, GET, HEAD, PUT, MKCOL, DELETE, MOVE, COPY, PROPPATCH"
DAV_HEADERS = {
    "DAV": "1, 2",
    "MS-Author-Via": "DAV",
    "Allow": DAV_METHODS,
}

ET.register_namespace("D", DAV)


def _http_error(error: FSError) -> HTTPException:
    return HTTPException(error.status, error.message)


def _virtual_path(path: str) -> str:
    decoded = unquote(path).strip()
    parts = [part for part in PurePosixPath(f"/{decoded.lstrip('/')}").parts if part != "/"]
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(400, "Invalid WebDAV path")
    return "/" + "/".join(parts) if parts else "/"


def _parent_and_name(path: str) -> tuple[str, str]:
    if path == "/":
        raise HTTPException(403, "The WebDAV root cannot be modified")
    pure = PurePosixPath(path)
    name = sanitize_filename(pure.name)
    parent = str(pure.parent)
    return (parent if parent.startswith("/") else f"/{parent}", name)


def _destination_path(request: Request) -> str:
    destination = request.headers.get("destination")
    if not destination:
        raise HTTPException(400, "Destination header is required")
    parsed = urlparse(destination)
    target = unquote(parsed.path or destination)
    if target == "/dav":
        return "/"
    if not target.startswith("/dav/"):
        raise HTTPException(502, "Destination must use the same /dav service")
    return _virtual_path(target[5:])


def _find_optional(fs: FileService, path: str) -> FileNode | None:
    try:
        return fs.resolve_path(path)
    except FSError as error:
        if error.status == 404:
            return None
        raise _http_error(error) from error


def _node_key(node: FileNode | None) -> str:
    return node.id if node is not None else ROOT_KEY


def _etag(node: FileNode | None) -> str:
    if node is None:
        return 'W/"z-lab-dav-root"'
    if node.sha256:
        return f'"{node.sha256}"'
    stamp = int(node.modified_at.replace(tzinfo=timezone.utc).timestamp())
    return f'W/"{node.id}-{stamp}"'


def _http_date(node: FileNode | None) -> str:
    value = node.modified_at if node is not None else None
    if value is None:
        from datetime import datetime

        value = datetime(1970, 1, 1)
    return format_datetime(value.replace(tzinfo=timezone.utc), usegmt=True)


def _href(fs: FileService, node: FileNode | None) -> str:
    path = fs.node_path(node) if node is not None else "/"
    href = f"/dav{quote(path, safe='/')}"
    if (node is None or node.node_type == NodeType.directory) and not href.endswith("/"):
        href += "/"
    return href


def _custom_properties(db: DbSession, node: FileNode | None) -> list[DavProperty]:
    return list(
        db.execute(
            select(DavProperty)
            .where(DavProperty.node_key == _node_key(node))
            .order_by(DavProperty.namespace, DavProperty.name)
        ).scalars()
    )


def _append_prop_response(
    multistatus: ET.Element,
    fs: FileService,
    db: DbSession,
    node: FileNode | None,
) -> None:
    response = ET.SubElement(multistatus, f"{{{DAV}}}response")
    ET.SubElement(response, f"{{{DAV}}}href").text = _href(fs, node)
    propstat = ET.SubElement(response, f"{{{DAV}}}propstat")
    prop = ET.SubElement(propstat, f"{{{DAV}}}prop")

    display_name = "Z-Lab" if node is None else node.name
    ET.SubElement(prop, f"{{{DAV}}}displayname").text = display_name
    resource_type = ET.SubElement(prop, f"{{{DAV}}}resourcetype")
    if node is None or node.node_type == NodeType.directory:
        ET.SubElement(resource_type, f"{{{DAV}}}collection")
    ET.SubElement(prop, f"{{{DAV}}}getcontentlength").text = str(
        0 if node is None else int(node.size or 0)
    )
    ET.SubElement(prop, f"{{{DAV}}}getcontenttype").text = (
        "httpd/unix-directory"
        if node is None or node.node_type == NodeType.directory
        else node.mime_type or "application/octet-stream"
    )
    ET.SubElement(prop, f"{{{DAV}}}getetag").text = _etag(node)
    ET.SubElement(prop, f"{{{DAV}}}getlastmodified").text = _http_date(node)
    if node is not None:
        ET.SubElement(prop, f"{{{DAV}}}creationdate").text = (
            node.created_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        )
    for item in _custom_properties(db, node):
        ET.SubElement(prop, f"{{{item.namespace}}}{item.name}").text = item.value
    ET.SubElement(propstat, f"{{{DAV}}}status").text = "HTTP/1.1 200 OK"


def _xml_response(root: ET.Element, status_code: int = 207) -> Response:
    return Response(
        ET.tostring(root, encoding="utf-8", xml_declaration=True),
        status_code=status_code,
        media_type="application/xml; charset=utf-8",
        headers=DAV_HEADERS,
    )


def _propfind(path: str, request: Request, db: DbSession, fs: FileService) -> Response:
    try:
        node = fs.resolve_path(path)
    except FSError as error:
        raise _http_error(error) from error

    multistatus = ET.Element(f"{{{DAV}}}multistatus")
    _append_prop_response(multistatus, fs, db, node)
    depth = request.headers.get("depth", "1").lower()
    if depth != "0" and (node is None or node.node_type == NodeType.directory):
        try:
            _, children = fs.list_directory(path=path)
        except FSError as error:
            raise _http_error(error) from error
        for child in children:
            _append_prop_response(multistatus, fs, db, child)
    response = _xml_response(multistatus)
    if depth == "infinity":
        response.headers["X-WebDAV-Depth-Limited"] = "1"
    return response


async def _put(
    path: str,
    request: Request,
    db: DbSession,
    fs: FileService,
    storage,
    settings: Settings,
) -> Response:
    parent_path, name = _parent_and_name(path)
    existing = _find_optional(fs, path)
    if existing is not None and existing.node_type == NodeType.directory:
        raise HTTPException(405, "Cannot PUT content to a directory")
    try:
        parent_id = fs.resolve_parent(path=parent_path)
    except FSError as error:
        raise _http_error(error) from error

    base_key = new_id().replace("-", "")
    chunk_size = settings.large_file_threshold
    chunks: list[dict] = []
    written_keys: list[str] = []
    buffer = bytearray()
    total_size = 0
    whole_hash = hashlib.sha256()

    def flush(data: bytes) -> None:
        nonlocal total_size
        index = len(chunks)
        key = f"{base_key}-{index:06d}"
        storage.write_bytes_atomic(key, data)
        written_keys.append(key)
        whole_hash.update(data)
        total_size += len(data)
        chunks.append(
            {
                "index": index,
                "storage_key": key,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    try:
        async for piece in request.stream():
            if not piece:
                continue
            buffer.extend(piece)
            while len(buffer) >= chunk_size:
                flush(bytes(buffer[:chunk_size]))
                del buffer[:chunk_size]
        if buffer or not chunks:
            flush(bytes(buffer))
        digest = whole_hash.hexdigest()
        content = fs.create_content_manifest(
            chunks=chunks,
            total_size=total_size,
            sha256=digest,
            chunk_size=chunk_size,
            backend=storage.backend_name(),
        )
        fs.register_file(
            name=name,
            storage_key=chunks[0]["storage_key"],
            size=total_size,
            sha256=digest,
            content_id=content.id,
            parent_id=parent_id,
            conflict=ConflictPolicy.overwrite,
            mime_type=request.headers.get("content-type"),
        )
    except Exception:
        for key in written_keys:
            try:
                storage.delete_file(key)
            except Exception:
                pass
        raise

    return Response(
        status_code=204 if existing is not None else 201,
        headers={"ETag": f'"{digest}"', **DAV_HEADERS},
    )


def _mkcol(path: str, db: DbSession, fs: FileService) -> Response:
    del db
    parent_path, name = _parent_and_name(path)
    if _find_optional(fs, path) is not None:
        raise HTTPException(405, "Collection already exists")
    try:
        fs.create_directory(name=name, path=parent_path)
    except FSError as error:
        raise _http_error(error) from error
    return Response(status_code=201, headers={"Location": f"/dav{quote(path)}", **DAV_HEADERS})


def _delete(path: str, fs: FileService) -> Response:
    if path == "/":
        raise HTTPException(403, "The WebDAV root cannot be deleted")
    try:
        node = fs.resolve_path(path)
        assert node is not None
        fs.delete_node(node.id)
    except FSError as error:
        raise _http_error(error) from error
    return Response(status_code=204, headers=DAV_HEADERS)


def _prepare_destination(
    source: FileNode,
    destination: str,
    request: Request,
    fs: FileService,
) -> tuple[str, str, bool]:
    parent_path, name = _parent_and_name(destination)
    try:
        target_parent_id = fs.resolve_parent(path=parent_path)
    except FSError as error:
        raise _http_error(error) from error
    if source.node_type == NodeType.directory and target_parent_id is not None:
        if target_parent_id == source.id or fs._is_descendant(target_parent_id, source.id):
            raise HTTPException(409, "Cannot copy or move a directory into itself")
    existing = _find_optional(fs, destination)
    if existing is source:
        return parent_path, name, True
    if existing is not None:
        if request.headers.get("overwrite", "T").upper() != "T":
            raise HTTPException(412, "Destination exists and Overwrite is false")
        if source.node_type == NodeType.directory and fs._is_descendant(source.id, existing.id):
            raise HTTPException(409, "Destination contains the source")
        try:
            fs.delete_node(existing.id)
        except FSError as error:
            raise _http_error(error) from error
    return parent_path, name, existing is not None


def _copy_properties(db: DbSession, source: FileNode, destination: FileNode) -> None:
    for item in _custom_properties(db, source):
        db.add(
            DavProperty(
                node_key=destination.id,
                namespace=item.namespace,
                name=item.name,
                value=item.value,
            )
        )
    db.flush()


def _move_or_copy(
    method: str,
    path: str,
    request: Request,
    db: DbSession,
    fs: FileService,
) -> Response:
    if path == "/":
        raise HTTPException(403, "The WebDAV root cannot be moved or copied")
    try:
        source = fs.resolve_path(path)
        assert source is not None
    except FSError as error:
        raise _http_error(error) from error
    destination = _destination_path(request)
    if destination == path:
        return Response(status_code=204, headers=DAV_HEADERS)
    parent_path, name, overwritten = _prepare_destination(source, destination, request, fs)
    try:
        if method == "MOVE":
            moved = fs.move_node(source.id, target_path=parent_path)
            fs.rename_node(moved.id, name)
        else:
            copied = fs.copy_node(source.id, target_path=parent_path, new_name=name)
            _copy_properties(db, source, copied)
    except FSError as error:
        raise _http_error(error) from error
    return Response(status_code=204 if overwritten else 201, headers=DAV_HEADERS)


def _split_xml_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, name = tag[1:].split("}", 1)
        return namespace, name
    return "", tag


async def _proppatch(path: str, request: Request, db: DbSession, fs: FileService) -> Response:
    try:
        node = fs.resolve_path(path)
    except FSError as error:
        raise _http_error(error) from error
    body = await request.body()
    try:
        document = ET.fromstring(body)
    except ET.ParseError as error:
        raise HTTPException(400, f"Invalid PROPPATCH XML: {error}") from error

    changed: list[tuple[str, str]] = []
    node_key = _node_key(node)
    for operation in document:
        action = _split_xml_tag(operation.tag)[1].lower()
        prop_container = operation.find(f"{{{DAV}}}prop")
        if prop_container is None:
            continue
        for element in prop_container:
            namespace, name = _split_xml_tag(element.tag)
            existing = db.execute(
                select(DavProperty).where(
                    DavProperty.node_key == node_key,
                    DavProperty.namespace == namespace,
                    DavProperty.name == name,
                )
            ).scalar_one_or_none()
            if action == "remove":
                if existing is not None:
                    db.delete(existing)
            elif existing is None:
                db.add(
                    DavProperty(
                        node_key=node_key,
                        namespace=namespace,
                        name=name,
                        value=element.text or "",
                    )
                )
            else:
                existing.value = element.text or ""
            changed.append((namespace, name))
    db.flush()

    multistatus = ET.Element(f"{{{DAV}}}multistatus")
    response = ET.SubElement(multistatus, f"{{{DAV}}}response")
    ET.SubElement(response, f"{{{DAV}}}href").text = _href(fs, node)
    propstat = ET.SubElement(response, f"{{{DAV}}}propstat")
    prop = ET.SubElement(propstat, f"{{{DAV}}}prop")
    for namespace, name in changed:
        ET.SubElement(prop, f"{{{namespace}}}{name}")
    ET.SubElement(propstat, f"{{{DAV}}}status").text = "HTTP/1.1 200 OK"
    return _xml_response(multistatus)


def create_webdav_router(storage, settings: Settings) -> APIRouter:
    router = APIRouter(
        tags=["WebDAV"],
        dependencies=[Depends(require_token)],
    )

    async def endpoint(request: Request, db: DbSession, path: str = ""):
        virtual_path = _virtual_path(path)
        fs = FileService(db, storage)
        method = request.method.upper()
        if method == "OPTIONS":
            return Response(status_code=200, headers=DAV_HEADERS)
        if method == "PROPFIND":
            return _propfind(virtual_path, request, db, fs)
        if method == "GET":
            try:
                node = fs.resolve_path(virtual_path)
                if node is None or node.node_type == NodeType.directory:
                    raise HTTPException(405, "GET is only available for files")
                response = download_file(node.id, request, db, storage)
                response.headers.update(
                    {
                        "ETag": _etag(node),
                        "Last-Modified": _http_date(node),
                        **DAV_HEADERS,
                    }
                )
                return response
            except FSError as error:
                raise _http_error(error) from error
        if method == "HEAD":
            try:
                node = fs.resolve_path(virtual_path)
                if node is None or node.node_type == NodeType.directory:
                    return Response(
                        status_code=200,
                        headers={
                            "ETag": _etag(node),
                            "Last-Modified": _http_date(node),
                            **DAV_HEADERS,
                        },
                    )
                response = head_file(node.id, db, storage)
                response.headers.update(
                    {
                        "ETag": _etag(node),
                        "Last-Modified": _http_date(node),
                        **DAV_HEADERS,
                    }
                )
                return response
            except FSError as error:
                raise _http_error(error) from error
        if method == "PUT":
            return await _put(virtual_path, request, db, fs, storage, settings)
        if method == "MKCOL":
            return _mkcol(virtual_path, db, fs)
        if method == "DELETE":
            return _delete(virtual_path, fs)
        if method in {"MOVE", "COPY"}:
            return _move_or_copy(method, virtual_path, request, db, fs)
        if method == "PROPPATCH":
            return await _proppatch(virtual_path, request, db, fs)
        raise HTTPException(405, headers={"Allow": DAV_METHODS})

    methods = [
        "OPTIONS",
        "PROPFIND",
        "GET",
        "HEAD",
        "PUT",
        "MKCOL",
        "DELETE",
        "MOVE",
        "COPY",
        "PROPPATCH",
    ]
    router.add_api_route("/dav", endpoint, methods=methods, include_in_schema=False)
    router.add_api_route("/dav/{path:path}", endpoint, methods=methods, include_in_schema=False)
    return router
