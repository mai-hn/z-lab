from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import QuotaResult, TranslationResult, Upstream, UpstreamError, UpstreamMeta, register


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def tc3_sign(secret_id: str, secret_key: str, *, service: str, host: str, path: str, payload: bytes, action: str, version: str, region: str, timestamp: int | None = None) -> dict[str, str]:
    """Build TC3-HMAC-SHA256 signed headers for a Tencent Cloud POST request."""
    timestamp = int(time.time()) if timestamp is None else timestamp
    date = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d")
    canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\n"
    signed_headers = "content-type;host"
    hashed_payload = hashlib.sha256(payload).hexdigest()
    canonical_request = f"POST\n{path}\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = f"TC3-HMAC-SHA256 Credential={secret_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return {
        "Authorization": authorization,
        "Content-Type": "application/json; charset=utf-8",
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Version": version,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Region": region,
    }


@register
class TencentCloudUpstream(Upstream):
    meta = UpstreamMeta(
        kind="tencent",
        label="腾讯云机器翻译",
        default_endpoint="https://tmt.tencentcloudapi.com",
        endpoint_help="腾讯云 TMT 接入点，一般保持默认即可。",
        key_label="SecretId",
        key_placeholder="AKIDxxxxxxxx",
        needs_secret=True,
        secret_label="SecretKey",
        secret_placeholder="仅用于上游鉴权，不会展示或记录到日志",
        quota_type="balance",
        color="#b15b00",
        sort_order=30,
    )

    service = "tmt"
    version = "2018-03-21"
    action = "TextTranslate"
    region = "ap-guangzhou"
    billing_endpoint = "https://billing.tencentcloudapi.com"
    language_codes = {"ZH": "zh", "ZH-HANT": "zh-TW", "EN": "en", "JA": "ja", "KO": "ko", "DE": "de", "FR": "fr", "ES": "es", "RU": "ru", "IT": "it", "PT-BR": "pt", "PT-PT": "pt"}

    def _language(self, value: str | None, default: str) -> str:
        return self.language_codes.get(value or "", default)

    @staticmethod
    def _credentials(provider: dict[str, Any]) -> tuple[str, str]:
        secret_id = provider.get("api_key", "")
        secret_key = provider.get("api_secret", "")
        if not secret_id or not secret_key:
            raise UpstreamError("Tencent Cloud requires SecretId and SecretKey", request={"method": "POST", "endpoint": provider["endpoint"]})
        return secret_id, secret_key

    async def _call(self, client: httpx.AsyncClient, provider: dict[str, Any], *, endpoint: str, service: str, action: str, version: str, body: dict[str, Any]) -> tuple[dict[str, Any], httpx.Response, Any]:
        secret_id, secret_key = self._credentials(provider)
        parsed = urlparse(endpoint)
        host = parsed.netloc
        path = parsed.path or "/"
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = tc3_sign(secret_id, secret_key, service=service, host=host, path=path, payload=payload, action=action, version=version, region=self.region)
        request = {"method": "POST", "endpoint": endpoint, "action": action, "body": body}
        try:
            response = await client.post(endpoint, content=payload, headers=headers)
            response_body = self.response_body(response)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(str(exc), request=request, response={"status_code": exc.response.status_code, "body": self.response_body(exc.response)}) from exc
        except Exception as exc:  # noqa: BLE001
            raise UpstreamError(str(exc), request=request) from exc
        result = response_body.get("Response", {}) if isinstance(response_body, dict) else {}
        if result.get("Error"):
            error = result["Error"]
            raise UpstreamError(f"Tencent Cloud error: {error.get('Code', 'Unknown')} {error.get('Message', '')}", request=request, response={"status_code": response.status_code, "body": response_body})
        return request, response, response_body

    async def translate(self, client: httpx.AsyncClient, provider: dict[str, Any], text: str, target_lang: str, source_lang: str | None) -> TranslationResult:
        endpoint = provider["endpoint"].rstrip("/") or "https://tmt.tencentcloudapi.com"
        body = {"SourceText": text, "Source": self._language(source_lang, "auto"), "Target": self._language(target_lang, "zh"), "ProjectId": 0}
        request, response, response_body = await self._call(client, provider, endpoint=endpoint, service=self.service, action=self.action, version=self.version, body=body)
        translated = response_body.get("Response", {}).get("TargetText")
        if not isinstance(translated, str) or not translated:
            raise UpstreamError("Tencent Cloud response is missing Response.TargetText", request=request, response={"status_code": response.status_code, "body": response_body})
        return TranslationResult(translated, source_lang, provider["name"], request, {"status_code": response.status_code, "body": response_body})

    async def query_quota(self, client: httpx.AsyncClient, provider: dict[str, Any]) -> QuotaResult:
        request, response, response_body = await self._call(client, provider, endpoint=self.billing_endpoint, service="billing", action="DescribeAccountBalance", version="2018-07-09", body={})
        balance = response_body.get("Response", {}).get("Balance")
        if balance is None:
            raise UpstreamError("Tencent Cloud balance response is missing Response.Balance", request=request, response={"status_code": response.status_code, "body": response_body})
        # Balance 单位为分
        return QuotaResult(type="balance", amount=round(float(balance) / 100, 2), currency="CNY")
