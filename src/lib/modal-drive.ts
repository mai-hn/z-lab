import "server-only"

const ALLOWED_ENDPOINTS = new Set([
  "health",
  "files",
  "folders",
  "upload",
  "download",
  "metadata",
  "offline-download",
  "copy",
  "move",
  "transfer",
])
const REQUEST_TIMEOUT_MS = 10 * 60 * 1000

export class ModalDriveError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "ModalDriveError"
  }
}

export function isModalDriveConfigured() {
  return Boolean(
    process.env.MODAL_DRIVE_API_URL?.trim() &&
      process.env.MODAL_PROXY_TOKEN_ID?.trim() &&
      process.env.MODAL_PROXY_TOKEN_SECRET?.trim(),
  )
}

function modalDriveUrl(endpoint: string, search: string) {
  if (!ALLOWED_ENDPOINTS.has(endpoint)) {
    throw new ModalDriveError("不支持的网盘操作。", 404)
  }

  const baseUrl = process.env.MODAL_DRIVE_API_URL?.trim()
  if (!baseUrl) {
    throw new ModalDriveError("Modal 网盘服务尚未配置。", 503)
  }

  let url: URL
  try {
    url = new URL(`${baseUrl.replace(/\/+$/, "")}/${endpoint}${search}`)
  } catch {
    throw new ModalDriveError("MODAL_DRIVE_API_URL 配置无效。", 500)
  }

  const allowLocal = process.env.MODAL_DRIVE_ALLOW_LOCAL_API === "true"
  if (url.protocol !== "https:" && !(allowLocal && url.protocol === "http:")) {
    throw new ModalDriveError("Modal 网盘服务必须使用 HTTPS。", 500)
  }

  if (url.username || url.password) {
    throw new ModalDriveError("Modal 网盘服务地址不能包含账号密码。", 500)
  }

  return url
}

function modalHeaders(request: Request) {
  const tokenId = process.env.MODAL_PROXY_TOKEN_ID?.trim()
  const tokenSecret = process.env.MODAL_PROXY_TOKEN_SECRET?.trim()
  if (!tokenId || !tokenSecret) {
    throw new ModalDriveError("Modal Proxy Token 尚未配置。", 503)
  }

  const headers = new Headers({
    Accept: request.headers.get("accept") || "application/json",
    "Modal-Key": tokenId,
    "Modal-Secret": tokenSecret,
  })
  const contentType = request.headers.get("content-type")
  const range = request.headers.get("range")
  if (contentType) headers.set("Content-Type", contentType)
  if (range) headers.set("Range", range)
  return headers
}

function responseHeaders(upstream: Response) {
  const headers = new Headers({ "Cache-Control": "no-store" })
  for (const name of [
    "accept-ranges",
    "content-disposition",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
  ]) {
    const value = upstream.headers.get(name)
    if (value) headers.set(name, value)
  }
  return headers
}

export async function proxyModalDriveRequest(request: Request, endpoint: string) {
  const incomingUrl = new URL(request.url)
  const target = modalDriveUrl(endpoint, incomingUrl.search)
  const method = request.method.toUpperCase()
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers: modalHeaders(request),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  }

  if (!["GET", "HEAD"].includes(method)) {
    init.body = request.body
    init.duplex = "half"
  }

  const upstream = await fetch(target, init)
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders(upstream),
  })
}

export async function fetchModalDriveMetadata(path: string) {
  const target = modalDriveUrl(
    "metadata",
    `?path=${encodeURIComponent(path)}`,
  )
  const request = new Request("http://toolbox.local", {
    headers: { Accept: "application/json" },
  })
  const response = await fetch(target, {
    method: "GET",
    headers: modalHeaders(request),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  })
  if (!response.ok) {
    throw new ModalDriveError(
      `无法读取媒体元信息（HTTP ${response.status}）。`,
      response.status,
    )
  }
  return response.json() as Promise<{
    entry: {
      name: string
      path: string
      type: "file"
      size: number
      mimeType?: string | null
      modifiedAt: string
    }
    video?: {
      durationSeconds?: number | null
      width?: number | null
      height?: number | null
      videoCodec?: string | null
      audioCodec?: string | null
      frameRate?: number | null
      bitRate?: number | null
      containerFormat?: string | null
    } | null
  }>
}

export function modalDriveErrorResponse(error: unknown) {
  if (error instanceof ModalDriveError) {
    return Response.json(
      { message: error.message },
      { status: error.status, headers: { "Cache-Control": "no-store" } },
    )
  }

  if (error instanceof Error && error.name === "TimeoutError") {
    return Response.json(
      { message: "Modal 网盘服务响应超时。" },
      { status: 504, headers: { "Cache-Control": "no-store" } },
    )
  }

  return Response.json(
    { message: "无法连接 Modal 网盘服务。" },
    { status: 502, headers: { "Cache-Control": "no-store" } },
  )
}
