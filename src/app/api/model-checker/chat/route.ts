import {
  findModel,
  getChannelCredentials,
  recordModelRequest,
} from "@/lib/model-tester-database"
import {
  gatewayErrorResponse,
  gatewayTimeouts,
  ModelGatewayError,
  providerError,
  providerHeaders,
  providerUrl,
} from "@/lib/model-checker"

type ChatRequest = {
  channelId?: unknown
  model?: unknown
  prompt?: unknown
  systemPrompt?: unknown
  temperature?: unknown
  maxTokens?: unknown
  topP?: unknown
  frequencyPenalty?: unknown
  stream?: unknown
}

function numberInRange(value: unknown, fallback: number, min: number, max: number) {
  const number = typeof value === "number" ? value : fallback
  if (!Number.isFinite(number) || number < min || number > max) {
    throw new ModelGatewayError(`参数必须位于 ${min}–${max} 之间。`, 400)
  }
  return number
}

export const dynamic = "force-dynamic"

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as ChatRequest
    const channelId = typeof body.channelId === "string" ? body.channelId.trim() : ""
    const model = typeof body.model === "string" ? body.model.trim() : ""
    const prompt = typeof body.prompt === "string" ? body.prompt.trim() : ""
    const systemPrompt = typeof body.systemPrompt === "string" ? body.systemPrompt.trim() : ""
    const stream = body.stream !== false

    if (!channelId || !model || !prompt) {
      throw new ModelGatewayError("渠道、模型和提示词不能为空。", 400)
    }
    if (model.length > 300 || prompt.length > 100_000 || systemPrompt.length > 30_000) {
      throw new ModelGatewayError("请求参数过长。", 400)
    }

    const channel = getChannelCredentials(channelId)
    const modelRecord = findModel(channelId, model)
    if (!channel) throw new ModelGatewayError("渠道不存在或已停用。", 404)
    if (!modelRecord) throw new ModelGatewayError("模型记录不存在或已停用。", 404)
    const modelRecordId = modelRecord.id

    const messages = []
    if (systemPrompt) messages.push({ role: "system", content: systemPrompt })
    messages.push({ role: "user", content: prompt })
    const upstreamBody = {
      model,
      messages,
      temperature: numberInRange(body.temperature, 0.7, 0, 2),
      max_tokens: Math.round(numberInRange(body.maxTokens, 2048, 1, 128_000)),
      top_p: numberInRange(body.topP, 1, 0, 1),
      frequency_penalty: numberInRange(body.frequencyPenalty, 0, -2, 2),
      stream,
    }
    const requestSummary = {
      temperature: upstreamBody.temperature,
      maxTokens: upstreamBody.max_tokens,
      topP: upstreamBody.top_p,
      frequencyPenalty: upstreamBody.frequency_penalty,
      stream,
    }
    const startedAt = performance.now()
    const url = await providerUrl(channel.baseUrl, "chat/completions")
    let response: Response
    try {
      response = await fetch(url, {
        method: "POST",
        headers: providerHeaders(channel.apiKey),
        body: JSON.stringify(upstreamBody),
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.any([
          request.signal,
          AbortSignal.timeout(gatewayTimeouts.chat),
        ]),
      })
    } catch (error) {
      recordModelRequest({
        channelId,
        modelRecordId,
        modelId: model,
        requestType: "chat",
        status: request.signal.aborted ? "cancelled" : "error",
        latencyMs: Math.round(performance.now() - startedAt),
        promptPreview: prompt,
        request: requestSummary,
        errorMessage: error instanceof Error ? error.message : "无法连接模型服务。",
      })
      throw error
    }

    if (!response.ok) {
      const message = await providerError(response)
      recordModelRequest({
        channelId,
        modelRecordId,
        modelId: model,
        requestType: "chat",
        status: "error",
        httpStatus: response.status,
        latencyMs: Math.round(performance.now() - startedAt),
        promptPreview: prompt,
        request: requestSummary,
        errorMessage: message,
      })
      throw new ModelGatewayError(message, response.status)
    }

    if (!stream) {
      const payload = (await response.json()) as {
        choices?: Array<{ message?: { content?: unknown } }>
        usage?: {
          prompt_tokens?: number
          completion_tokens?: number
          total_tokens?: number
        }
      }
      const value = payload.choices?.[0]?.message?.content
      const content = typeof value === "string" ? value : ""
      recordModelRequest({
        channelId,
        modelRecordId,
        modelId: model,
        requestType: "chat",
        status: "success",
        httpStatus: response.status,
        latencyMs: Math.round(performance.now() - startedAt),
        promptPreview: prompt,
        request: requestSummary,
        usage: payload.usage,
        responseChars: content.length,
      })
      return Response.json(
        { content, usage: payload.usage || null },
        { headers: { "Cache-Control": "no-store" } },
      )
    }

    if (!response.body) {
      throw new ModelGatewayError("模型服务没有返回响应流。", 502)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    let responseChars = 0
    let recorded = false

    function finish(status: "success" | "error" | "cancelled", errorMessage?: string) {
      if (recorded) return
      recorded = true
      recordModelRequest({
        channelId,
        modelRecordId,
        modelId: model,
        requestType: "chat",
        status,
        httpStatus: response.status,
        latencyMs: Math.round(performance.now() - startedAt),
        promptPreview: prompt,
        request: requestSummary,
        responseChars,
        errorMessage,
      })
    }

    function inspectChunk(chunk: Uint8Array) {
      buffer += decoder.decode(chunk, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ""
      for (const line of lines) {
        if (!line.startsWith("data:")) continue
        const data = line.slice(5).trim()
        if (!data || data === "[DONE]") continue
        try {
          const payload = JSON.parse(data) as {
            choices?: Array<{ delta?: { content?: unknown } }>
          }
          const delta = payload.choices?.[0]?.delta?.content
          if (typeof delta === "string") responseChars += delta.length
        } catch {
          // Ignore non-JSON SSE fields while preserving the upstream stream.
        }
      }
    }

    const loggedStream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const { value, done } = await reader.read()
          if (done) {
            finish("success")
            controller.close()
            return
          }
          inspectChunk(value)
          controller.enqueue(value)
        } catch (error) {
          finish("error", error instanceof Error ? error.message : "流式响应失败。")
          controller.error(error)
        }
      },
      async cancel(reason) {
        finish("cancelled", "客户端停止了流式请求。")
        await reader.cancel(reason)
      },
    })

    return new Response(loggedStream, {
      headers: {
        "Cache-Control": "no-cache, no-store",
        "Content-Type": response.headers.get("content-type") || "text/event-stream; charset=utf-8",
        "X-Accel-Buffering": "no",
      },
    })
  } catch (error) {
    return gatewayErrorResponse(error)
  }
}
