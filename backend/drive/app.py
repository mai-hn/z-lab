from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.drive.config import Settings, get_settings
from backend.drive.database import init_db, reset_engine
from backend.drive.deps import require_token
from backend.drive.modal_util import resolve_backend
from backend.drive.routers import download, files, offline, search, stats, upload
from backend.drive.storage import create_storage

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    volume_commit: Callable[[], None] | None = None,
    spawn_offline_download: Callable[[str], None] | None = None,
    storage_backend: str | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()

    os.environ["DRIVE_LOCAL_DATA_ROOT"] = str(settings.resolved_local_root())
    get_settings.cache_clear()
    reset_engine()
    init_db()

    try:
        backend = storage_backend or resolve_backend(settings)
    except Exception as e:
        logger.warning("Falling back to local storage: %s", e)
        backend = "local"

    storage = create_storage(settings=settings, on_commit=volume_commit, backend=backend)

    app = FastAPI(
        title="Modal Drive",
        description="Local API + Modal Volume SDK; Modal Functions only for heavy jobs",
        version="0.2.0",
        dependencies=[Depends(require_token)],
    )
    app.state.settings = settings
    app.state.volume_commit = volume_commit
    app.state.spawn_offline_download = spawn_offline_download
    app.state.storage_backend = backend
    app.state.storage = storage

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins if origins != ["*"] else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Range",
            "Accept-Ranges",
            "Content-Length",
            "Content-Disposition",
            "X-File-Size",
            "X-Chunk-Count",
        ],
    )

    @app.on_event("startup")
    def _startup():
        settings.ensure_dirs()
        init_db()

    prefix = settings.api_prefix
    app.include_router(files.router, prefix=prefix)
    app.include_router(upload.router, prefix=prefix)
    app.include_router(download.router, prefix=prefix)
    app.include_router(search.router, prefix=prefix)
    app.include_router(offline.router, prefix=prefix)
    app.include_router(stats.router, prefix=prefix)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "storage_backend": backend,
            "local_data_root": str(settings.resolved_local_root()),
            "modal_volume": settings.modal_volume_name if backend == "modal" else None,
            "modal_app": settings.modal_app_name if backend == "modal" else None,
            "note": (
                "Uploads/downloads use Modal Volume SDK (no container). "
                "Offline download spawns Modal Function on demand."
                if backend == "modal"
                else "Local disk storage. Set DRIVE_STORAGE_BACKEND=modal after `modal setup`."
            ),
        }

    candidates = [
        Path(__file__).resolve().parent.parent / "frontend" / "dist",
        Path("/root/frontend/dist"),
    ]
    frontend_dist = next((p for p in candidates if p.exists()), None)
    if frontend_dist is not None:
        assets = frontend_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str = ""):
            if full_path.startswith("api") or full_path == "health":
                return {"detail": "Not found"}
            index = frontend_dist / "index.html"
            file_path = frontend_dist / full_path
            if full_path and file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(index)

    return app


def get_app() -> FastAPI:
    return create_app()


app = None


def __getattr__(name: str):
    global app
    if name == "app":
        if app is None:
            app = create_app()
        return app
    raise AttributeError(name)
