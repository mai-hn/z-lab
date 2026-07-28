from __future__ import annotations

import time
from typing import Any

import httpx

from .store import Store
from .upstreams import UPSTREAMS, TranslationResult, UpstreamError, quota_exceeded


class TranslationError(RuntimeError):
    def __init__(self, message: str, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class ProviderRouter:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._round_robin_weights: dict[tuple[int, tuple[tuple[int, int], ...]], dict[int, int]] = {}

    def candidates(self) -> list[dict[str, Any]]:
        return [provider for provider in self.store.providers(reveal_key=True) if provider["enabled"] and not quota_exceeded(provider)]

    def order(self) -> list[dict[str, Any]]:
        providers = self.candidates()
        if not providers:
            enabled = [provider for provider in self.store.providers(reveal_key=True) if provider["enabled"]]
            if enabled:
                raise TranslationError("所有启用路由均已达限额，已自动跳过；请刷新额度或调整限额设置")
            raise TranslationError("No enabled upstream route is available")
        groups: dict[int, list[dict[str, Any]]] = {}
        for provider in providers:
            groups.setdefault(provider["priority"], []).append(provider)
        ordered: list[dict[str, Any]] = []
        for priority in sorted(groups):
            group = groups[priority]
            selected = self._next_weighted(group, priority)
            ordered.append(selected)
            ordered.extend(provider for provider in group if provider["id"] != selected["id"])
        return ordered

    def _next_weighted(self, group: list[dict[str, Any]], priority: int) -> dict[str, Any]:
        signature = tuple(sorted((provider["id"], max(1, provider["weight"])) for provider in group))
        state_key = (priority, signature)
        current = self._round_robin_weights.setdefault(state_key, {provider_id: 0 for provider_id, _ in signature})
        total = sum(weight for _, weight in signature)
        selected_id: int | None = None
        selected_value: int | None = None
        for provider_id, weight in signature:
            current[provider_id] = current.get(provider_id, 0) + weight
            if selected_value is None or current[provider_id] > selected_value:
                selected_id, selected_value = provider_id, current[provider_id]
        assert selected_id is not None
        current[selected_id] -= total
        return next(provider for provider in group if provider["id"] == selected_id)

    async def translate(self, text: str, target_lang: str, source_lang: str | None = None) -> TranslationResult:
        settings = self.store.settings()
        attempts: list[dict[str, Any]] = []
        errors: list[str] = []
        ordered = self.order()
        for index, provider in enumerate(ordered):
            started = time.perf_counter()
            try:
                result = await self._call_provider(provider, text, target_lang, source_lang)
                latency_ms = round((time.perf_counter() - started) * 1000)
                self.store.set_health(provider["id"], "healthy", latency_ms)
                attempts.append({"provider": provider["name"], "kind": provider["kind"], "status": "success", "latency_ms": latency_ms, "request": result.upstream_request or {}, "response": result.upstream_response or {}})
                result.attempts = attempts
                return result
            except Exception as exc:  # noqa: BLE001 - failures must trigger fallback
                latency_ms = round((time.perf_counter() - started) * 1000)
                message = str(exc)[:500]
                self.store.set_health(provider["id"], "unhealthy", latency_ms, message)
                upstream_request = exc.request if isinstance(exc, UpstreamError) else {"endpoint": provider["endpoint"]}
                upstream_response = exc.response if isinstance(exc, UpstreamError) else None
                attempts.append({"provider": provider["name"], "kind": provider["kind"], "status": "failed", "latency_ms": latency_ms, "request": upstream_request, "response": upstream_response, "error": message})
                errors.append(f"{provider['name']}: {message}")
                if settings.get("fallback_enabled", "true") != "true" or index == len(ordered) - 1:
                    break
        raise TranslationError("All upstream translation requests failed: " + "; ".join(errors), attempts)

    async def check(self, provider: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            await self._call_provider(provider, "health check", "ZH", "EN")
            latency_ms = round((time.perf_counter() - started) * 1000)
            self.store.set_health(provider["id"], "healthy", latency_ms, source="check")
            return {"ok": True, "latency_ms": latency_ms}
        except Exception as exc:  # noqa: BLE001
            latency_ms = round((time.perf_counter() - started) * 1000)
            self.store.set_health(provider["id"], "unhealthy", latency_ms, str(exc)[:500], source="check")
            return {"ok": False, "latency_ms": latency_ms, "error": str(exc)}

    async def _call_provider(self, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        upstream = UPSTREAMS.get(provider["kind"])
        if not upstream:
            raise UpstreamError(f"Unsupported upstream kind: {provider['kind']}", request={"endpoint": provider["endpoint"]})
        timeout = httpx.Timeout(float(provider["timeout_seconds"]))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            return await upstream.translate(client, provider, text, target_lang, source_lang)
