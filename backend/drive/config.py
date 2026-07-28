from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

StorageBackend = Literal["auto", "local", "modal"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIVE_", env_file=".env", extra="ignore")

    # Where local metadata + upload temps live (always on this machine)
    local_data_root: Path = Path(os.environ.get("DRIVE_LOCAL_DATA_ROOT", "./data"))

    # Deprecated alias — treated as local_data_root if set
    storage_root: Path | None = None

    # auto: use Modal Volume if credentials work, else local disk
    storage_backend: StorageBackend = Field(default="auto")

    modal_volume_name: str = "modal-drive-storage"
    modal_app_name: str = "modal-drive"
    modal_environment: str | None = None
    # Modal Dict for offline task progress (no always-on web service)
    modal_task_dict: str = "modal-drive-tasks"
    # A deployed, scale-to-zero Modal ASGI endpoint used for direct downloads.
    modal_download_url: str = ""
    # Shared with the Modal Secret named ``modal-drive-download``.
    download_signing_key: str = ""
    download_link_ttl_seconds: int = Field(default=300, ge=30, le=3600)

    # SQLite metadata (always local)
    db_name: str = "meta/drive.db"

    # Upload defaults
    default_chunk_size: int = 8 * 1024 * 1024
    large_file_threshold: int = 8 * 1024 * 1024
    max_upload_size: int = 50 * 1024 * 1024 * 1024
    upload_expire_hours: int = 48
    simple_upload_max: int = 100 * 1024 * 1024

    # Offline
    offline_max_concurrent: int = 3
    offline_timeout_hours: int = 12

    # API
    api_prefix: str = "/api"
    cors_origins: str = "*"
    api_token: str = ""

    def resolved_local_root(self) -> Path:
        if self.storage_root is not None:
            return Path(self.storage_root)
        return Path(self.local_data_root)

    @property
    def files_dir(self) -> Path:
        """Local files dir (only used by local backend)."""
        return self.resolved_local_root() / "files"

    @property
    def uploads_dir(self) -> Path:
        return self.resolved_local_root() / "uploads"

    @property
    def offline_dir(self) -> Path:
        return self.resolved_local_root() / "offline"

    @property
    def tmp_dir(self) -> Path:
        return self.resolved_local_root() / "tmp"

    @property
    def db_path(self) -> Path:
        p = Path(self.db_name)
        if p.is_absolute():
            return p
        return self.resolved_local_root() / p

    def ensure_dirs(self) -> None:
        for d in (
            self.resolved_local_root(),
            self.uploads_dir,
            self.offline_dir,
            self.tmp_dir,
            self.db_path.parent,
        ):
            d.mkdir(parents=True, exist_ok=True)
        # local backend also needs files/
        if self.storage_backend == "local":
            self.files_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
