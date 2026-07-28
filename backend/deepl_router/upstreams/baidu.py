from __future__ import annotations

import time
from typing import Any

import httpx

from .base import TranslationResult, Upstream, UpstreamError, UpstreamMeta, register

TOKEN_ERROR_CODES = {110, 111}  # token 失效 / 过期


@register
class BaiduMTUpstream(Upstream):
    meta = UpstreamMeta(
        kind="baidu",
        label="百度智能云机器翻译",
        default_endpoint="https://aip.baidubce.com",
        endpoint_help="百度智能云接入点，一般保持默认即可。",
        key_label="API Key",
        key_placeholder="百度智能云应用的 API Key",
        needs_secret=True,
        secret_label="Secret Key",
        secret_placeholder="仅用于上游鉴权，不会展示或记录到日志",
        color="#2932e1",
        sort_order=60,
    )

    # 百度使用自有语言代码（jp/kor/fra/spa 等）
    language_codes = {"ZH": "zh", "ZH-HANT": "cht", "EN": "en", "JA": "jp", "KO": "kor", "DE": "de", "FR": "fra", "ES": "spa", "RU": "ru", "IT": "it", "PT-BR": "pt", "PT-PT": "pt"}

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], tuple[str, float]] = {}

    @staticmethod
    def _credentials(provider: dict[str, Any]) -> tuple[str, str]:
        api_key = provider.get("api_key", "")
        secret_key = provider.get("api_secret", "")
        if not api_key or not secret_key:
            raise UpstreamError("Baidu MT requires API Key and Secret Key", request={"method": "POST", "endpoint": provider["endpoint"]})
        return api_key, secret_key

    async def _get_token(self, client: httpx.AsyncClient, endpoint: str, api_key: str, secret_key: str, *, force: bool = False) -> str:
        cache_key = (api_key, secret_key)
        if not force:
            cached = self._tokens.get(cache_key)
            if cached and cached[1] > time.time():
                return cached[0]
        token_url = f"{endpoint}/oauth/2.0/token"
        request = {"method": "POST", "endpoint": token_url}
        try:
            response = await client.post(token_url, params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key})
            body = self.response_body(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(f"Baidu token request failed: {exc}", request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(f"Baidu token request failed: {exc}", request=request) from exc
        # 凭证错误时百度返回 200 + {"error": ...}
        if not isinstance(body, dict) or body.get("error") or not body.get("access_token"):
            detail = body.get("error_description") or body.get("error") if isinstance(body, dict) else body
            raise UpstreamError(f"Baidu token error: {detail}", request=request, response={"status_code": response.status_code, "body": body})
        token = body["access_token"]
        expires_in = int(body.get("expires_in", 2592000))
        self._tokens[cache_key] = (token, time.time() + max(60, expires_in - 3600))
        return token

    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        api_key, secret_key = self._credentials(provider)
        endpoint = provider["endpoint"].rstrip("/") or "https://aip.baidubce.com"
        body = {"q": text, "from": self.language_codes.get(source_lang or "", "auto"), "to": self.language_codes.get(target_lang or "", "zh")}
        translate_url = f"{endpoint}/rpc/2.0/mt/texttrans/v1"
        request = {"method": "POST", "endpoint": translate_url, "body": body}
        token = await self._get_token(client, endpoint, api_key, secret_key)
        for attempt in range(2):
            try:
                response = await client.post(translate_url, params={"access_token": token}, json=body, headers={"Content-Type": "application/json"})
                response_body = self.response_body(response)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
            except Exception as exc:  # noqa: BLE001
                raise UpstreamError(str(exc), request=request) from exc
            error_code = response_body.get("error_code") if isinstance(response_body, dict) else None
            if error_code in TOKEN_ERROR_CODES and attempt == 0:
                token = await self._get_token(client, endpoint, api_key, secret_key, force=True)
                continue
            if error_code:
                raise UpstreamError(f"Baidu MT error: {error_code} {response_body.get('error_msg', '')}", request=request, response={"status_code": response.status_code, "body": response_body})
            break
        result = response_body.get("result", {}) if isinstance(response_body, dict) else {}
        trans_result = result.get("trans_result")
        if not trans_result or not trans_result[0].get("dst"):
            raise UpstreamError("Baidu MT response is missing result.trans_result[0].dst", request=request, response={"status_code": response.status_code, "body": response_body})
        return TranslationResult(trans_result[0]["dst"], source_lang, provider["name"], request, {"status_code": response.status_code, "body": response_body})
