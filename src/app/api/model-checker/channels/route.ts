import {
  createChannel,
  listChannels,
} from "@/lib/model-tester-database"
import {
  gatewayErrorResponse,
  ModelGatewayError,
  providerUrl,
} from "@/lib/model-checker"

export const dynamic = "force-dynamic"

export function GET() {
  return Response.json(
    { channels: listChannels() },
    { headers: { "Cache-Control": "no-store" } },
  )
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      name?: unknown
      provider?: unknown
      baseUrl?: unknown
      apiKey?: unknown
    }
    const name = typeof body.name === "string" ? body.name.trim() : ""
    const provider = typeof body.provider === "string" ? body.provider.trim() : "custom"
    const baseUrl = typeof body.baseUrl === "string" ? body.baseUrl.trim() : ""
    const apiKey = typeof body.apiKey === "string" ? body.apiKey.trim() : ""

    if (!name || name.length > 120 || provider.length > 80 || apiKey.length > 10_000) {
      throw new ModelGatewayError("渠道名称或配置无效。", 400)
    }
    await providerUrl(baseUrl, "models")

    return Response.json(
      createChannel({
        name,
        provider: provider || "custom",
        baseUrl: baseUrl.replace(/\/+$/, ""),
        apiKey,
      }),
      { status: 201, headers: { "Cache-Control": "no-store" } },
    )
  } catch (error) {
    return gatewayErrorResponse(error)
  }
}
