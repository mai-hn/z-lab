import {
  getChannelCredentials,
  recordModelRequest,
  replaceSyncedModels,
} from "@/lib/model-tester-database"
import {
  gatewayErrorResponse,
  gatewayTimeouts,
  ModelGatewayError,
  providerError,
  providerHeaders,
  providerUrl,
} from "@/lib/model-checker"

export const dynamic = "force-dynamic"

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params
  const channel = getChannelCredentials(id)
  if (!channel) {
    return Response.json(
      { message: "渠道不存在或已停用。" },
      { status: 404, headers: { "Cache-Control": "no-store" } },
    )
  }

  const startedAt = performance.now()
  try {
    const url = await providerUrl(channel.baseUrl, "models")
    const response = await fetch(url, {
      method: "GET",
      headers: providerHeaders(channel.apiKey),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(gatewayTimeouts.connection),
    })
    if (!response.ok) {
      throw new ModelGatewayError(await providerError(response), response.status)
    }

    const payload = (await response.json()) as { data?: Array<{ id?: unknown }> }
    const modelIds = [...new Set(
      (payload.data || []).flatMap((item) =>
        typeof item?.id === "string" && item.id.trim() ? [item.id.trim()] : [],
      ),
    )].sort((left, right) => left.localeCompare(right))
    const models = replaceSyncedModels(id, modelIds)
    recordModelRequest({
      channelId: id,
      requestType: "models.sync",
      status: "success",
      httpStatus: response.status,
      latencyMs: Math.round(performance.now() - startedAt),
      responseChars: JSON.stringify(payload).length,
    })
    return Response.json(
      { models },
      { headers: { "Cache-Control": "no-store" } },
    )
  } catch (error) {
    const status = error instanceof ModelGatewayError ? error.status : 502
    const message = error instanceof Error ? error.message : "同步模型列表失败。"
    recordModelRequest({
      channelId: id,
      requestType: "models.sync",
      status: "error",
      httpStatus: status,
      latencyMs: Math.round(performance.now() - startedAt),
      errorMessage: message,
    })
    return gatewayErrorResponse(error)
  }
}
