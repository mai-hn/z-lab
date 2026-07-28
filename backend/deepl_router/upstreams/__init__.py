"""Upstream provider adapters.

新增供应商只需在本包内新建一个模块并用 @register 注册，无需改动其他文件。
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import (
    UPSTREAMS,
    QuotaResult,
    QuotaUnsupportedError,
    TranslationResult,
    Upstream,
    UpstreamError,
    UpstreamMeta,
    quota_exceeded,
    register,
)

for _module_info in pkgutil.iter_modules(__path__):
    if _module_info.name != "base":
        importlib.import_module(f"{__name__}.{_module_info.name}")

from .deepl import DeepLUpstream  # noqa: E402
from .deeplx import JsonTranslateUpstream  # noqa: E402
from .tencent import TencentCloudUpstream, tc3_sign  # noqa: E402
from .volcengine import VolcengineUpstream, volc_sign_v4  # noqa: E402
from .azure import AzureTranslatorUpstream  # noqa: E402
from .baidu import BaiduMTUpstream  # noqa: E402

KINDS: tuple[str, ...] = tuple(sorted(UPSTREAMS, key=lambda kind: UPSTREAMS[kind].meta.sort_order))

BATCH_ALIAS_MAP: dict[str, str] = {
    alias: upstream.meta.kind
    for upstream in UPSTREAMS.values()
    for alias in upstream.meta.batch_aliases
}

__all__ = [
    "UPSTREAMS",
    "KINDS",
    "BATCH_ALIAS_MAP",
    "QuotaResult",
    "QuotaUnsupportedError",
    "TranslationResult",
    "Upstream",
    "UpstreamError",
    "UpstreamMeta",
    "quota_exceeded",
    "register",
    "DeepLUpstream",
    "JsonTranslateUpstream",
    "TencentCloudUpstream",
    "VolcengineUpstream",
    "AzureTranslatorUpstream",
    "BaiduMTUpstream",
    "tc3_sign",
    "volc_sign_v4",
]
