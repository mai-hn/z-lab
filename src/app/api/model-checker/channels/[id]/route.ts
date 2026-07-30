import {
  deleteChannel,
  getChannel,
  updateChannel,
} from "@/lib/model-tester-database"
import {
  gatewayErrorResponse,
  ModelGatewayError,
  providerUrl,
} from "@/lib/model-checker"

export const dynamic = "force-dynamic"

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params
    if (!getChannel(id, true)) {
      throw new ModelGatewayError("渠道不存在。", 404)
    }

    const body = (await request.json()) as {
      name?: unknown
      provider?: unknown
      baseUrl?: unknown
      apiKey?: unknown
      enabled?: unknown
    }
    const input: {
      name?: string
      provider?: string
      baseUrl?: string
      apiKey?: string
      enabled?: boolean
    } = {}

    if ("name" in body) {
      if (typeof body.name !== "string" || !body.name.trim() || body.name.length > 120) {
        throw new ModelGatewayError("渠道名称无效。", 400)
      }
      input.name = body.name.trim()
    }
    if ("provider" in body) {
      if (typeof body.provider !== "string" || body.provider.length > 80) {
        throw new ModelGatewayError("服务商名称无效。", 400)
      }
      input.provider = body.provider.trim() || "custom"
    }
    if ("baseUrl" in body) {
      if (typeof body.baseUrl !== "string") {
        throw new ModelGatewayError("Base URL 无效。", 400)
      }
      await providerUrl(body.baseUrl, "models")
      input.baseUrl = body.baseUrl.trim().replace(/\/+$/, "")
    }
    if ("apiKey" in body) {
      if (typeof body.apiKey !== "string" || body.apiKey.length > 10_000) {
        throw new ModelGatewayError("API Key 无效。", 400)
      }
      input.apiKey = body.apiKey.trim()
    }
    if ("enabled" in body) input.enabled = Boolean(body.enabled)

    return Response.json(updateChannel(id, input), {
      headers: { "Cache-Control": "no-store" },
    })
  } catch (error) {
    return gatewayErrorResponse(error)
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  if (!deleteChannel(id)) {
    return Response.json(
      { message: "渠道不存在。" },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    )
  }
  return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } })
}
