import {
  gatewayErrorResponse,
  gatewayTimeouts,
  ModelGatewayError,
  providerError,
  providerHeaders,
  providerUrl,
} from "@/lib/model-checker"

type ChatRequest = {
  baseUrl?: unknown
  apiKey?: unknown
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
    const baseUrl = typeof body.baseUrl === "string" ? body.baseUrl.trim() : ""
    const apiKey = typeof body.apiKey === "string" ? body.apiKey : ""
    const model = typeof body.model === "string" ? body.model.trim() : ""
    const prompt = typeof body.prompt === "string" ? body.prompt.trim() : ""
    const systemPrompt = typeof body.systemPrompt === "string" ? body.systemPrompt.trim() : ""
    const stream = body.stream !== false

    if (!baseUrl || !model || !prompt) {
      throw new ModelGatewayError("接口地址、模型和提示词不能为空。", 400)
    }
    if (baseUrl.length > 500 || apiKey.length > 10_000 || model.length > 300) {
      throw new ModelGatewayError("请求参数过长。", 400)
    }
    if (prompt.length > 100_000 || systemPrompt.length > 30_000) {
      throw new ModelGatewayError("提示词内容过长。", 400)
    }

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

    const url = await providerUrl(baseUrl, "chat/completions")
    const response = await fetch(url, {
      method: "POST",
      headers: providerHeaders(apiKey),
      body: JSON.stringify(upstreamBody),
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.any([
        request.signal,
        AbortSignal.timeout(gatewayTimeouts.chat),
      ]),
    })

    if (!response.ok) {
      throw new ModelGatewayError(await providerError(response), response.status)
    }

    if (stream) {
      return new Response(response.body, {
        headers: {
          "Cache-Control": "no-cache, no-store",
          "Content-Type": response.headers.get("content-type") || "text/event-stream; charset=utf-8",
          "X-Accel-Buffering": "no",
        },
      })
    }

    const payload = (await response.json()) as {
      choices?: Array<{ message?: { content?: unknown } }>
      usage?: unknown
    }
    const content = payload.choices?.[0]?.message?.content
    return Response.json(
      {
        content: typeof content === "string" ? content : "",
        usage: payload.usage || null,
      },
      { headers: { "Cache-Control": "no-store" } },
    )
  } catch (error) {
    return gatewayErrorResponse(error)
  }
}
