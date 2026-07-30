import "server-only"

import { lookup } from "node:dns/promises"
import { isIP } from "node:net"

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

function isPrivateIpv4(address: string) {
  const octets = address.split(".").map(Number)
  if (octets.length !== 4 || octets.some((part) => !Number.isInteger(part))) return true

  const [first, second] = octets
  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    first >= 224 ||
    (first === 100 && second >= 64 && second <= 127) ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  )
}

function isPrivateIpv6(address: string) {
  const normalized = address.toLowerCase()
  if (normalized.startsWith("::ffff:")) {
    return isPrivateIpv4(normalized.slice(7))
  }

  return (
    normalized === "::" ||
    normalized === "::1" ||
    normalized.startsWith("fc") ||
    normalized.startsWith("fd") ||
    /^fe[89ab]/.test(normalized)
  )
}

function isPrivateAddress(address: string) {
  const version = isIP(address)
  if (version === 4) return isPrivateIpv4(address)
  if (version === 6) return isPrivateIpv6(address)
  return true
}

async function assertPublicHost(url: URL) {
  if (process.env.AI_MODEL_CHECKER_ALLOW_PRIVATE_HOSTS === "true") return

  const hostname = url.hostname.toLowerCase()
  if (hostname === "localhost" || hostname.endsWith(".localhost")) {
    throw new ModelGatewayError("默认不允许访问本机或内网地址。", 403)
  }

  if (isIP(hostname) && isPrivateAddress(hostname)) {
    throw new ModelGatewayError("默认不允许访问本机或内网地址。", 403)
  }

  try {
    const addresses = await lookup(hostname, { all: true, verbatim: true })
    if (addresses.length === 0 || addresses.some(({ address }) => isPrivateAddress(address))) {
      throw new ModelGatewayError("目标域名解析到了内网地址，已拒绝请求。", 403)
    }
  } catch (error) {
    if (error instanceof ModelGatewayError) throw error
    throw new ModelGatewayError("无法解析 API 服务地址。", 400)
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

  await assertPublicHost(url)
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
  const fallback = `模型服务请求失败（HTTP ${response.status}）`
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
