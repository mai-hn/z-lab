from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/models", tags=["AI Model Checker"])


class Credentials(BaseModel):
    base_url: str = Field(min_length=8)
    api_key: str = Field(min_length=1)


class ChatPayload(Credentials):
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    system_prompt: str = ""
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=2048, ge=1, le=128_000)
    top_p: float = Field(default=1.0, ge=0, le=1)
    frequency_penalty: float = Field(default=0.0, ge=-2, le=2)
    stream: bool = True
    messages: list[dict[str, str]] | None = None


def api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def response_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
        return body.get("error", {}).get("message") or json.dumps(body, ensure_ascii=False)
    except Exception:
        return response.text[:500] or f"HTTP {response.status_code}"


@router.post("/list")
async def list_models(payload: Credentials) -> dict[str, list[str]]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                api_url(payload.base_url, "models"),
                headers=auth_headers(payload.api_key),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"无法连接 API：{exc}") from exc
    if response.is_error:
        raise HTTPException(response.status_code, response_detail(response))
    models = sorted(
        item["id"]
        for item in response.json().get("data", [])
        if isinstance(item, dict) and item.get("id")
    )
    return {"models": models}


def chat_body(payload: ChatPayload) -> dict[str, Any]:
    messages = list(payload.messages or [])
    if not messages:
        if payload.system_prompt.strip():
            messages.append({"role": "system", "content": payload.system_prompt.strip()})
        messages.append({"role": "user", "content": payload.prompt.strip()})
    return {
        "model": payload.model,
        "messages": messages,
        "temperature": payload.temperature,
        "max_tokens": payload.max_tokens,
        "top_p": payload.top_p,
        "frequency_penalty": payload.frequency_penalty,
        "stream": payload.stream,
    }


async def sse_stream(payload: ChatPayload) -> AsyncIterator[str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=20)) as client:
            async with client.stream(
                "POST",
                api_url(payload.base_url, "chat/completions"),
                headers=auth_headers(payload.api_key),
                json=chat_body(payload),
            ) as response:
                if response.is_error:
                    detail = json.dumps(
                        {"detail": response_detail(response)}, ensure_ascii=False
                    )
                    yield f"event: error\ndata: {detail}\n\n"
                    return
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        yield f"data: {line[5:].strip()}\n\n"
    except httpx.HTTPError as exc:
        detail = json.dumps({"detail": str(exc)}, ensure_ascii=False)
        yield f"event: error\ndata: {detail}\n\n"


@router.post("/chat")
async def chat(payload: ChatPayload):
    if payload.stream:
        return StreamingResponse(
            sse_stream(payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                api_url(payload.base_url, "chat/completions"),
                headers=auth_headers(payload.api_key),
                json=chat_body(payload),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"无法连接 API：{exc}") from exc
    if response.is_error:
        raise HTTPException(response.status_code, response_detail(response))
    data = response.json()
    return {
        "content": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
        "raw": data,
    }
