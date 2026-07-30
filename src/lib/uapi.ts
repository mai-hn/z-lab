import "server-only"

const DEFAULT_BASE_URL = "https://uapis.cn/api/v1"
const REQUEST_TIMEOUT_MS = 10_000

type QueryValue = string | number | boolean | undefined

export class UapiRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = "UapiRequestError"
  }
}

export async function fetchUapi<T>(
  pathname: string,
  query: Record<string, QueryValue> = {},
): Promise<T> {
  const baseUrl = (process.env.UAPI_API_BASE_URL || DEFAULT_BASE_URL).replace(/\/$/, "")
  const url = new URL(`${baseUrl}/${pathname.replace(/^\//, "")}`)

  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, String(value))
    }
  }

  const headers = new Headers({ Accept: "application/json" })
  const apiKey = process.env.UAPI_API_KEY?.trim()
  if (apiKey) headers.set("Authorization", `Bearer ${apiKey}`)

  let response: Response
  try {
    response = await fetch(url, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
  } catch {
    throw new UapiRequestError("UApiPro 服务暂时不可用，请稍后重试。", 503)
  }

  const payload = (await response.json().catch(() => null)) as
    | { message?: string }
    | null

  if (!response.ok) {
    throw new UapiRequestError(
      payload?.message || `UApiPro 请求失败（${response.status}）`,
      response.status,
    )
  }

  return payload as T
}

export function apiErrorResponse(error: unknown) {
  if (error instanceof UapiRequestError) {
    return Response.json(
      { message: error.message },
      { status: error.status, headers: { "Cache-Control": "no-store" } },
    )
  }

  return Response.json(
    { message: "处理请求时发生未知错误。" },
    { status: 500, headers: { "Cache-Control": "no-store" } },
  )
}

export function liveJson<T extends object>(data: T) {
  return Response.json(
    { ...data, fetched_at: Date.now() },
    { headers: { "Cache-Control": "no-store" } },
  )
}
