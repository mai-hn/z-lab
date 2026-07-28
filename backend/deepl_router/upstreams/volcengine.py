from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .base import QuotaResult, TranslationResult, Upstream, UpstreamError, UpstreamMeta, register


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def volc_sign_v4(access_key: str, secret_key: str, *, service: str, region: str, host: str, path: str, method: str, query: dict[str, str], payload: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Build Volcengine V4 (HMAC-SHA256) signed headers.

    与腾讯 TC3 不同：密钥派生链为 SK→Date→Region→Service→"request"，时间头 X-Date 为
    ISO8601 basic 格式，CanonicalRequest 包含排序后的 query string，且需 X-Content-Sha256。
    """
    timestamp = int(time.time()) if timestamp is None else timestamp
    now = datetime.fromtimestamp(timestamp, UTC)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")
    content_sha256 = hashlib.sha256(payload).hexdigest()
    content_type = "application/json"
    canonical_query = "&".join(f"{quote(key, safe='-_.~')}={quote(value, safe='-_.~')}" for key, value in sorted(query.items()))
    canonical_headers = f"content-type:{content_type}\nhost:{host}\nx-content-sha256:{content_sha256}\nx-date:{x_date}\n"
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = f"{method}\n{path}\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{content_sha256}"
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = f"HMAC-SHA256\n{x_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    k_date = _hmac(secret_key.encode("utf-8"), short_date)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    k_signing = _hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = f"HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return {
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": content_sha256,
    }


@register
class VolcengineUpstream(Upstream):
    meta = UpstreamMeta(
        kind="volcengine",
        label="火山引擎机器翻译",
        default_endpoint="https://translate.volcengineapi.com",
        endpoint_help="火山引擎机器翻译接入点，一般保持默认即可。",
        key_label="Access Key ID",
        key_placeholder="AKLTxxxxxxxx",
        needs_secret=True,
        secret_label="Secret Access Key",
        secret_placeholder="仅用于上游鉴权，不会展示或记录到日志",
        quota_type="balance",
        color="#c4321f",
        sort_order=40,
    )

    service = "translate"
    region = "cn-north-1"
    action = "TranslateText"
    version = "2020-06-01"
    billing_endpoint = "https://open.volcengineapi.com"
    language_codes = {"ZH": "zh", "ZH-HANT": "zh-Hant", "EN": "en", "JA": "ja", "KO": "ko", "DE": "de", "FR": "fr", "ES": "es", "RU": "ru", "IT": "it", "PT-BR": "pt", "PT-PT": "pt"}

    @staticmethod
    def _credentials(provider: dict[str, Any]) -> tuple[str, str]:
        access_key = provider.get("api_key", "")
        secret_key = provider.get("api_secret", "")
        if not access_key or not secret_key:
            raise UpstreamError("Volcengine requires AccessKey and SecretKey", request={"method": "POST", "endpoint": provider["endpoint"]})
        return access_key, secret_key

    def _check_error(self, request: dict[str, Any], response: httpx.Response, response_body: Any) -> None:
        metadata = response_body.get("ResponseMetadata", {}) if isinstance(response_body, dict) else {}
        error = metadata.get("Error")
        if error:
            raise UpstreamError(f"Volcengine error: {error.get('Code', 'Unknown')} {error.get('Message', '')}", request=request, response={"status_code": response.status_code, "body": response_body})

    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        access_key, secret_key = self._credentials(provider)
        endpoint = provider["endpoint"].rstrip("/") or "https://translate.volcengineapi.com"
        host = urlparse(endpoint).netloc
        query = {"Action": self.action, "Version": self.version}
        body: dict[str, Any] = {"TargetLanguage": self.language_codes.get(target_lang or "", "zh"), "TextList": [text]}
        if source_lang:
            body["SourceLanguage"] = self.language_codes.get(source_lang, source_lang.lower())
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = volc_sign_v4(access_key, secret_key, service=self.service, region=self.region, host=host, path="/", method="POST", query=query, payload=payload)
        url = f"{endpoint}/?Action={self.action}&Version={self.version}"
        request = {"method": "POST", "endpoint": url, "action": self.action, "body": body}
        try:
            response = await client.post(url, content=payload, headers=headers)
            response_body = self.response_body(response)
            self._check_error(request, response, response_body)
            response.raise_for_status()
        except UpstreamError:
            raise
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        translations = response_body.get("TranslationList") if isinstance(response_body, dict) else None
        if not translations or not translations[0].get("Translation"):
            raise UpstreamError("Volcengine response is missing TranslationList[0].Translation", request=request, response={"status_code": response.status_code, "body": response_body})
        item = translations[0]
        return TranslationResult(item["Translation"], item.get("DetectedSourceLanguage"), provider["name"], request, {"status_code": response.status_code, "body": response_body})

    async def query_quota(self, client: httpx.AsyncClient, provider: dict[str, Any]) -> QuotaResult:
        access_key, secret_key = self._credentials(provider)
        host = urlparse(self.billing_endpoint).netloc
        query = {"Action": "QueryBalanceAcct", "Version": "2022-01-01"}
        headers = volc_sign_v4(access_key, secret_key, service="billing", region=self.region, host=host, path="/", method="GET", query=query, payload=b"")
        url = f"{self.billing_endpoint}/?Action=QueryBalanceAcct&Version=2022-01-01"
        request = {"method": "GET", "endpoint": url, "action": "QueryBalanceAcct"}
        try:
            response = await client.get(url, headers=headers)
            response_body = self.response_body(response)
            self._check_error(request, response, response_body)
            response.raise_for_status()
        except UpstreamError:
            raise
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        result = response_body.get("Result", {}) if isinstance(response_body, dict) else {}
        available = result.get("AvailableBalance")
        if available is None:
            raise UpstreamError("Volcengine balance response is missing Result.AvailableBalance", request=request, response={"status_code": response.status_code, "body": response_body})
        return QuotaResult(type="balance", amount=round(float(available), 2), currency="CNY")
