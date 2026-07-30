"use client"

import * as React from "react"
import {
  BotIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ClipboardIcon,
  Clock3Icon,
  DatabaseIcon,
  EyeIcon,
  EyeOffIcon,
  HistoryIcon,
  Layers3Icon,
  PlusIcon,
  RefreshCwIcon,
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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

const providerPresets = [
  { name: "OpenAI", provider: "openai", url: "https://api.openai.com/v1" },
  { name: "DeepSeek", provider: "deepseek", url: "https://api.deepseek.com/v1" },
  { name: "OpenRouter", provider: "openrouter", url: "https://openrouter.ai/api/v1" },
  { name: "硅基流动", provider: "siliconflow", url: "https://api.siliconflow.cn/v1" },
  { name: "通义千问", provider: "dashscope", url: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { name: "智谱 GLM", provider: "bigmodel", url: "https://open.bigmodel.cn/api/paas/v4" },
] as const

const promptTemplates = [
  { label: "自我介绍", prompt: "你好，请简单介绍一下你自己，包括你的能力和特点。" },
  { label: "概念解释", prompt: "请用一句话解释什么是大语言模型。" },
  { label: "代码生成", prompt: "写一段 TypeScript 快速排序代码，并添加必要注释。" },
  { label: "格式测试", prompt: "请用 Markdown 总结 React 的五个核心概念。" },
] as const

type Channel = {
  id: string
  name: string
  provider: string
  baseUrl: string
  hasApiKey: boolean
  enabled: boolean
  createdAt: string
  updatedAt: string
}

type StoredModel = {
  id: string
  channelId: string
  modelId: string
  displayName: string
  source: string
  enabled: boolean
  createdAt: string
  updatedAt: string
  lastSeenAt: string | null
}

type RequestRecord = {
  id: string
  channelId: string | null
  channelName: string | null
  modelId: string | null
  requestType: string
  status: string
  httpStatus: number | null
  latencyMs: number | null
  promptPreview: string | null
  inputTokens: number | null
  outputTokens: number | null
  totalTokens: number | null
  responseChars: number | null
  errorMessage: string | null
  createdAt: string
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
  models: StoredModel[]
  value: string
  onValueChange: (value: string) => void
}) {
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <Select value={value || null} onValueChange={(next) => onValueChange(next || "")}>
        <SelectTrigger className="h-10 w-full font-mono" disabled={models.length === 0}>
          <SelectValue placeholder={models.length ? "选择模型" : "请先同步或添加模型"} />
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {models.map((model) => (
              <SelectItem key={model.id} value={model.modelId}>
                {model.displayName}
              </SelectItem>
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
  const [channels, setChannels] = React.useState<Channel[]>([])
  const [channelId, setChannelId] = React.useState("")
  const [models, setModels] = React.useState<StoredModel[]>([])
  const [requests, setRequests] = React.useState<RequestRecord[]>([])
  const [loadingData, setLoadingData] = React.useState(true)
  const [syncing, setSyncing] = React.useState(false)
  const [selectedModel, setSelectedModel] = React.useState("")
  const [compareModelA, setCompareModelA] = React.useState("")
  const [compareModelB, setCompareModelB] = React.useState("")
  const [prompt, setPrompt] = React.useState("你好，请简单介绍一下你自己。")
  const [comparePrompt, setComparePrompt] = React.useState("用一句话解释什么是人工智能。")
  const [parameters, setParameters] = React.useState(defaultParameters)
  const [stream, setStream] = React.useState(true)
  const [advancedOpen, setAdvancedOpen] = React.useState(false)
  const [running, setRunning] = React.useState(false)
  const [comparing, setComparing] = React.useState(false)
  const [output, setOutput] = React.useState("")
  const [error, setError] = React.useState("")
  const [metrics, setMetrics] = React.useState<{ duration: number; chars: number } | null>(null)
  const [compareResults, setCompareResults] = React.useState<CompareResult[]>([])
  const [activeTab, setActiveTab] = React.useState("single")
  const [channelDialogOpen, setChannelDialogOpen] = React.useState(false)
  const [modelDialogOpen, setModelDialogOpen] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [showApiKey, setShowApiKey] = React.useState(false)
  const [channelDraft, setChannelDraft] = React.useState({
    name: "",
    provider: "custom",
    baseUrl: "",
    apiKey: "",
  })
  const [modelDraft, setModelDraft] = React.useState({ modelId: "", displayName: "" })
  const controllerRef = React.useRef<AbortController | null>(null)

  const activeChannel = channels.find((channel) => channel.id === channelId) || null

  const loadChannels = React.useCallback(async (preferredId?: string) => {
    const response = await fetch("/api/model-checker/channels", { cache: "no-store" })
    if (!response.ok) throw new Error(await readError(response))
    const data = (await response.json()) as { channels: Channel[] }
    setChannels(data.channels)
    setChannelId((current) => {
      const candidate = preferredId || current
      return data.channels.some((channel) => channel.id === candidate)
        ? candidate
        : data.channels[0]?.id || ""
    })
  }, [])

  const loadChannelData = React.useCallback(async (nextChannelId: string) => {
    if (!nextChannelId) {
      setModels([])
      setRequests([])
      return
    }
    const [modelResponse, requestResponse] = await Promise.all([
      fetch(`/api/model-checker/models?channelId=${encodeURIComponent(nextChannelId)}`, {
        cache: "no-store",
      }),
      fetch(`/api/model-checker/requests?channelId=${encodeURIComponent(nextChannelId)}`, {
        cache: "no-store",
      }),
    ])
    if (!modelResponse.ok) throw new Error(await readError(modelResponse))
    if (!requestResponse.ok) throw new Error(await readError(requestResponse))
    const modelData = (await modelResponse.json()) as { models: StoredModel[] }
    const requestData = (await requestResponse.json()) as { requests: RequestRecord[] }
    setModels(modelData.models)
    setRequests(requestData.requests)
    setSelectedModel((current) =>
      modelData.models.some((model) => model.modelId === current)
        ? current
        : modelData.models[0]?.modelId || "",
    )
    setCompareModelA(modelData.models[0]?.modelId || "")
    setCompareModelB(modelData.models[1]?.modelId || "")
  }, [])

  React.useEffect(() => {
    let active = true
    void loadChannels()
      .catch((requestError) => {
        if (active) setError(requestError instanceof Error ? requestError.message : "初始化失败。")
      })
      .finally(() => {
        if (active) setLoadingData(false)
      })
    return () => {
      active = false
      controllerRef.current?.abort()
    }
  }, [loadChannels])

  React.useEffect(() => {
    if (!channelId) {
      setModels([])
      setRequests([])
      return
    }
    void loadChannelData(channelId).catch((requestError) => {
      setError(requestError instanceof Error ? requestError.message : "读取渠道数据失败。")
    })
  }, [channelId, loadChannelData])

  async function createChannel() {
    if (!channelDraft.name.trim() || !channelDraft.baseUrl.trim()) {
      setError("请填写渠道名称和 Base URL。")
      return
    }
    setSaving(true)
    setError("")
    try {
      const response = await fetch("/api/model-checker/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(channelDraft),
      })
      if (!response.ok) throw new Error(await readError(response))
      const channel = (await response.json()) as Channel
      setChannelDialogOpen(false)
      setChannelDraft({ name: "", provider: "custom", baseUrl: "", apiKey: "" })
      await loadChannels(channel.id)
      toast.success("渠道已保存到本机数据库")
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "创建渠道失败。")
    } finally {
      setSaving(false)
    }
  }

  async function syncModels() {
    if (!channelId) return
    setSyncing(true)
    setError("")
    try {
      const response = await fetch(
        `/api/model-checker/channels/${encodeURIComponent(channelId)}/sync-models`,
        { method: "POST" },
      )
      if (!response.ok) throw new Error(await readError(response))
      const data = (await response.json()) as { models: StoredModel[] }
      setModels(data.models)
      setSelectedModel(data.models[0]?.modelId || "")
      setCompareModelA(data.models[0]?.modelId || "")
      setCompareModelB(data.models[1]?.modelId || "")
      await loadChannelData(channelId)
      toast.success(`已同步 ${data.models.length} 个模型`)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "同步模型失败。")
    } finally {
      setSyncing(false)
    }
  }

  async function createModel() {
    if (!channelId || !modelDraft.modelId.trim()) return
    setSaving(true)
    try {
      const response = await fetch("/api/model-checker/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channelId, ...modelDraft }),
      })
      if (!response.ok) throw new Error(await readError(response))
      setModelDialogOpen(false)
      setModelDraft({ modelId: "", displayName: "" })
      await loadChannelData(channelId)
      toast.success("模型记录已添加")
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "添加模型失败。")
    } finally {
      setSaving(false)
    }
  }

  async function deleteModel(record: StoredModel) {
    if (!window.confirm(`确认删除模型记录 ${record.modelId}？`)) return
    const response = await fetch(`/api/model-checker/models/${record.id}`, { method: "DELETE" })
    if (!response.ok) {
      setError(await readError(response))
      return
    }
    await loadChannelData(channelId)
    toast.success("模型记录已删除")
  }

  async function deleteActiveChannel() {
    if (!activeChannel || !window.confirm(`确认删除渠道 ${activeChannel.name} 及其模型记录？`)) return
    const response = await fetch(`/api/model-checker/channels/${activeChannel.id}`, {
      method: "DELETE",
    })
    if (!response.ok) {
      setError(await readError(response))
      return
    }
    await loadChannels()
    toast.success("渠道已删除")
  }

  function chatPayload(model: string, testPrompt: string, shouldStream: boolean) {
    return {
      channelId,
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
    if (!channelId || !selectedModel || !prompt.trim()) {
      setError("请先选择渠道和模型并填写提示词。")
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
      setMetrics({
        duration: (performance.now() - startedAt) / 1000,
        chars: content.length,
      })
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") {
        toast.info("已停止生成")
      } else {
        setError(requestError instanceof Error ? requestError.message : "模型请求失败。")
      }
    } finally {
      controllerRef.current = null
      setRunning(false)
      await loadChannelData(channelId)
    }
  }

  async function runCompare() {
    const chosenModels = [...new Set([compareModelA, compareModelB].filter(Boolean))]
    if (chosenModels.length < 2 || !comparePrompt.trim()) {
      setError("请选择两个不同模型并填写对比提示词。")
      return
    }
    setComparing(true)
    setCompareResults(chosenModels.map((model) => ({
      model,
      content: "",
      duration: null,
      status: "pending",
    })))
    await Promise.all(chosenModels.map(async (model) => {
      const startedAt = performance.now()
      try {
        const content = await requestStandard(model, comparePrompt)
        setCompareResults((current) => current.map((item) =>
          item.model === model
            ? { ...item, content, duration: (performance.now() - startedAt) / 1000, status: "success" }
            : item,
        ))
      } catch (requestError) {
        setCompareResults((current) => current.map((item) =>
          item.model === model
            ? {
                ...item,
                content: requestError instanceof Error ? requestError.message : "请求失败。",
                duration: (performance.now() - startedAt) / 1000,
                status: "error",
              }
            : item,
        ))
      }
    }))
    setComparing(false)
    await loadChannelData(channelId)
  }

  async function clearRequests() {
    if (!channelId) return
    const response = await fetch(
      `/api/model-checker/requests?channelId=${encodeURIComponent(channelId)}`,
      { method: "DELETE" },
    )
    if (!response.ok) {
      setError(await readError(response))
      return
    }
    setRequests([])
    toast.success("请求记录已清空")
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
            渠道、模型与请求记录保存在本机 SQLite；模型请求由本机 Next.js 发起。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline"><DatabaseIcon data-icon="inline-start" />Local SQLite</Badge>
          <Badge variant="outline"><ZapIcon data-icon="inline-start" />Stream</Badge>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive" className="mb-5">
          <AlertTitle>操作未完成</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid items-start gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="xl:sticky xl:top-[102px]">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ServerCogIcon className="size-5" />
              渠道配置
            </CardTitle>
            <CardDescription>渠道密钥加密保存在本机，不会发送到浏览器。</CardDescription>
          </CardHeader>
          <CardContent>
            <FieldGroup>
              <Field>
                <FieldLabel>当前渠道</FieldLabel>
                <Select value={channelId || null} onValueChange={(value) => setChannelId(value || "")}>
                  <SelectTrigger className="h-10 w-full" disabled={loadingData || !channels.length}>
                    <SelectValue placeholder={loadingData ? "正在读取…" : "请选择渠道"} />
                  </SelectTrigger>
                  <SelectContent alignItemWithTrigger={false}>
                    <SelectGroup>
                      {channels.map((channel) => (
                        <SelectItem key={channel.id} value={channel.id}>{channel.name}</SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </Field>

              {activeChannel ? (
                <div className="rounded-xl border bg-muted/30 p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{activeChannel.name}</span>
                    <Badge variant={activeChannel.hasApiKey ? "default" : "secondary"}>
                      {activeChannel.hasApiKey ? "密钥已保存" : "无密钥"}
                    </Badge>
                  </div>
                  <p className="mt-2 break-all font-mono text-xs leading-5 text-muted-foreground">
                    {activeChannel.baseUrl}
                  </p>
                </div>
              ) : null}

              <div className="grid grid-cols-2 gap-2">
                <Button type="button" variant="outline" onClick={() => setChannelDialogOpen(true)}>
                  <PlusIcon data-icon="inline-start" />新增渠道
                </Button>
                <Button type="button" disabled={!channelId || syncing} onClick={syncModels}>
                  {syncing ? <Spinner data-icon="inline-start" /> : <RefreshCwIcon data-icon="inline-start" />}
                  {syncing ? "同步中…" : "同步模型"}
                </Button>
              </div>

              <Button type="button" variant="outline" disabled={!channelId} onClick={() => setModelDialogOpen(true)}>
                <PlusIcon data-icon="inline-start" />手动添加模型
              </Button>
            </FieldGroup>
          </CardContent>
          <CardFooter className="justify-between gap-3 text-xs text-muted-foreground">
            <span>{models.length} 个可用模型</span>
            <Badge variant={channelId ? "default" : "secondary"}>
              {channelId ? <CheckCircle2Icon data-icon="inline-start" /> : null}
              {channelId ? "本机已连接" : "等待渠道"}
            </Badge>
          </CardFooter>
        </Card>

        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>模型实验台</CardTitle>
            <CardDescription>测试响应、管理渠道模型并查看本机请求记录。</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={activeTab} onValueChange={setActiveTab}>
              <TabsList variant="line" className="mb-5 w-full justify-start overflow-x-auto">
                <TabsTrigger value="single"><SendIcon data-icon="inline-start" />单轮测试</TabsTrigger>
                <TabsTrigger value="compare"><Layers3Icon data-icon="inline-start" />模型对比</TabsTrigger>
                <TabsTrigger value="models"><DatabaseIcon data-icon="inline-start" />模型记录</TabsTrigger>
                <TabsTrigger value="requests"><HistoryIcon data-icon="inline-start" />请求记录</TabsTrigger>
              </TabsList>

              <TabsContent value="single" className="flex flex-col gap-5">
                <FieldGroup>
                  <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                    <ModelSelect label="Model 模型" models={models} value={selectedModel} onValueChange={setSelectedModel} />
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
                        <Button key={template.label} type="button" variant="outline" size="sm" onClick={() => setPrompt(template.prompt)}>
                          {template.label}
                        </Button>
                      ))}
                    </div>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="test-prompt">Prompt 提示词</FieldLabel>
                    <Textarea id="test-prompt" className="min-h-32 resize-y" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
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
                        <Textarea id="system-prompt" value={parameters.systemPrompt} onChange={(event) => setParameters((current) => ({ ...current, systemPrompt: event.target.value }))} />
                      </Field>
                    </FieldGroup>
                  </CollapsibleContent>
                </Collapsible>

                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" size="lg" disabled={running || !selectedModel} onClick={runSingle}>
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
                      <Button type="button" variant="ghost" size="icon-sm" aria-label="复制响应" disabled={!output} onClick={async () => {
                        await navigator.clipboard.writeText(output)
                        toast.success("响应内容已复制")
                      }}>
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
                      <EmptyDescription>选择两个模型后，使用同一个提示词并行请求。</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </TabsContent>

              <TabsContent value="models" className="flex flex-col gap-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-muted-foreground">同步模型与手动模型都保存在当前渠道中。</p>
                  <Button type="button" variant="outline" size="sm" disabled={!channelId} onClick={() => setModelDialogOpen(true)}>
                    <PlusIcon data-icon="inline-start" />添加
                  </Button>
                </div>
                {models.length ? models.map((model) => (
                  <div key={model.id} className="flex items-center gap-3 rounded-xl border p-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-mono text-sm font-medium">{model.modelId}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {model.source === "synced" ? "渠道同步" : "手动添加"}
                        {model.lastSeenAt ? ` · ${new Date(model.lastSeenAt).toLocaleString("zh-CN")}` : ""}
                      </p>
                    </div>
                    <Badge variant="outline">{model.source}</Badge>
                    <Button type="button" variant="ghost" size="icon-sm" aria-label={`删除 ${model.modelId}`} onClick={() => void deleteModel(model)}>
                      <Trash2Icon />
                    </Button>
                  </div>
                )) : (
                  <Empty className="min-h-64">
                    <EmptyHeader>
                      <EmptyMedia variant="icon"><DatabaseIcon /></EmptyMedia>
                      <EmptyTitle>还没有模型记录</EmptyTitle>
                      <EmptyDescription>同步渠道模型或手动添加一个模型 ID。</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
                {activeChannel ? (
                  <div className="mt-3 flex justify-end border-t pt-4">
                    <Button type="button" variant="outline" size="sm" onClick={() => void deleteActiveChannel()}>
                      <Trash2Icon data-icon="inline-start" />删除当前渠道
                    </Button>
                  </div>
                ) : null}
              </TabsContent>

              <TabsContent value="requests" className="flex flex-col gap-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-muted-foreground">记录状态、耗时、Token 用量与错误，不保存完整响应。</p>
                  <Button type="button" variant="outline" size="sm" disabled={!requests.length} onClick={() => void clearRequests()}>
                    <Trash2Icon data-icon="inline-start" />清空
                  </Button>
                </div>
                {requests.length ? requests.map((record) => (
                  <div key={record.id} className="rounded-xl border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={record.status === "success" ? "default" : record.status === "error" ? "destructive" : "secondary"}>
                        {record.status}
                      </Badge>
                      <span className="font-mono text-sm">{record.modelId || record.requestType}</span>
                      <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                        <Clock3Icon className="size-3.5" />
                        {record.latencyMs === null ? "—" : `${record.latencyMs} ms`}
                      </span>
                    </div>
                    {record.promptPreview ? <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{record.promptPreview}</p> : null}
                    {record.errorMessage ? <p className="mt-2 text-sm text-destructive">{record.errorMessage}</p> : null}
                    <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span>{new Date(record.createdAt).toLocaleString("zh-CN")}</span>
                      {record.httpStatus ? <span>HTTP {record.httpStatus}</span> : null}
                      {record.totalTokens !== null ? <span>{record.totalTokens} tokens</span> : null}
                      {record.responseChars !== null ? <span>{record.responseChars} chars</span> : null}
                    </div>
                  </div>
                )) : (
                  <Empty className="min-h-64">
                    <EmptyHeader>
                      <EmptyMedia variant="icon"><HistoryIcon /></EmptyMedia>
                      <EmptyTitle>暂无请求记录</EmptyTitle>
                      <EmptyDescription>模型同步和聊天测试完成后会自动记录在本机数据库。</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>

      <Dialog open={channelDialogOpen} onOpenChange={setChannelDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>新增模型渠道</DialogTitle>
            <DialogDescription>API Key 会加密后保存到本机 data/model_tester.sqlite3。</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel>服务商预设</FieldLabel>
              <div className="flex flex-wrap gap-2">
                {providerPresets.map((preset) => (
                  <Button
                    key={preset.provider}
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setChannelDraft((current) => ({
                      ...current,
                      name: preset.name,
                      provider: preset.provider,
                      baseUrl: preset.url,
                    }))}
                  >
                    {preset.name}
                  </Button>
                ))}
              </div>
            </Field>
            <Field>
              <FieldLabel htmlFor="channel-name">渠道名称</FieldLabel>
              <Input id="channel-name" value={channelDraft.name} onChange={(event) => setChannelDraft((current) => ({ ...current, name: event.target.value }))} />
            </Field>
            <Field>
              <FieldLabel htmlFor="channel-base-url">Base URL</FieldLabel>
              <Input id="channel-base-url" placeholder="https://api.example.com/v1" value={channelDraft.baseUrl} onChange={(event) => setChannelDraft((current) => ({ ...current, baseUrl: event.target.value }))} />
            </Field>
            <Field>
              <FieldLabel htmlFor="channel-api-key">API Key</FieldLabel>
              <InputGroup>
                <InputGroupInput id="channel-api-key" type={showApiKey ? "text" : "password"} autoComplete="off" value={channelDraft.apiKey} onChange={(event) => setChannelDraft((current) => ({ ...current, apiKey: event.target.value }))} />
                <InputGroupAddon align="inline-end">
                  <InputGroupButton size="icon-xs" aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"} onClick={() => setShowApiKey((current) => !current)}>
                    {showApiKey ? <EyeOffIcon /> : <EyeIcon />}
                  </InputGroupButton>
                </InputGroupAddon>
              </InputGroup>
              <FieldDescription>不需要密钥的本地服务可以留空。</FieldDescription>
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setChannelDialogOpen(false)}>取消</Button>
            <Button type="button" disabled={saving} onClick={createChannel}>
              {saving ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
              保存渠道
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={modelDialogOpen} onOpenChange={setModelDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>手动添加模型</DialogTitle>
            <DialogDescription>适用于模型列表接口未返回但实际可调用的模型。</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel htmlFor="manual-model-id">模型 ID</FieldLabel>
              <Input id="manual-model-id" className="font-mono" value={modelDraft.modelId} onChange={(event) => setModelDraft((current) => ({ ...current, modelId: event.target.value }))} />
            </Field>
            <Field>
              <FieldLabel htmlFor="manual-model-name">显示名称（可选）</FieldLabel>
              <Input id="manual-model-name" value={modelDraft.displayName} onChange={(event) => setModelDraft((current) => ({ ...current, displayName: event.target.value }))} />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setModelDialogOpen(false)}>取消</Button>
            <Button type="button" disabled={saving || !modelDraft.modelId.trim()} onClick={createModel}>
              {saving ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
              添加模型
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
