"use client"

import * as React from "react"
import {
  BotIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ClipboardIcon,
  Clock3Icon,
  EyeIcon,
  EyeOffIcon,
  HistoryIcon,
  Layers3Icon,
  PlayIcon,
  RotateCcwIcon,
  SendIcon,
  ServerCogIcon,
  SquareIcon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@/components/ui/input-group"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { cn } from "@/lib/utils"

const STORAGE_KEY = "toolbox-ai-model-checker-v1"
const HISTORY_LIMIT = 30

const providerPresets = [
  { name: "OpenAI", url: "https://api.openai.com/v1" },
  { name: "DeepSeek", url: "https://api.deepseek.com/v1" },
  { name: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { name: "硅基流动", url: "https://api.siliconflow.cn/v1" },
  { name: "通义千问", url: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { name: "智谱 GLM", url: "https://open.bigmodel.cn/api/paas/v4" },
] as const

const promptTemplates = [
  { label: "自我介绍", prompt: "你好，请简单介绍一下你自己，包括你的能力和特点。" },
  { label: "概念解释", prompt: "请用一句话解释什么是大语言模型。" },
  { label: "代码生成", prompt: "写一段 TypeScript 快速排序代码，并添加必要注释。" },
  { label: "格式测试", prompt: "请用 Markdown 总结 React 的五个核心概念。" },
] as const

type TestHistory = {
  id: string
  model: string
  prompt: string
  duration: number
  ok: boolean
  createdAt: number
}

type Parameters = {
  temperature: number
  maxTokens: number
  topP: number
  frequencyPenalty: number
  systemPrompt: string
}

type CompareResult = {
  model: string
  content: string
  duration: number | null
  status: "pending" | "success" | "error"
}

const defaultParameters: Parameters = {
  temperature: 0.7,
  maxTokens: 2048,
  topP: 1,
  frequencyPenalty: 0,
  systemPrompt: "",
}

async function readError(response: Response) {
  const payload = (await response.json().catch(() => null)) as { message?: string } | null
  return payload?.message || `请求失败（HTTP ${response.status}）`
}

async function readOpenAiStream(response: Response, onDelta: (content: string) => void) {
  if (!response.body) throw new Error("模型服务没有返回响应流。")

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let answer = ""

  function consume(eventBlock: string) {
    const data = eventBlock
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("\n")

    if (!data || data === "[DONE]") return
    try {
      const payload = JSON.parse(data) as {
        choices?: Array<{ delta?: { content?: unknown } }>
        error?: { message?: string } | string
      }
      if (payload.error) {
        throw new Error(typeof payload.error === "string" ? payload.error : payload.error.message)
      }
      const delta = payload.choices?.[0]?.delta?.content
      if (typeof delta === "string") {
        answer += delta
        onDelta(answer)
      }
    } catch (error) {
      if (error instanceof SyntaxError) return
      throw error
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const events = buffer.split(/\r?\n\r?\n/)
    buffer = events.pop() || ""
    events.forEach(consume)
    if (done) break
  }

  if (buffer.trim()) consume(buffer)
  return answer
}

function ModelSelect({
  label,
  models,
  value,
  onValueChange,
}: {
  label: string
  models: string[]
  value: string
  onValueChange: (value: string) => void
}) {
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Select value={value || null} onValueChange={(next) => onValueChange(next || "")}>
        <SelectTrigger className="h-10 w-full font-mono" disabled={models.length === 0}>
          <SelectValue placeholder={models.length ? "选择模型" : "请先获取模型列表"} />
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {models.map((model) => (
              <SelectItem key={model} value={model}>{model}</SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </Field>
  )
}

function MetricBadge({ children }: { children: React.ReactNode }) {
  return <Badge variant="outline" className="font-mono font-normal">{children}</Badge>
}

export function AiModelTester() {
  const [baseUrl, setBaseUrl] = React.useState("")
  const [apiKey, setApiKey] = React.useState("")
  const [showApiKey, setShowApiKey] = React.useState(false)
  const [models, setModels] = React.useState<string[]>([])
  const [selectedModel, setSelectedModel] = React.useState("")
  const [compareModelA, setCompareModelA] = React.useState("")
  const [compareModelB, setCompareModelB] = React.useState("")
  const [prompt, setPrompt] = React.useState("你好，请简单介绍一下你自己。")
  const [comparePrompt, setComparePrompt] = React.useState("用一句话解释什么是人工智能。")
  const [parameters, setParameters] = React.useState(defaultParameters)
  const [stream, setStream] = React.useState(true)
  const [advancedOpen, setAdvancedOpen] = React.useState(false)
  const [loadingModels, setLoadingModels] = React.useState(false)
  const [running, setRunning] = React.useState(false)
  const [comparing, setComparing] = React.useState(false)
  const [output, setOutput] = React.useState("")
  const [error, setError] = React.useState("")
  const [metrics, setMetrics] = React.useState<{ duration: number; chars: number } | null>(null)
  const [compareResults, setCompareResults] = React.useState<CompareResult[]>([])
  const [history, setHistory] = React.useState<TestHistory[]>([])
  const [activeTab, setActiveTab] = React.useState("single")
  const controllerRef = React.useRef<AbortController | null>(null)

  React.useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") as {
          baseUrl?: string
          selectedModel?: string
          history?: TestHistory[]
        }
        if (saved.baseUrl) setBaseUrl(saved.baseUrl)
        if (saved.selectedModel) setSelectedModel(saved.selectedModel)
        if (Array.isArray(saved.history)) setHistory(saved.history.slice(0, HISTORY_LIMIT))
      } catch {
        localStorage.removeItem(STORAGE_KEY)
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [])

  React.useEffect(() => () => controllerRef.current?.abort(), [])

  const selectedPreset = React.useMemo(
    () => providerPresets.find((preset) => preset.url === baseUrl)?.name || "",
    [baseUrl],
  )

  function persistPreferences(nextHistory = history, nextModel = selectedModel) {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ baseUrl, selectedModel: nextModel, history: nextHistory.slice(0, HISTORY_LIMIT) }),
    )
  }

  function addHistory(entry: Omit<TestHistory, "id" | "createdAt">) {
    setHistory((current) => {
      const next = [
        { ...entry, id: crypto.randomUUID(), createdAt: Date.now() },
        ...current,
      ].slice(0, HISTORY_LIMIT)
      persistPreferences(next)
      return next
    })
  }

  async function fetchModels() {
    if (!baseUrl.trim()) {
      setError("请先填写 Base URL。")
      return
    }

    setLoadingModels(true)
    setError("")
    try {
      const response = await fetch("/api/model-checker/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseUrl, apiKey }),
      })
      if (!response.ok) throw new Error(await readError(response))
      const data = (await response.json()) as { models: string[] }
      setModels(data.models)
      const nextModel = data.models.includes(selectedModel) ? selectedModel : data.models[0] || ""
      setSelectedModel(nextModel)
      setCompareModelA(data.models[0] || "")
      setCompareModelB(data.models[1] || "")
      persistPreferences(history, nextModel)
      toast.success(`已获取 ${data.models.length} 个模型`)
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "获取模型列表失败。"
      setError(message)
      setModels([])
    } finally {
      setLoadingModels(false)
    }
  }

  function chatPayload(model: string, testPrompt: string, shouldStream: boolean) {
    return {
      baseUrl,
      apiKey,
      model,
      prompt: testPrompt,
      systemPrompt: parameters.systemPrompt,
      temperature: parameters.temperature,
      maxTokens: parameters.maxTokens,
      topP: parameters.topP,
      frequencyPenalty: parameters.frequencyPenalty,
      stream: shouldStream,
    }
  }

  async function requestStandard(model: string, testPrompt: string, signal?: AbortSignal) {
    const response = await fetch("/api/model-checker/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(chatPayload(model, testPrompt, false)),
      signal,
    })
    if (!response.ok) throw new Error(await readError(response))
    const data = (await response.json()) as { content?: string }
    return data.content || ""
  }

  async function runSingle() {
    if (!baseUrl.trim() || !selectedModel || !prompt.trim()) {
      setError("请先完成接口配置、选择模型并填写提示词。")
      return
    }

    const controller = new AbortController()
    controllerRef.current = controller
    setRunning(true)
    setError("")
    setOutput("")
    setMetrics(null)
    const startedAt = performance.now()

    try {
      let content = ""
      if (stream) {
        const response = await fetch("/api/model-checker/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(chatPayload(selectedModel, prompt, true)),
          signal: controller.signal,
        })
        if (!response.ok) throw new Error(await readError(response))
        content = await readOpenAiStream(response, setOutput)
      } else {
        content = await requestStandard(selectedModel, prompt, controller.signal)
        setOutput(content)
      }

      const duration = (performance.now() - startedAt) / 1000
      setMetrics({ duration, chars: content.length })
      addHistory({ model: selectedModel, prompt, duration, ok: true })
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        toast.info("已停止生成")
      } else {
        const message = requestError instanceof Error ? requestError.message : "模型请求失败。"
        setError(message)
        addHistory({
          model: selectedModel,
          prompt,
          duration: (performance.now() - startedAt) / 1000,
          ok: false,
        })
      }
    } finally {
      controllerRef.current = null
      setRunning(false)
    }
  }

  async function runCompare() {
    const chosenModels = [...new Set([compareModelA, compareModelB].filter(Boolean))]
    if (chosenModels.length < 2 || !comparePrompt.trim()) {
      toast.error("请选择两个不同的模型并填写提示词。")
      return
    }

    setComparing(true)
    setCompareResults(chosenModels.map((model) => ({ model, content: "", duration: null, status: "pending" })))

    await Promise.all(
      chosenModels.map(async (model) => {
        const startedAt = performance.now()
        try {
          const content = await requestStandard(model, comparePrompt)
          const duration = (performance.now() - startedAt) / 1000
          setCompareResults((current) => current.map((item) =>
            item.model === model ? { ...item, content, duration, status: "success" } : item,
          ))
          addHistory({ model, prompt: comparePrompt, duration, ok: true })
        } catch (requestError) {
          const message = requestError instanceof Error ? requestError.message : "请求失败。"
          const duration = (performance.now() - startedAt) / 1000
          setCompareResults((current) => current.map((item) =>
            item.model === model ? { ...item, content: message, duration, status: "error" } : item,
          ))
          addHistory({ model, prompt: comparePrompt, duration, ok: false })
        }
      }),
    )
    setComparing(false)
  }

  async function copyOutput() {
    if (!output) return
    await navigator.clipboard.writeText(output)
    toast.success("响应内容已复制")
  }

  function loadHistoryItem(item: TestHistory) {
    setSelectedModel(item.model)
    setPrompt(item.prompt)
    setActiveTab("single")
    toast.success("已载入历史测试")
  }

  function clearHistory() {
    setHistory([])
    persistPreferences([])
    toast.success("历史记录已清空")
  }

  return (
    <section aria-labelledby="model-tester-title">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 id="model-tester-title" className="flex scroll-mt-28 items-center gap-3 text-2xl font-semibold tracking-[-0.035em] sm:text-3xl">
            <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
              <BotIcon className="size-5" />
            </span>
            AI 模型测试
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            连接 OpenAI 兼容接口，查询模型并测试流式生成、参数响应与模型差异。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline"><ZapIcon data-icon="inline-start" />Stream</Badge>
          <Badge variant="outline"><Layers3Icon data-icon="inline-start" />Compare</Badge>
        </div>
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="xl:sticky xl:top-[102px]">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ServerCogIcon className="size-5" />
              接口配置
            </CardTitle>
            <CardDescription>填写兼容 OpenAI API 的服务地址与访问密钥。</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel>服务商预设</FieldLabel>
                <ToggleGroup
                  aria-label="选择服务商预设"
                  variant="outline"
                  size="sm"
                  className="flex-wrap"
                  value={selectedPreset ? [selectedPreset] : []}
                  onValueChange={(values) => {
                    const preset = providerPresets.find((item) => item.name === values[0])
                    if (preset) setBaseUrl(preset.url)
                  }}
                >
                  {providerPresets.map((preset) => (
                    <ToggleGroupItem key={preset.name} value={preset.name}>{preset.name}</ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </Field>

              <Field>
                <FieldLabel htmlFor="model-base-url">Base URL</FieldLabel>
                <Input
                  id="model-base-url"
                  autoComplete="url"
                  placeholder="https://api.example.com/v1"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                />
                <FieldDescription>填写到版本路径即可，无需追加 /chat/completions。</FieldDescription>
              </Field>

              <Field>
                <FieldLabel htmlFor="model-api-key">API Key</FieldLabel>
                <InputGroup>
                  <InputGroupInput
                    id="model-api-key"
                    type={showApiKey ? "text" : "password"}
                    autoComplete="off"
                    placeholder="sk-...（本地服务可留空）"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                  />
                  <InputGroupAddon align="inline-end">
                    <InputGroupButton
                      size="icon-xs"
                      aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}
                      onClick={() => setShowApiKey((current) => !current)}
                    >
                      {showApiKey ? <EyeOffIcon /> : <EyeIcon />}
                    </InputGroupButton>
                  </InputGroupAddon>
                </InputGroup>
                <FieldDescription>密钥仅保存在当前页面内存中，不写入本地存储。</FieldDescription>
              </Field>

              <Button type="button" size="lg" disabled={loadingModels} onClick={fetchModels}>
                {loadingModels ? <Spinner data-icon="inline-start" /> : <RotateCcwIcon data-icon="inline-start" />}
                {loadingModels ? "正在连接…" : "获取模型列表"}
              </Button>
            </FieldGroup>

            {error ? (
              <Alert variant="destructive" className="mt-5">
                <AlertTitle>请求失败</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
          </CardContent>
          <CardFooter className="justify-between gap-3 text-xs text-muted-foreground">
            <span>{models.length ? `${models.length} 个模型可用` : "等待连接"}</span>
            <Badge variant={models.length ? "default" : "secondary"}>
              {models.length ? <CheckCircle2Icon data-icon="inline-start" /> : null}
              {models.length ? "已连接" : "未连接"}
            </Badge>
          </CardFooter>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>模型实验台</CardTitle>
            <CardDescription>测试单模型响应、并行对比结果，或重新载入历史提示词。</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList variant="line" className="mb-5 w-full justify-start overflow-x-auto">
                <TabsTrigger value="single"><PlayIcon data-icon="inline-start" />单轮测试</TabsTrigger>
                <TabsTrigger value="compare"><Layers3Icon data-icon="inline-start" />模型对比</TabsTrigger>
                <TabsTrigger value="history"><HistoryIcon data-icon="inline-start" />历史记录</TabsTrigger>
              </TabsList>

              <TabsContent value="single" className="flex flex-col gap-5">
                <FieldGroup>
                  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                    <ModelSelect
                      label="Model 模型"
                      models={models}
                      value={selectedModel}
                      onValueChange={(value) => {
                        setSelectedModel(value)
                        persistPreferences(history, value)
                      }}
                    />
                    <Field>
                      <FieldLabel>响应模式</FieldLabel>
                      <ToggleGroup
                        aria-label="响应模式"
                        variant="outline"
                        value={[stream ? "stream" : "standard"]}
                        onValueChange={(values) => {
                          if (values[0]) setStream(values[0] === "stream")
                        }}
                      >
                        <ToggleGroupItem value="stream">流式</ToggleGroupItem>
                        <ToggleGroupItem value="standard">标准</ToggleGroupItem>
                      </ToggleGroup>
                    </Field>
                  </div>

                  <Field>
                    <FieldLabel>常用提示词</FieldLabel>
                    <div className="flex flex-wrap gap-2">
                      {promptTemplates.map((template) => (
                        <Button
                          key={template.label}
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => setPrompt(template.prompt)}
                        >
                          {template.label}
                        </Button>
                      ))}
                    </div>
                  </Field>

                  <Field>
                    <FieldLabel htmlFor="test-prompt">Prompt 提示词</FieldLabel>
                    <Textarea
                      id="test-prompt"
                      className="min-h-32 resize-y"
                      placeholder="输入用于测试模型的提示词…"
                      value={prompt}
                      onChange={(event) => setPrompt(event.target.value)}
                    />
                  </Field>
                </FieldGroup>

                <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
                  <CollapsibleTrigger render={<Button type="button" variant="ghost" className="w-full justify-between" />}>
                    高级参数
                    <ChevronDownIcon className={cn("transition-transform", advancedOpen && "rotate-180")} />
                  </CollapsibleTrigger>
                  <CollapsibleContent className="pt-4">
                    <FieldGroup>
                      <div className="grid gap-4 sm:grid-cols-2">
                        <Field>
                          <FieldLabel htmlFor="temperature">Temperature</FieldLabel>
                          <Input id="temperature" type="number" min="0" max="2" step="0.1" value={parameters.temperature} onChange={(event) => setParameters((current) => ({ ...current, temperature: Number(event.target.value) }))} />
                        </Field>
                        <Field>
                          <FieldLabel htmlFor="max-tokens">Max Tokens</FieldLabel>
                          <Input id="max-tokens" type="number" min="1" max="128000" value={parameters.maxTokens} onChange={(event) => setParameters((current) => ({ ...current, maxTokens: Number(event.target.value) }))} />
                        </Field>
                        <Field>
                          <FieldLabel htmlFor="top-p">Top P</FieldLabel>
                          <Input id="top-p" type="number" min="0" max="1" step="0.05" value={parameters.topP} onChange={(event) => setParameters((current) => ({ ...current, topP: Number(event.target.value) }))} />
                        </Field>
                        <Field>
                          <FieldLabel htmlFor="frequency-penalty">Frequency Penalty</FieldLabel>
                          <Input id="frequency-penalty" type="number" min="-2" max="2" step="0.1" value={parameters.frequencyPenalty} onChange={(event) => setParameters((current) => ({ ...current, frequencyPenalty: Number(event.target.value) }))} />
                        </Field>
                      </div>
                      <Field>
                        <FieldLabel htmlFor="system-prompt">System Prompt</FieldLabel>
                        <Textarea id="system-prompt" placeholder="You are a helpful assistant." value={parameters.systemPrompt} onChange={(event) => setParameters((current) => ({ ...current, systemPrompt: event.target.value }))} />
                      </Field>
                    </FieldGroup>
                  </CollapsibleContent>
                </Collapsible>

                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" size="lg" disabled={running} onClick={runSingle}>
                    {running ? <Spinner data-icon="inline-start" /> : <SendIcon data-icon="inline-start" />}
                    {running ? "生成中…" : "发送测试"}
                  </Button>
                  {running ? (
                    <Button type="button" variant="outline" size="lg" onClick={() => controllerRef.current?.abort()}>
                      <SquareIcon data-icon="inline-start" />停止
                    </Button>
                  ) : null}
                  <Button type="button" variant="ghost" size="lg" onClick={() => { setOutput(""); setMetrics(null); setError("") }}>
                    <Trash2Icon data-icon="inline-start" />清空
                  </Button>
                </div>

                <div className="overflow-hidden rounded-xl border bg-muted/25">
                  <div className="flex min-h-11 flex-wrap items-center gap-2 border-b bg-muted/45 px-4 py-2">
                    <span className="flex items-center gap-2 font-mono text-xs font-semibold">
                      <span className={cn("size-2 rounded-full bg-muted-foreground/40", running && "animate-pulse bg-primary")} />
                      RESPONSE
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      {metrics ? (
                        <><MetricBadge>{metrics.chars} chars</MetricBadge><MetricBadge>{metrics.duration.toFixed(2)}s</MetricBadge></>
                      ) : null}
                      <Button type="button" variant="ghost" size="icon-sm" aria-label="复制响应" disabled={!output} onClick={copyOutput}>
                        <ClipboardIcon />
                      </Button>
                    </div>
                  </div>
                  <pre className="min-h-64 max-h-[520px] overflow-auto whitespace-pre-wrap break-words p-5 font-sans text-sm leading-7">
                    {output || <span className="text-muted-foreground">模型响应将显示在这里。</span>}
                  </pre>
                </div>
              </TabsContent>

              <TabsContent value="compare" className="flex flex-col gap-5">
                <FieldGroup>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <ModelSelect label="模型 A" models={models} value={compareModelA} onValueChange={setCompareModelA} />
                    <ModelSelect label="模型 B" models={models} value={compareModelB} onValueChange={setCompareModelB} />
                  </div>
                  <Field>
                    <FieldLabel htmlFor="compare-prompt">对比提示词</FieldLabel>
                    <Textarea id="compare-prompt" className="min-h-28 resize-y" value={comparePrompt} onChange={(event) => setComparePrompt(event.target.value)} />
                  </Field>
                  <Button type="button" className="w-fit" size="lg" disabled={comparing} onClick={runCompare}>
                    {comparing ? <Spinner data-icon="inline-start" /> : <ZapIcon data-icon="inline-start" />}
                    {comparing ? "并行测试中…" : "开始对比"}
                  </Button>
                </FieldGroup>

                {compareResults.length ? (
                  <div className="grid gap-4 lg:grid-cols-2">
                    {compareResults.map((result) => (
                      <section key={result.model} className="min-w-0 overflow-hidden rounded-xl border">
                        <div className="flex items-center gap-2 border-b bg-muted/45 px-4 py-3">
                          <span className="truncate font-mono text-sm font-semibold">{result.model}</span>
                          <Badge variant={result.status === "error" ? "destructive" : "secondary"} className="ml-auto">
                            {result.status === "pending" ? <Spinner data-icon="inline-start" /> : null}
                            {result.status === "pending" ? "请求中" : result.duration ? `${result.duration.toFixed(2)}s` : "完成"}
                          </Badge>
                        </div>
                        <pre className="min-h-52 max-h-96 overflow-auto whitespace-pre-wrap break-words p-4 font-sans text-sm leading-7">
                          {result.content || "等待模型响应…"}
                        </pre>
                      </section>
                    ))}
                  </div>
                ) : (
                  <Empty className="min-h-56 border-y">
                    <EmptyHeader>
                      <EmptyMedia variant="icon"><Layers3Icon /></EmptyMedia>
                      <EmptyTitle>等待模型对比</EmptyTitle>
                      <EmptyDescription>选择两个模型后，将使用同一提示词并行请求。</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </TabsContent>

              <TabsContent value="history" className="flex flex-col gap-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-muted-foreground">仅保存模型、提示词与耗时，不保存 API Key。</p>
                  <Button type="button" variant="outline" size="sm" disabled={!history.length} onClick={clearHistory}>
                    <Trash2Icon data-icon="inline-start" />清空历史
                  </Button>
                </div>
                {history.length ? (
                  <div className="flex flex-col">
                    {history.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 border-b px-2 py-4 text-left outline-none transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => loadHistoryItem(item)}
                      >
                        <span className="truncate font-mono text-sm font-semibold">{item.model}</span>
                        <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Clock3Icon className="size-3.5" />{item.duration.toFixed(2)}s</span>
                        <span className="truncate text-sm text-muted-foreground">{item.prompt}</span>
                        <Badge variant={item.ok ? "secondary" : "destructive"}>{item.ok ? "成功" : "失败"}</Badge>
                      </button>
                    ))}
                  </div>
                ) : (
                  <Empty className="min-h-64 border-y">
                    <EmptyHeader>
                      <EmptyMedia variant="icon"><HistoryIcon /></EmptyMedia>
                      <EmptyTitle>暂无测试记录</EmptyTitle>
                      <EmptyDescription>完成一次生成或模型对比后，记录会出现在这里。</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
          <CardFooter className="justify-between gap-4 text-xs text-muted-foreground">
            <span>兼容 OpenAI /v1 模型与 Chat Completions 接口</span>
            <span className="font-mono">KEY: MEMORY ONLY</span>
          </CardFooter>
        </Card>
      </div>
    </section>
  )
}
