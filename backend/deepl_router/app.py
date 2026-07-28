from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .router import ProviderRouter, TranslationError
from .store import Store
from .upstreams import BATCH_ALIAS_MAP, KINDS, UPSTREAMS

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "frontend" / "dist"
store = Store(os.getenv("DEEPL_ROUTER_DB", str(BASE_DIR / "data" / "router.db")))
router = ProviderRouter(store)


def _validate_kind(value: str) -> str:
    if value not in UPSTREAMS:
        raise ValueError(f"不支持的上游类型：{value}，可选：{', '.join(KINDS)}")
    return value


def _validate_quota_limit(kind: str | None, quota_limit: float | None) -> None:
    if quota_limit is None or kind is None:
        return
    if UPSTREAMS[kind].meta.quota_type is None:
        raise HTTPException(status_code=422, detail=f"上游类型 {kind} 不支持额度/余额查询，无法设置限额")


class ProviderInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str
    endpoint: str = Field(min_length=8, max_length=500)
    api_key: str = Field(default="", max_length=500)
    api_secret: str = Field(default="", max_length=500)
    region: str = Field(default="", max_length=64)
    priority: int = Field(default=100, ge=1, le=10000)
    weight: int = Field(default=1, ge=1, le=1000)
    enabled: bool = True
    timeout_seconds: int = Field(default=20, ge=2, le=120)
    quota_limit: float | None = Field(default=None, ge=0)

    @field_validator("kind")
    @classmethod
    def check_kind(cls, value: str) -> str:
        return _validate_kind(value)


class ProviderPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: str | None = None
    endpoint: str | None = Field(default=None, min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    api_secret: str | None = Field(default=None, max_length=500)
    region: str | None = Field(default=None, max_length=64)
    priority: int | None = Field(default=None, ge=1, le=10000)
    weight: int | None = Field(default=None, ge=1, le=1000)
    enabled: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=2, le=120)
    quota_limit: float | None = Field(default=None, ge=0)

    @field_validator("kind")
    @classmethod
    def check_kind(cls, value: str | None) -> str | None:
        return _validate_kind(value) if value is not None else None


class SettingsInput(BaseModel):
    routing_mode: str | None = None
    fallback_enabled: bool | None = None
    downstream_key: str | None = Field(default=None, max_length=500)


class TranslateInput(BaseModel):
    text: str | list[str] | None = None
    text_list: list[str] | None = None
    target_lang: str
    source_lang: str | None = None


class BatchProvidersInput(BaseModel):
    lines: str = Field(min_length=3, max_length=100_000)
    priority: int = Field(default=100, ge=1, le=10000)
    weight: int = Field(default=1, ge=1, le=1000)
    timeout_seconds: int = Field(default=20, ge=2, le=120)


class ProviderIdsInput(BaseModel):
    provider_ids: list[int] = Field(min_length=1, max_length=1000)


app = FastAPI(title="Translate Router", version="0.4.0")


def require_downstream_key(authorization: str | None = Header(default=None)) -> None:
    configured_key = store.settings().get("downstream_key", "")
    if not configured_key:
        return
    provided = authorization.removeprefix("DeepL-Auth-Key ").removeprefix("Bearer ") if authorization else ""
    if provided != configured_key:
        raise HTTPException(status_code=403, detail="无效的下游访问密钥")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/upstream-kinds")
def list_upstream_kinds():
    return [UPSTREAMS[kind].meta.to_json() for kind in KINDS]


@app.get("/api/dashboard")
def dashboard_stats():
    providers = store.providers()
    return {
        "providers": {
            "total": len(providers),
            "enabled": sum(provider["enabled"] for provider in providers),
            "healthy": sum(provider["last_status"] == "healthy" for provider in providers),
            "quota_exceeded": sum(provider["quota_exceeded"] for provider in providers),
        },
        "requests": store.request_stats(),
    }


@app.get("/api/providers")
def list_providers():
    return store.providers()


@app.post("/api/providers", status_code=201)
def create_provider(payload: ProviderInput):
    _validate_quota_limit(payload.kind, payload.quota_limit)
    return store.create_provider(payload.model_dump())


@app.post("/api/providers/batch", status_code=201)
def create_providers_batch(payload: BatchProvidersInput):
    parsed: list[dict] = []
    errors: list[str] = []
    aliases = "/".join(sorted(set(BATCH_ALIAS_MAP)))
    for line_number, raw_line in enumerate(payload.lines.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in {2, 3}:
            errors.append(f"第 {line_number} 行应为：{aliases} | url | key（可选）")
            continue
        kind = BATCH_ALIAS_MAP.get(parts[0].lower())
        if not kind:
            errors.append(f"第 {line_number} 行类型只能是 {aliases}")
            continue
        endpoint = parts[1].rstrip("/")
        parsed_url = urlparse(endpoint)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            errors.append(f"第 {line_number} 行 URL 无效")
            continue
        key = parts[2] if len(parts) == 3 else ""
        label = UPSTREAMS[kind].meta.label
        parsed.append({
            "name": f"{label} · {parsed_url.netloc}", "kind": kind, "endpoint": endpoint,
            "api_key": key, "api_secret": "", "priority": payload.priority, "weight": payload.weight,
            "enabled": True, "timeout_seconds": payload.timeout_seconds,
        })
    if errors:
        raise HTTPException(status_code=422, detail="；".join(errors))
    if not parsed:
        raise HTTPException(status_code=422, detail="没有可导入的路由")
    return store.create_providers(parsed)


@app.patch("/api/providers/{provider_id}")
def update_provider(provider_id: int, payload: ProviderPatch):
    changes = payload.model_dump(exclude_unset=True)
    if "quota_limit" in changes or "kind" in changes:
        existing = store.provider(provider_id, reveal_key=False)
        if not existing:
            raise HTTPException(status_code=404, detail="路由不存在")
        kind = changes.get("kind", existing["kind"])
        quota_limit = changes.get("quota_limit", existing.get("quota_limit"))
        _validate_quota_limit(kind, quota_limit)
    item = store.update_provider(provider_id, changes)
    if not item:
        raise HTTPException(status_code=404, detail="路由不存在")
    return item


@app.delete("/api/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: int):
    if not store.delete_provider(provider_id):
        raise HTTPException(status_code=404, detail="路由不存在")


@app.post("/api/providers/check")
async def check_all_providers():
    providers = store.providers(reveal_key=True)
    semaphore = asyncio.Semaphore(12)

    async def check_one(provider: dict) -> dict:
        async with semaphore:
            result = await router.check(provider)
        return {"provider_id": provider["id"], "name": provider["name"], **result}

    results = await asyncio.gather(*(check_one(provider) for provider in providers))
    unhealthy = sum(not result["ok"] for result in results)
    return {"total": len(results), "healthy": len(results) - unhealthy, "unhealthy": unhealthy, "results": results}


@app.post("/api/providers/batch/disable-unhealthy")
def disable_unhealthy_providers(payload: ProviderIdsInput):
    provider_ids = store.disable_unhealthy_providers(payload.provider_ids)
    return {"count": len(provider_ids), "provider_ids": provider_ids}


@app.post("/api/providers/batch/delete-unhealthy")
def delete_unhealthy_providers(payload: ProviderIdsInput):
    provider_ids = store.delete_unhealthy_providers(payload.provider_ids)
    return {"count": len(provider_ids), "provider_ids": provider_ids}


@app.post("/api/providers/{provider_id}/check")
async def check_provider(provider_id: int):
    provider = store.provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="路由不存在")
    return await router.check(provider)


async def query_provider_quota(provider: dict) -> dict:
    upstream = UPSTREAMS.get(provider["kind"])
    if not upstream or upstream.meta.quota_type is None:
        raise HTTPException(status_code=422, detail="该上游类型不支持额度/余额查询")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(float(provider["timeout_seconds"])), follow_redirects=True) as client:
            result = await upstream.query_quota(client, provider)
        quota = result.to_json()
        store.set_quota(provider["id"], quota)
        return {"provider_id": provider["id"], "quota": quota}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        store.set_quota(provider["id"], None, str(exc)[:500])
        raise HTTPException(status_code=502, detail=f"额度查询失败：{exc}") from exc


@app.post("/api/quota")
async def query_all_provider_quota():
    providers = [provider for provider in store.providers(reveal_key=True) if UPSTREAMS.get(provider["kind"]) and UPSTREAMS[provider["kind"]].meta.quota_type is not None]
    results = []
    for provider in providers:
        try:
            results.append({"ok": True, **await query_provider_quota(provider)})
        except HTTPException as exc:
            results.append({"ok": False, "provider_id": provider["id"], "error": exc.detail})
    return results


@app.post("/api/providers/{provider_id}/quota")
async def query_single_provider_quota(provider_id: int):
    provider = store.provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="路由不存在")
    return await query_provider_quota(provider)


@app.get("/api/settings")
def get_settings():
    values = store.settings()
    return {**values, "fallback_enabled": values.get("fallback_enabled") == "true", "downstream_key_hint": "已设置" if values.get("downstream_key") else "未设置", "downstream_key": ""}


@app.put("/api/settings")
def update_settings(payload: SettingsInput):
    values = payload.model_dump(exclude_unset=True)
    if "fallback_enabled" in values:
        values["fallback_enabled"] = str(values["fallback_enabled"]).lower()
    store.update_settings(values)
    return get_settings()


@app.get("/api/logs")
def list_request_logs(limit: int = 50):
    return store.request_logs(max(1, min(limit, 100)))


@app.get("/api/logs/{log_id}")
def get_request_log(log_id: int):
    item = store.request_log(log_id)
    if not item:
        raise HTTPException(status_code=404, detail="日志不存在")
    return item


def normalize_language(language: str | None, source: bool = False) -> str | None:
    if not language:
        return None
    normalized = language.strip().lower()
    if source and normalized in {"auto", "detect", "auto-detect"}:
        return None
    aliases = {"zh": "ZH", "zh-cn": "ZH", "zh-hans": "ZH", "zh-tw": "ZH-HANT", "zh-hant": "ZH-HANT", "pt-br": "PT-BR", "pt-pt": "PT-PT"}
    return aliases.get(normalized, normalized.upper())


async def run_translation(text: str, target_lang: str, source_lang: str | None, route: str) -> dict:
    request_id = uuid.uuid4().hex
    downstream_request = {"text": text, "target_lang": target_lang, "source_lang": source_lang}
    started = time.perf_counter()
    try:
        result = await router.translate(text, normalize_language(target_lang), normalize_language(source_lang, source=True) if source_lang else None)
        response = {"translations": [{"text": result.text, "detected_source_language": result.detected_source_language}], "provider": result.provider}
        attempts = result.attempts or [{
            "provider": result.provider, "status": "success",
            "request": result.upstream_request or {}, "response": result.upstream_response or {},
        }]
        store.create_request_log(
            request_id=request_id, route=route, downstream_request=downstream_request,
            upstream_attempts=attempts, response_body=response, provider=result.provider,
            status="success", latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return response
    except TranslationError as exc:
        store.create_request_log(
            request_id=request_id, route=route, downstream_request=downstream_request,
            upstream_attempts=exc.attempts, response_body=None, provider=None, status="failed",
            latency_ms=round((time.perf_counter() - started) * 1000), error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/translate")
async def translate_json(payload: TranslateInput, _: None = Depends(require_downstream_key)):
    texts = payload.text_list or ([payload.text] if isinstance(payload.text, str) else payload.text)
    if not texts:
        raise HTTPException(status_code=422, detail="text 或 text_list 不能为空")
    results = [await run_translation(text, payload.target_lang, payload.source_lang, "/translate") for text in texts]
    translations = [{"text": result["translations"][0]["text"], "detected_source_lang": result["translations"][0]["detected_source_language"]} for result in results]
    return {"data": translations[0]["text"] if len(translations) == 1 else [item["text"] for item in translations], "translations": translations, "providers": [result["provider"] for result in results]}


@app.post("/v2/translate")
async def translate_deepl(request: Request, authorization: str | None = Header(default=None)):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        text = payload.get("text", [])
        target_lang = payload.get("target_lang")
        source_lang = payload.get("source_lang")
        auth_key = payload.get("auth_key")
    else:
        payload = await request.form()
        text = payload.getlist("text")
        target_lang = payload.get("target_lang")
        source_lang = payload.get("source_lang")
        auth_key = payload.get("auth_key")
    text = [text] if isinstance(text, str) else text
    if not text or not target_lang:
        raise HTTPException(status_code=422, detail="text 和 target_lang 为必填项")
    configured_key = store.settings().get("downstream_key", "")
    provided = authorization.removeprefix("DeepL-Auth-Key ").removeprefix("Bearer ") if authorization else auth_key or ""
    if configured_key and provided != configured_key:
        raise HTTPException(status_code=403, detail="无效的下游访问密钥")
    results = [await run_translation(item, target_lang, source_lang, "/v2/translate") for item in text]
    return {"translations": [item["translations"][0] for item in results]}


@app.get("/v2/usage")
def usage(_: None = Depends(require_downstream_key)):
    return {"character_count": 0, "character_limit": 0, "router": "DeepRouter"}


if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith(("api/", "v2/")) or full_path in {"api", "v2", "translate"}:
        raise HTTPException(status_code=404)
    if full_path:
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(DIST_DIR.resolve()):
            return FileResponse(candidate)
    index = DIST_DIR / "index.html"
    if not index.exists():
        return PlainTextResponse("前端未构建，请运行：cd frontend && npm install && npm run build", status_code=503)
    return FileResponse(index)
