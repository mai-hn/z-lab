import "server-only"

const CONNECTION_TIMEOUT_MS = 20_000
const CHAT_TIMEOUT_MS = 180_000

export class ModelGatewayError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ModelGatewayError"
  }
}

export async function providerUrl(baseUrl: string, path: string) {
  let url: URL
  try {
    url = new URL(`${baseUrl.trim().replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`)
  } catch {
    throw new ModelGatewayError("请输入有效的 Base URL。", 400)
  }

  if (!(["http:", "https:"] as string[]).includes(url.protocol) || url.username || url.password) {
    throw new ModelGatewayError("Base URL 仅支持不含账号密码的 HTTP(S) 地址。", 400)
  }

  return url
}

export function providerHeaders(apiKey: string) {
  const headers = new Headers({
    Accept: "application/json",
    "Content-Type": "application/json",
  })
  if (apiKey.trim()) headers.set("Authorization", `Bearer ${apiKey.trim()}`)
  return headers
}

export async function providerError(response: Response) {
  const fallback = `模型服务请求失败（HTTP ${response.status}）。`
  try {
    const payload = (await response.json()) as {
      detail?: string
      message?: string
      error?: { message?: string } | string
    }
    if (typeof payload.error === "string") return payload.error
    return payload.error?.message || payload.detail || payload.message || fallback
  } catch {
    const text = await response.text().catch(() => "")
    return text.slice(0, 500) || fallback
  }
}

export function gatewayErrorResponse(error: unknown) {
  if (error instanceof ModelGatewayError) {
    return Response.json(
      { message: error.message },
      { status: error.status, headers: { "Cache-Control": "no-store" } },
    )
  }

  if (error instanceof Error && error.name === "TimeoutError") {
    return Response.json(
      { message: "模型服务响应超时。" },
      { status: 504, headers: { "Cache-Control": "no-store" } },
    )
  }

  return Response.json(
    { message: "无法连接模型服务，请检查地址与网络。" },
    { status: 502, headers: { "Cache-Control": "no-store" } },
  )
}

export const gatewayTimeouts = {
  connection: CONNECTION_TIMEOUT_MS,
  chat: CHAT_TIMEOUT_MS,
} as const
