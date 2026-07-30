import {
  deleteStoredModel,
  updateStoredModel,
} from "@/lib/model-tester-database"
import {
  gatewayErrorResponse,
  ModelGatewayError,
} from "@/lib/model-checker"

export const dynamic = "force-dynamic"

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params
    const body = (await request.json()) as {
      modelId?: unknown
      displayName?: unknown
      enabled?: unknown
    }
    const input: {
      modelId?: string
      displayName?: string
      enabled?: boolean
    } = {}
    if ("modelId" in body) {
      if (typeof body.modelId !== "string" || !body.modelId.trim() || body.modelId.length > 300) {
        throw new ModelGatewayError("模型 ID 无效。", 400)
      }
      input.modelId = body.modelId.trim()
    }
    if ("displayName" in body) {
      if (typeof body.displayName !== "string" || body.displayName.length > 300) {
        throw new ModelGatewayError("模型显示名称无效。", 400)
      }
      input.displayName = body.displayName.trim()
    }
    if ("enabled" in body) input.enabled = Boolean(body.enabled)

    const model = updateStoredModel(id, input)
    if (!model) throw new ModelGatewayError("模型记录不存在。", 404)
    return Response.json(model, { headers: { "Cache-Control": "no-store" } })
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

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  if (!deleteStoredModel(id)) {
    return Response.json(
      { message: "模型记录不存在。" },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    )
  }
  return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } })
}
