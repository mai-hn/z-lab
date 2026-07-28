from __future__ import annotations

from typing import Any

import httpx

from .base import TranslationResult, Upstream, UpstreamError, UpstreamMeta, register


class JsonTranslateUpstream(Upstream):
    def __init__(self, meta: UpstreamMeta) -> None:
        self.meta = meta  # type: ignore[misc]

    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        endpoint = provider["endpoint"].rstrip("/")
        if not endpoint.endswith("/translate"):
            endpoint += "/translate"
        body = {"text": text, "target_lang": target_lang, "source_lang": source_lang or "auto"}
        headers = {"Content-Type": "application/json"}
        if provider["api_key"]:
            headers["Authorization"] = f"Bearer {provider['api_key']}"
        request = {"method": "POST", "endpoint": endpoint, "body": body}
        try:
            response = await client.post(endpoint, json=body, headers=headers)
            response_body = self.response_body(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        translated = (response_body.get("text") or response_body.get("data") or response_body.get("translation")) if isinstance(response_body, dict) else None
        if isinstance(translated, dict):
            translated = translated.get("text") or translated.get("translation")
        if not isinstance(translated, str) or not translated:
            raise UpstreamError("Upstream response has no text/data/translation field", request=request, response={"status_code": response.status_code, "body": response_body})
        return TranslationResult(translated, response_body.get("detected_source_language") or response_body.get("source_lang"), provider["name"], request, {"status_code": response.status_code, "body": response_body})


register(JsonTranslateUpstream(UpstreamMeta(
    kind="deeplx",
    label="DeepLX / DLX",
    default_endpoint="https://dlx.example.com",
    endpoint_help="DeepLX 地址会自动补齐 /translate。",
    key_label="Token（可选）",
    key_placeholder="Bearer Token，留空则不鉴权",
    color="#188b4e",
    sort_order=20,
    batch_aliases=("dlx", "deeplx"),
)))

register(JsonTranslateUpstream(UpstreamMeta(
    kind="custom",
    label="自定义 API",
    default_endpoint="https://example.com",
    endpoint_help="自定义地址会自动补齐 /translate，需返回 text/data/translation 字段。",
    key_label="Bearer Token（可选）",
    key_placeholder="留空则不鉴权",
    color="#6e42db",
    sort_order=90,
)))
