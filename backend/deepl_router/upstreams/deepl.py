from __future__ import annotations

from typing import Any

import httpx

from .base import QuotaResult, TranslationResult, Upstream, UpstreamError, UpstreamMeta, register


def usage_url(provider: dict[str, Any]) -> str:
    endpoint = provider["endpoint"].rstrip("/")
    if provider["api_key"].endswith(":fx"):
        return "https://api-free.deepl.com/v2/usage"
    if "/v2/" in endpoint:
        endpoint = endpoint.split("/v2/", 1)[0]
    elif endpoint.endswith("/v2"):
        endpoint = endpoint[:-3]
    return f"{endpoint}/v2/usage"


@register
class DeepLUpstream(Upstream):
    meta = UpstreamMeta(
        kind="deepl",
        label="DeepL API",
        default_endpoint="https://api.deepl.com",
        endpoint_help="DeepL 地址会自动补齐 /v2/translate。",
        key_label="DeepL API Key",
        key_placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx",
        quota_type="characters",
        color="#265cdb",
        sort_order=10,
        batch_aliases=("deepl",),
    )

    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        endpoint = provider["endpoint"].rstrip("/")
        if not endpoint.endswith("/v2/translate"):
            endpoint += "/v2/translate"
        body = {"text": [text], "target_lang": target_lang}
        if source_lang:
            body["source_lang"] = source_lang
        request = {"method": "POST", "endpoint": endpoint, "body": body}
        try:
            response = await client.post(endpoint, json=body, headers={"Authorization": f"DeepL-Auth-Key {provider['api_key']}"})
            response_body = self.response_body(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        translations = response_body.get("translations") if isinstance(response_body, dict) else None
        if not translations or not translations[0].get("text"):
            raise UpstreamError("DeepL response is missing translations[0].text", request=request, response={"status_code": response.status_code, "body": response_body})
        item = translations[0]
        return TranslationResult(item["text"], item.get("detected_source_language"), provider["name"], request, {"status_code": response.status_code, "body": response_body})

    async def query_quota(self, client: httpx.AsyncClient, provider: dict[str, Any]) -> QuotaResult:
        if not provider.get("api_key"):
            raise UpstreamError("该路由没有配置 DeepL API Key", request={"endpoint": provider["endpoint"]})
        url = usage_url(provider)
        request = {"method": "GET", "endpoint": url}
        try:
            response = await client.get(url, headers={"Authorization": f"DeepL-Auth-Key {provider['api_key']}"})
            body = self.response_body(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        if not isinstance(body, dict):
            raise UpstreamError("DeepL usage response is not JSON", request=request, response={"status_code": response.status_code, "body": body})
        return QuotaResult(type="characters", used=int(body.get("character_count", 0)), limit=int(body.get("character_limit", 0)))
