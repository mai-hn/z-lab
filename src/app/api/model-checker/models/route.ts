import {
  gatewayErrorResponse,
  gatewayTimeouts,
  ModelGatewayError,
  providerError,
  providerHeaders,
  providerUrl,
} from "@/lib/model-checker"

export const dynamic = "force-dynamic"

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as { baseUrl?: unknown; apiKey?: unknown }
    const baseUrl = typeof body.baseUrl === "string" ? body.baseUrl.trim() : ""
    const apiKey = typeof body.apiKey === "string" ? body.apiKey : ""
    if (!baseUrl || baseUrl.length > 500 || apiKey.length > 10_000) {
      throw new ModelGatewayError("请填写有效的接口地址。", 400)
    }

    const url = await providerUrl(baseUrl, "models")
    const response = await fetch(url, {
      method: "GET",
      headers: providerHeaders(apiKey),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(gatewayTimeouts.connection),
    })

    if (!response.ok) {
      throw new ModelGatewayError(await providerError(response), response.status)
    }

    const payload = (await response.json()) as { data?: Array<{ id?: unknown }> }
    const models = (payload.data || [])
      .flatMap((item) => (typeof item?.id === "string" ? [item.id] : []))
      .sort((a, b) => a.localeCompare(b))

    return Response.json(
      { models },
      { headers: { "Cache-Control": "no-store" } },
    )
  } catch (error) {
    return gatewayErrorResponse(error)
  }
}
