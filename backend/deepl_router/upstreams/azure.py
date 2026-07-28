from __future__ import annotations

from typing import Any

import httpx

from .base import TranslationResult, Upstream, UpstreamError, UpstreamMeta, register


@register
class AzureTranslatorUpstream(Upstream):
    meta = UpstreamMeta(
        kind="azure",
        label="Azure Translator",
        default_endpoint="https://api.cognitive.microsofttranslator.com",
        endpoint_help="Azure Translator 全球接入点，一般保持默认即可。",
        key_label="Subscription Key",
        key_placeholder="Azure 资源的 Key1 / Key2",
        needs_region=True,
        region_label="资源区域 Region",
        region_placeholder="global / eastasia / westus2",
        color="#0a7cc4",
        sort_order=50,
    )

    language_codes = {"ZH": "zh-Hans", "ZH-HANT": "zh-Hant", "EN": "en", "JA": "ja", "KO": "ko", "DE": "de", "FR": "fr", "ES": "es", "RU": "ru", "IT": "it", "PT-BR": "pt", "PT-PT": "pt-pt"}

    def _language(self, value: str) -> str:
        return self.language_codes.get(value, value.lower())

    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        if not provider.get("api_key"):
            raise UpstreamError("Azure Translator requires a subscription key", request={"method": "POST", "endpoint": provider["endpoint"]})
        endpoint = provider["endpoint"].rstrip("/") or "https://api.cognitive.microsofttranslator.com"
        params: dict[str, str] = {"api-version": "3.0", "to": self._language(target_lang or "ZH")}
        if source_lang:
            params["from"] = self._language(source_lang)
        headers = {"Ocp-Apim-Subscription-Key": provider["api_key"], "Content-Type": "application/json"}
        region = (provider.get("region") or "").strip()
        if region and region.lower() != "global":
            headers["Ocp-Apim-Subscription-Region"] = region
        url = f"{endpoint}/translate"
        body = [{"Text": text}]
        request = {"method": "POST", "endpoint": url, "params": params, "body": body}
        try:
            response = await client.post(url, params=params, json=body, headers=headers)
            response_body = self.response_body(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        first = response_body[0] if isinstance(response_body, list) and response_body else None
        translations = first.get("translations") if isinstance(first, dict) else None
        if not translations or not translations[0].get("text"):
            raise UpstreamError("Azure response is missing [0].translations[0].text", request=request, response={"status_code": response.status_code, "body": response_body})
        detected = (first.get("detectedLanguage") or {}).get("language") if isinstance(first, dict) else None
        return TranslationResult(translations[0]["text"], detected, provider["name"], request, {"status_code": response.status_code, "body": response_body})
