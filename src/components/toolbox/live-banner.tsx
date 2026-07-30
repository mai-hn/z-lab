"use client"

import * as React from "react"
import useSWR from "swr"
import {
  CheckIcon,
  ClipboardIcon,
  Clock3Icon,
  CloudSunIcon,
  DropletsIcon,
  Globe2Icon,
  QuoteIcon,
  RefreshCwIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type ApiPayload = { fetched_at: number }
type SayingData = ApiPayload & { text: string }
type WorldTimeData = ApiPayload & {
  offset_string: string
  timestamp_unix: number
  timezone: string
}
type WeatherData = ApiPayload & {
  province: string
  city: string
  district?: string
  weather: string
  temperature: number
  humidity: number
}
type MyIpData = ApiPayload & {
  ip: string
  region: string
  isp: string
  llc?: string
}

async function apiFetcher<T>(url: string): Promise<T> {
  const response = await fetch(url)
  const payload = (await response.json()) as T & { message?: string }

  if (!response.ok) {
    throw new Error(payload.message || "请求失败，请稍后重试。")
  }

  return payload
}

function BannerLoading({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3", className)} aria-label="正在加载">
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-4 w-full" />
    </div>
  )
}

function BannerError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Alert variant="destructive" className="py-3">
      <AlertDescription className="flex items-center justify-between gap-2">
        <span className="line-clamp-2 text-xs">{message}</span>
        <Button type="button" variant="ghost" size="icon-sm" aria-label="重新请求" onClick={onRetry}>
          <RefreshCwIcon />
        </Button>
      </AlertDescription>
    </Alert>
  )
}

function TileHeader({
  icon: Icon,
  label,
  loading,
  onRefresh,
}: {
  icon: React.ComponentType<React.SVGProps<SVGSVGElement>>
  label: string
  loading: boolean
  onRefresh: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <Icon className="size-4" strokeWidth={1.8} />
        <span>{label}</span>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label={`刷新${label}`}
        disabled={loading}
        onClick={onRefresh}
      >
        <RefreshCwIcon className={cn(loading && "animate-spin")} />
      </Button>
    </div>
  )
}

function SayingTile() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<SayingData>(
    "/api/tools/saying",
    apiFetcher,
    { revalidateOnFocus: false },
  )

  return (
    <section className="col-span-2 flex min-h-44 flex-col border-b border-border/70 p-5 sm:p-6 lg:col-span-1 lg:border-b-0 lg:border-r">
      <TileHeader icon={QuoteIcon} label="每日一言" loading={isValidating} onRefresh={() => void mutate()} />
      <div className="flex flex-1 items-center py-4" aria-live="polite">
        {isLoading ? <BannerLoading className="w-full" /> : null}
        {error ? <BannerError message={error.message} onRetry={() => void mutate()} /> : null}
        {data ? (
          <blockquote className="text-xl font-semibold leading-relaxed tracking-[-0.035em] text-balance sm:text-2xl">
            <span className="mr-2 text-primary">“</span>
            {data.text}
            <span>”</span>
          </blockquote>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">点击刷新，遇见一句新的话</p>
    </section>
  )
}

function WeatherTile() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<WeatherData>(
    "/api/tools/weather",
    apiFetcher,
    { revalidateOnFocus: false, refreshInterval: 10 * 60 * 1000 },
  )

  return (
    <section className="flex min-h-44 flex-col border-b border-r border-border/70 p-5 lg:border-b-0">
      <TileHeader icon={CloudSunIcon} label="天气" loading={isValidating} onRefresh={() => void mutate()} />
      <div className="flex flex-1 flex-col justify-center py-3" aria-live="polite">
        {isLoading ? <BannerLoading /> : null}
        {error ? <BannerError message={error.message} onRetry={() => void mutate()} /> : null}
        {data ? (
          <>
            <div className="flex items-end gap-2">
              <span className="text-4xl font-semibold tracking-[-0.07em] tabular-nums">{data.temperature}°</span>
              <span className="pb-1 text-sm font-medium">{data.weather}</span>
            </div>
            <p className="mt-2 truncate text-xs text-muted-foreground">
              {[data.province, data.city, data.district].filter(Boolean).join(" · ")}
            </p>
          </>
        ) : null}
      </div>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <DropletsIcon className="size-3.5" />
        湿度 {data?.humidity ?? "--"}%
      </p>
    </section>
  )
}

function WorldTimeTile() {
  const [now, setNow] = React.useState(() => Date.now())
  const { data, error, isLoading, isValidating, mutate } = useSWR<WorldTimeData>(
    "/api/tools/worldtime",
    apiFetcher,
    { revalidateOnFocus: false, refreshInterval: 10 * 60 * 1000 },
  )

  React.useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const clock = React.useMemo(() => {
    if (!data) return null
    const current = new Date(data.timestamp_unix * 1000 + Math.max(0, now - data.fetched_at))
    return {
      time: new Intl.DateTimeFormat("zh-CN", {
        timeZone: data.timezone,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(current),
      date: new Intl.DateTimeFormat("zh-CN", {
        timeZone: data.timezone,
        month: "numeric",
        day: "numeric",
        weekday: "short",
      }).format(current),
    }
  }, [data, now])

  return (
    <section className="flex min-h-44 flex-col border-b border-border/70 p-5 lg:border-b-0 lg:border-r">
      <TileHeader icon={Clock3Icon} label="世界时间" loading={isValidating} onRefresh={() => void mutate()} />
      <div className="flex flex-1 flex-col justify-center py-3" aria-live="polite">
        {isLoading ? <BannerLoading /> : null}
        {error ? <BannerError message={error.message} onRetry={() => void mutate()} /> : null}
        {clock ? (
          <>
            <div className="font-mono text-3xl font-semibold tabular-nums tracking-[-0.055em] sm:text-4xl">{clock.time}</div>
            <p className="mt-2 text-xs text-muted-foreground">{clock.date}</p>
          </>
        ) : null}
      </div>
      <p className="truncate font-mono text-xs text-muted-foreground">
        {data ? (
          <>
            <span className="sm:hidden">{data.timezone.split("/").pop()}</span>
            <span className="hidden sm:inline">{data.timezone}</span>
            {` · ${data.offset_string}`}
          </>
        ) : (
          "IANA timezone"
        )}
      </p>
    </section>
  )
}

function MyIpTile() {
  const [copied, setCopied] = React.useState(false)
  const { data, error, isLoading, isValidating, mutate } = useSWR<MyIpData>(
    "/api/tools/myip",
    apiFetcher,
    { revalidateOnFocus: false },
  )

  async function copyIp() {
    if (!data) return
    try {
      await navigator.clipboard.writeText(data.ip)
      setCopied(true)
      toast.success("IP 地址已复制")
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      toast.error("复制失败，请手动复制。")
    }
  }

  return (
    <section className="col-span-2 flex min-h-44 flex-col p-5 lg:col-span-1">
      <TileHeader icon={Globe2Icon} label="我的 IP" loading={isValidating} onRefresh={() => void mutate()} />
      <div className="flex flex-1 flex-col justify-center py-3" aria-live="polite">
        {isLoading ? <BannerLoading /> : null}
        {error ? <BannerError message={error.message} onRetry={() => void mutate()} /> : null}
        {data ? (
          <button
            type="button"
            className="flex max-w-full items-center gap-2 rounded-md text-left font-mono text-xl font-semibold tracking-[-0.04em] outline-none transition-colors hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
            onClick={copyIp}
          >
            <span className="truncate">{data.ip}</span>
            {copied ? <CheckIcon className="size-4 shrink-0" /> : <ClipboardIcon className="size-4 shrink-0" />}
          </button>
        ) : null}
        <p className="mt-2 truncate text-xs text-muted-foreground">{data?.region || "正在检测出口网络"}</p>
      </div>
      <p className="truncate text-xs text-muted-foreground">{data?.llc || data?.isp || "公网网络信息"}</p>
    </section>
  )
}

export function LiveBanner() {
  return (
    <Card className="gap-0 overflow-hidden border-border/80 bg-card/90 py-0 shadow-[0_22px_70px_var(--module-shadow)]">
      <CardHeader className="sr-only">
        <CardTitle>实时信息</CardTitle>
        <CardDescription>每日一言、天气、世界时间和公网 IP。</CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-2 px-0 lg:grid-cols-[1.65fr_0.8fr_1fr_1fr]">
        <SayingTile />
        <WeatherTile />
        <WorldTimeTile />
        <MyIpTile />
      </CardContent>
      <CardFooter className="min-h-11 justify-between gap-4 border-t border-border/70 bg-muted/35 px-5 text-xs text-muted-foreground sm:px-6">
        <span>实时信息 · 默认每 10 分钟更新</span>
        <span className="flex shrink-0 items-center gap-2 font-mono">
          <span className="size-2 rounded-full bg-primary shadow-[0_0_0_4px_var(--accent-shadow)]" />
          UAPI ONLINE
        </span>
      </CardFooter>
    </Card>
  )
}
