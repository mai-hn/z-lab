from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.drive.app import create_app as create_drive_app
from backend.drive.config import Settings as DriveSettings
from backend.model_checker import router as model_checker_router
from backend.registry import PROJECTS, public_projects

DATA_ROOT = Path(os.getenv("Z_LAB_DATA_ROOT", "./data")).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)

# DeepRouter constructs its SQLite store at import time.
os.environ.setdefault("DEEPL_ROUTER_DB", str(DATA_ROOT / "router" / "router.db"))
from backend.deepl_router.app import (  # noqa: E402
    app as deepl_router_app,
    translate_deepl,
    translate_json,
    usage,
)

app = FastAPI(
    title="Z-Lab API",
    version="1.0.0",
    description="Unified Python API for Modal Drive, DeepRouter and AI Model Checker.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
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

drive_settings = DriveSettings(
    local_data_root=DATA_ROOT / "drive",
    storage_backend=os.getenv("DRIVE_STORAGE_BACKEND", "auto"),
    api_prefix="",
)
drive_app = create_drive_app(drive_settings)

app.mount("/api/drive", drive_app, name="modal-drive")
app.mount("/api/router", deepl_router_app, name="deepl-router")
app.include_router(model_checker_router)

# Preserve the original public DeepRouter contract for existing clients.
app.add_api_route("/translate", translate_json, methods=["POST"], tags=["DeepRouter compatibility"])
app.add_api_route("/v2/translate", translate_deepl, methods=["POST"], tags=["DeepRouter compatibility"])
app.add_api_route("/v2/usage", usage, methods=["GET"], tags=["DeepRouter compatibility"])


@app.get("/api/health", tags=["System"])
def health() -> dict:
    return {
        "status": "ok",
        "name": "Z-Lab",
        "projects": [{"id": project.id, "status": project.status} for project in PROJECTS],
    }


@app.get("/api/projects", tags=["System"])
def projects() -> list[dict]:
    return public_projects()
