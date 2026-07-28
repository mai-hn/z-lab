"""Modal client helpers — Volume I/O without a running web service.

Upload/download use Volume SDK (batch_upload / read_file).
Heavy work (offline download) spawns Functions on demand only.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from backend.drive.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ModalNotConfigured(RuntimeError):
    pass


def modal_available(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    try:
        import modal  # noqa: F401

        if not _has_modal_credentials():
            return False
        get_volume(settings)
        return True
    except Exception as e:
        logger.debug("Modal not available: %s", e)
        return False


@lru_cache(maxsize=4)
def _volume_cached(name: str, environment: str | None) -> Any:
    import modal

    kwargs: dict[str, Any] = {"create_if_missing": True}
    if environment:
        kwargs["environment_name"] = environment
    # Lazy handle only — no listdir/hydrate here (avoids sync-in-async warnings
    # during FastAPI startup). Real I/O happens on upload/download.
    return modal.Volume.from_name(name, **kwargs)


def get_volume(settings: Settings | None = None):
    settings = settings or get_settings()
    try:
        return _volume_cached(settings.modal_volume_name, settings.modal_environment)
    except Exception as e:
        raise ModalNotConfigured(
            f"Cannot access Modal Volume '{settings.modal_volume_name}'. "
            f"Run `uv run modal setup` first. ({e})"
        ) from e


def clear_volume_cache() -> None:
    _volume_cached.cache_clear()


def _has_modal_credentials() -> bool:
    import os
    from pathlib import Path

    if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"):
        return True
    return Path.home().joinpath(".modal.toml").is_file()


def get_task_dict(settings: Settings | None = None):
    """Shared progress dict — billed only as storage, no container."""
    import modal

    settings = settings or get_settings()
    kwargs: dict[str, Any] = {"create_if_missing": True}
    if settings.modal_environment:
        kwargs["environment_name"] = settings.modal_environment
    return modal.Dict.from_name(settings.modal_task_dict, **kwargs)


def get_offline_function(settings: Settings | None = None):
    """Lookup deployed offline worker. Spawning it starts compute only then."""
    import modal

    settings = settings or get_settings()
    kwargs: dict[str, Any] = {}
    if settings.modal_environment:
        kwargs["environment_name"] = settings.modal_environment
    try:
        return modal.Function.from_name(settings.modal_app_name, "offline_worker", **kwargs)
    except Exception as e:
        raise ModalNotConfigured(
            f"Modal function '{settings.modal_app_name}/offline_worker' not found. "
            f"Deploy once with: uv run modal deploy modal_app.py ({e})"
        ) from e


def resolve_backend(settings: Settings | None = None) -> str:
    """Return 'modal' or 'local'."""
    settings = settings or get_settings()
    mode = settings.storage_backend
    if mode == "local":
        return "local"
    if mode == "modal":
        if not modal_available(settings):
            raise ModalNotConfigured(
                "DRIVE_STORAGE_BACKEND=modal but Modal is not configured. Run `uv run modal setup`."
            )
        return "modal"
    # auto
    if modal_available(settings):
        return "modal"
    return "local"


def volume_file_path(storage_key: str) -> str:
    shard = storage_key[:2]
    return f"files/{shard}/{storage_key}"


def volume_upload_chunk_path(upload_id: str, index: int) -> str:
    return f"uploads/{upload_id}/part_{index:06d}"
