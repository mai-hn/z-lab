from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Literal

import httpx


class UpstreamError(RuntimeError):
    def __init__(self, message: str, *, request: dict[str, Any], response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.request = request
        self.response = response


class QuotaUnsupportedError(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"该上游类型不支持额度/余额查询: {kind}")
        self.kind = kind


@dataclass
class TranslationResult:
    text: str
    detected_source_language: str | None
    provider: str
    upstream_request: dict[str, Any] | None = None
    upstream_response: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] | None = None


@dataclass
class QuotaResult:
    type: str  # "characters" | "balance"
    used: int | None = None
    limit: int | None = None
    amount: float | None = None
    currency: str | None = None

    def to_json(self) -> dict[str, Any]:
        if self.type == "characters":
            return {"type": "characters", "used": self.used, "limit": self.limit}
        return {"type": "balance", "amount": self.amount, "currency": self.currency}


@dataclass(frozen=True)
class UpstreamMeta:
    kind: str
    label: str
    default_endpoint: str
    endpoint_help: str = ""
    key_label: str = "API Key / Token"
    key_placeholder: str = ""
    needs_secret: bool = False
    secret_label: str | None = None
    secret_placeholder: str | None = None
    needs_region: bool = False
    region_label: str | None = None
    region_placeholder: str | None = None
    quota_type: Literal["characters", "balance"] | None = None
    color: str = "#8054eb"
    sort_order: int = 100
    batch_aliases: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["batch_aliases"] = list(self.batch_aliases)
        return data


class Upstream(ABC):
    meta: ClassVar[UpstreamMeta]

    @property
    def kind(self) -> str:
        return self.meta.kind

    @abstractmethod
    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        raise NotImplementedError

    async def query_quota(self, client: httpx.AsyncClient, provider: dict[str, Any]) -> QuotaResult:
        raise QuotaUnsupportedError(self.meta.kind)

    @staticmethod
    def response_body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text[:2000]


UPSTREAMS: dict[str, "Upstream"] = {}


def register(upstream_cls_or_instance: type[Upstream] | Upstream) -> type[Upstream] | Upstream:
    """Register an upstream (class or pre-built instance) into UPSTREAMS by its meta.kind."""
    instance = upstream_cls_or_instance() if isinstance(upstream_cls_or_instance, type) else upstream_cls_or_instance
    UPSTREAMS[instance.meta.kind] = instance
    return upstream_cls_or_instance


def quota_exceeded(provider: dict[str, Any]) -> bool:
    quota = provider.get("quota")
    if isinstance(quota, str):
        try:
            quota = json.loads(quota)
        except ValueError:
            return False
    if not isinstance(quota, dict):
        return False
    user_limit = provider.get("quota_limit")
    if quota.get("type") == "characters":
        limits = [value for value in (quota.get("limit"), user_limit) if value]
        if not limits:
            return False
        used = quota.get("used") or 0
        return used >= min(limits)
    if quota.get("type") == "balance":
        amount = quota.get("amount")
        if user_limit is None or amount is None:
            return False
        return amount < user_limit
    return False
