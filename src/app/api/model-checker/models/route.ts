import {
  createManualModel,
  getChannel,
  listModels,
} from "@/lib/model-tester-database"
import {
  gatewayErrorResponse,
  ModelGatewayError,
} from "@/lib/model-checker"

export const dynamic = "force-dynamic"

export function GET(request: Request) {
  const search = new URL(request.url).searchParams
  const channelId = search.get("channelId")?.trim() || undefined
  const includeDisabled = search.get("includeDisabled") === "true"
  return Response.json(
    { models: listModels(channelId, includeDisabled) },
    { headers: { "Cache-Control": "no-store" } },
  )
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      channelId?: unknown
      modelId?: unknown
      displayName?: unknown
    }
    const channelId = typeof body.channelId === "string" ? body.channelId.trim() : ""
    const modelId = typeof body.modelId === "string" ? body.modelId.trim() : ""
    const displayName = typeof body.displayName === "string" ? body.displayName.trim() : ""
    if (!channelId || !getChannel(channelId) || !modelId || modelId.length > 300) {
      throw new ModelGatewayError("请选择渠道并填写有效的模型 ID。", 400)
    }

    return Response.json(
      createManualModel({ channelId, modelId, displayName }),
      { status: 201, headers: { "Cache-Control": "no-store" } },
    )
  } catch (error) {
    if (error instanceof Error && error.message.includes("UNIQUE constraint failed")) {
      return Response.json(
        { message: "该渠道中已经存在此模型。" },
        { status: 409, headers: { "Cache-Control": "no-store" } },
      )
    }
    return gatewayErrorResponse(error)
  }
}
