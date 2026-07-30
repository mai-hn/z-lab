"use client"

import * as React from "react"
import {
  ArchiveIcon,
  ChevronRightIcon,
  CloudIcon,
  CloudDownloadIcon,
  CopyIcon,
  DownloadIcon,
  FileIcon,
  FileImageIcon,
  FileTextIcon,
  FolderIcon,
  FolderOpenIcon,
  HardDriveIcon,
  KeyRoundIcon,
  LockKeyholeIcon,
  LogOutIcon,
  MoveRightIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  SquareIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type DriveEntry = {
  name: string
  path: string
  type: "file" | "directory"
  size: number
  modifiedAt: string
}

type DriveListing = {
  ok: boolean
  path: string
  entries: DriveEntry[]
}

type DriveSession = {
  configured: boolean
  protected: boolean
  authorized: boolean
}

type OfflineDownloadResult = {
  url: string
  status: "completed" | "failed" | "canceled"
  entry?: DriveEntry
  error?: string
}

type OfflineDownloadJob = {
  ok: boolean
  jobId: string
  status:
    | "queued"
    | "pending"
    | "downloading"
    | "canceling"
    | "completed"
    | "canceled"
    | "failed"
  path?: string
  total?: number
  completed?: number
  failed?: number
  currentIndex?: number | null
  currentUrl?: string | null
  currentFileName?: string | null
  currentBytes?: number
  currentTotalBytes?: number | null
  bytesPerSecond?: number
  totalBytesDownloaded?: number
  error?: string
  legacy?: boolean
  results?: OfflineDownloadResult[]
}

type TransferJob = {
  ok: boolean
  jobId: string
  operation: "copy" | "move"
  status:
    | "queued"
    | "preparing"
    | "transferring"
    | "finalizing"
    | "canceling"
    | "completed"
    | "canceled"
    | "failed"
  sourcePath: string
  destinationPath: string
  currentBytes?: number
  currentTotalBytes?: number | null
  bytesPerSecond?: number
  currentFileName?: string | null
  completedFiles?: number
  totalFiles?: number | null
  entry?: DriveEntry
  error?: string
}

const ACTIVE_OFFLINE_STATUSES = new Set([
  "queued",
  "pending",
  "downloading",
  "canceling",
])

function isOfflineDownloadActive(status?: string) {
  return Boolean(status && ACTIVE_OFFLINE_STATUSES.has(status))
}

const ACTIVE_TRANSFER_STATUSES = new Set([
  "queued",
  "preparing",
  "transferring",
  "finalizing",
  "canceling",
])

function isTransferActive(status?: string) {
  return Boolean(status && ACTIVE_TRANSFER_STATUSES.has(status))
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return bytes === 0 ? "0 B" : "—"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** index
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function joinPath(directory: string, name: string) {
  return `${directory === "/" ? "" : directory}/${name}`
}

function OfflineDownloadProgress({
  job,
  stopping,
  onStop,
}: {
  job: OfflineDownloadJob
  stopping: boolean
  onStop: () => void
}) {
  const currentBytes = job.currentBytes || 0
  const currentTotalBytes = job.currentTotalBytes || 0
  const percentage =
    currentTotalBytes > 0
      ? Math.min(100, Math.max(0, (currentBytes / currentTotalBytes) * 100))
      : null
  const canceling = job.status === "canceling"
  const title =
    job.legacy
      ? "旧版本任务运行中"
      : job.status === "queued" || job.status === "pending"
      ? "任务排队中"
      : canceling
        ? "正在停止下载"
        : `正在下载 ${job.currentIndex || 1} / ${job.total || 1}`

  return (
    <div className="space-y-3 rounded-xl border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Spinner className="size-3.5" />
            {title}
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {canceling
              ? "等待 worker 清理当前临时文件…"
              : job.currentFileName ||
                job.currentUrl ||
                (job.legacy
                  ? "旧任务不提供字节进度，但可以强制停止。"
                  : "等待 Modal worker 接收任务…")}
          </p>
        </div>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={stopping || canceling}
          onClick={onStop}
        >
          {stopping || canceling ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <SquareIcon data-icon="inline-start" />
          )}
          {canceling ? "停止中" : "停止下载"}
        </Button>
      </div>

      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="当前文件下载进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percentage === null ? undefined : Math.round(percentage)}
      >
        <div
          className={cn(
            "h-full rounded-full bg-primary transition-[width] duration-300",
            percentage === null && "w-1/3 animate-pulse",
          )}
          style={percentage === null ? undefined : { width: `${percentage}%` }}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs tabular-nums text-muted-foreground">
        <span>
          {formatBytes(currentBytes)}
          {currentTotalBytes > 0 ? ` / ${formatBytes(currentTotalBytes)}` : ""}
          {percentage !== null ? ` · ${percentage.toFixed(1)}%` : ""}
        </span>
        <span>
          {job.bytesPerSecond ? `${formatBytes(job.bytesPerSecond)}/s · ` : ""}
          已完成 {job.completed || 0} · 失败 {job.failed || 0}
        </span>
      </div>
    </div>
  )
}

function TransferProgress({
  job,
  stopping,
  onStop,
}: {
  job: TransferJob
  stopping: boolean
  onStop: () => void
}) {
  const currentBytes = job.currentBytes || 0
  const currentTotalBytes = job.currentTotalBytes || 0
  const percentage =
    currentTotalBytes > 0
      ? Math.min(100, Math.max(0, (currentBytes / currentTotalBytes) * 100))
      : null
  const canceling = job.status === "canceling"
  const operationName = job.operation === "copy" ? "复制" : "移动"
  const title =
    job.status === "queued"
      ? `${operationName}任务排队中`
      : job.status === "preparing"
        ? `正在统计${operationName}内容`
        : job.status === "finalizing"
          ? `正在完成${operationName}`
          : canceling
            ? `正在停止${operationName}`
            : `正在${operationName}`

  return (
    <div className="space-y-3 rounded-xl border bg-muted/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Spinner className="size-3.5" />
            {title}
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {canceling
              ? "等待 worker 停止当前 rclone 进程…"
              : job.currentFileName || `${job.sourcePath} → ${job.destinationPath}`}
          </p>
        </div>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          disabled={stopping || canceling || job.status === "finalizing"}
          onClick={onStop}
        >
          {stopping || canceling ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <SquareIcon data-icon="inline-start" />
          )}
          {canceling ? "停止中" : "停止任务"}
        </Button>
      </div>

      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label={`${operationName}进度`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percentage === null ? undefined : Math.round(percentage)}
      >
        <div
          className={cn(
            "h-full rounded-full bg-primary transition-[width] duration-300",
            percentage === null && "w-1/3 animate-pulse",
          )}
          style={percentage === null ? undefined : { width: `${percentage}%` }}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs tabular-nums text-muted-foreground">
        <span>
          {formatBytes(currentBytes)}
          {currentTotalBytes > 0 ? ` / ${formatBytes(currentTotalBytes)}` : ""}
          {percentage !== null ? ` · ${percentage.toFixed(1)}%` : ""}
        </span>
        <span>
          {job.bytesPerSecond ? `${formatBytes(job.bytesPerSecond)}/s · ` : ""}
          已完成 {job.completedFiles || 0}
          {job.totalFiles ? ` / ${job.totalFiles}` : ""} 个文件
        </span>
      </div>
    </div>
  )
}

function EntryGlyph({ entry }: { entry: DriveEntry }) {
  if (entry.type === "directory") return <FolderIcon className="size-4.5" />
  const extension = entry.name.split(".").pop()?.toLowerCase() || ""
  if (["png", "jpg", "jpeg", "gif", "webp", "svg", "avif"].includes(extension)) {
    return <FileImageIcon className="size-4.5" />
  }
  if (["zip", "tar", "gz", "7z", "rar"].includes(extension)) {
    return <ArchiveIcon className="size-4.5" />
  }
  if (["txt", "md", "json", "csv", "log", "pdf", "doc", "docx"].includes(extension)) {
    return <FileTextIcon className="size-4.5" />
  }
  return <FileIcon className="size-4.5" />
}

async function responseMessage(response: Response) {
  const payload = (await response.json().catch(() => null)) as {
    message?: unknown
    detail?: unknown
    code?: string
  } | null

  function readableDetail(value: unknown): string | null {
    if (typeof value === "string" && value.trim()) return value
    if (Array.isArray(value)) {
      const messages = value
        .map((item) => {
          if (!item || typeof item !== "object") return readableDetail(item)
          const detail = item as { loc?: unknown; msg?: unknown }
          const message =
            typeof detail.msg === "string" ? detail.msg.trim() : ""
          const location = Array.isArray(detail.loc)
            ? detail.loc.filter((part) => typeof part === "string").join(".")
            : ""
          if (!message) return null
          return location ? `${location}：${message}` : message
        })
        .filter((message): message is string => Boolean(message))
      return messages.length ? messages.join("；") : null
    }
    if (value && typeof value === "object") {
      try {
        return JSON.stringify(value)
      } catch {
        return null
      }
    }
    return null
  }

  return {
    message:
      readableDetail(payload?.message) ||
      readableDetail(payload?.detail) ||
      `请求失败（HTTP ${response.status}）`,
    code: payload?.code,
  }
}

function PathBreadcrumbs({
  path,
  onNavigate,
}: {
  path: string
  onNavigate: (path: string) => void
}) {
  const parts = path.split("/").filter(Boolean)

  return (
    <nav className="flex min-w-0 items-center gap-0.5 overflow-x-auto" aria-label="网盘路径">
      <Button type="button" variant="ghost" size="sm" onClick={() => onNavigate("/")}>
        <HardDriveIcon data-icon="inline-start" />
        根目录
      </Button>
      {parts.map((part, index) => {
        const target = `/${parts.slice(0, index + 1).join("/")}`
        return (
          <React.Fragment key={target}>
            <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground" />
            <Button type="button" variant="ghost" size="sm" onClick={() => onNavigate(target)}>
              {part}
            </Button>
          </React.Fragment>
        )
      })}
    </nav>
  )
}

function DriveRow({
  entry,
  onOpen,
  onRename,
  onCopy,
  onMove,
  onDelete,
}: {
  entry: DriveEntry
  onOpen: (entry: DriveEntry) => void
  onRename: (entry: DriveEntry) => void
  onCopy: (entry: DriveEntry) => void
  onMove: (entry: DriveEntry) => void
  onDelete: (entry: DriveEntry) => void
}) {
  const isCloudRoot =
    entry.path === "/Cloud" || /^\/Cloud\/[^/]+$/.test(entry.path)

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b px-3 py-2.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_100px_140px_auto] sm:px-4">
      <Button
        type="button"
        variant="ghost"
        className="h-auto min-w-0 justify-start px-1 py-1"
        onClick={() => onOpen(entry)}
      >
        <span className={cn(
          "grid size-9 shrink-0 place-items-center rounded-lg",
          entry.type === "directory" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
        )}>
          <EntryGlyph entry={entry} />
        </span>
        <span className="min-w-0 truncate text-left">{entry.name}</span>
      </Button>
      <span className="hidden text-xs tabular-nums text-muted-foreground sm:block">
        {entry.type === "directory" ? "文件夹" : formatBytes(entry.size)}
      </span>
      <span className="hidden text-xs tabular-nums text-muted-foreground sm:block">
        {formatDate(entry.modifiedAt)}
      </span>
      <div className="flex items-center justify-end gap-1">
        {entry.type === "file" ? (
          <a
            href={`/api/modal-drive/download?path=${encodeURIComponent(entry.path)}`}
            aria-label={`下载 ${entry.name}`}
            className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
          >
            <DownloadIcon />
          </a>
        ) : null}
        {!isCloudRoot ? (
          <>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`复制 ${entry.name}`}
              onClick={() => onCopy(entry)}
            >
              <CopyIcon />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`移动 ${entry.name}`}
              onClick={() => onMove(entry)}
            >
              <MoveRightIcon />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`重命名 ${entry.name}`}
              onClick={() => onRename(entry)}
            >
              <PencilIcon />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={`删除 ${entry.name}`}
              onClick={() => onDelete(entry)}
            >
              <Trash2Icon />
            </Button>
          </>
        ) : null}
      </div>
    </div>
  )
}

export function ModalDrive() {
  const [session, setSession] = React.useState<DriveSession | null>(null)
  const [password, setPassword] = React.useState("")
  const [unlocking, setUnlocking] = React.useState(false)
  const [path, setPath] = React.useState("/")
  const [entries, setEntries] = React.useState<DriveEntry[]>([])
  const [query, setQuery] = React.useState("")
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState("")
  const [dragging, setDragging] = React.useState(false)
  const [uploading, setUploading] = React.useState(false)
  const [uploadStatus, setUploadStatus] = React.useState("")
  const [folderOpen, setFolderOpen] = React.useState(false)
  const [folderName, setFolderName] = React.useState("")
  const [renameTarget, setRenameTarget] = React.useState<DriveEntry | null>(null)
  const [renameName, setRenameName] = React.useState("")
  const [transferTarget, setTransferTarget] = React.useState<DriveEntry | null>(null)
  const [transferOperation, setTransferOperation] = React.useState<"copy" | "move">("copy")
  const [transferDestination, setTransferDestination] = React.useState("")
  const [transferJob, setTransferJob] = React.useState<TransferJob | null>(null)
  const [transferStopping, setTransferStopping] = React.useState(false)
  const [deleteTarget, setDeleteTarget] = React.useState<DriveEntry | null>(null)
  const [offlineOpen, setOfflineOpen] = React.useState(false)
  const [offlineLinks, setOfflineLinks] = React.useState("")
  const [offlineSubmitting, setOfflineSubmitting] = React.useState(false)
  const [offlineStopping, setOfflineStopping] = React.useState(false)
  const [offlineJob, setOfflineJob] = React.useState<OfflineDownloadJob | null>(null)
  const [mutating, setMutating] = React.useState(false)
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const isCloudIndex = path === "/Cloud"

  const handleUnauthorized = React.useCallback(() => {
    setSession((current) => current ? { ...current, authorized: false } : current)
    setEntries([])
  }, [])

  const loadFiles = React.useCallback(async (nextPath: string) => {
    setLoading(true)
    setError("")
    try {
      const response = await fetch(`/api/modal-drive/files?path=${encodeURIComponent(nextPath)}`, {
        cache: "no-store",
      })
      if (!response.ok) {
        const details = await responseMessage(response)
        if (response.status === 401) handleUnauthorized()
        throw new Error(details.message)
      }
      const listing = (await response.json()) as DriveListing
      setPath(listing.path)
      setEntries(listing.entries)
      setQuery("")
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "无法读取目录。")
    } finally {
      setLoading(false)
    }
  }, [handleUnauthorized])

  React.useEffect(() => {
    let active = true
    void fetch("/api/modal-drive/session", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("无法读取网盘配置。")
        return response.json() as Promise<DriveSession>
      })
      .then((nextSession) => {
        if (!active) return
        setSession(nextSession)
        if (nextSession.configured && nextSession.authorized) {
          void loadFiles("/")
        }
      })
      .catch((requestError) => {
        if (active) setError(requestError instanceof Error ? requestError.message : "初始化失败。")
      })
    return () => {
      active = false
    }
  }, [loadFiles])

  const offlineJobId = offlineJob?.jobId
  const offlineJobPath = offlineJob?.path
  const offlineJobStatus = offlineJob?.status

  React.useEffect(() => {
    if (!offlineJobId || !isOfflineDownloadActive(offlineJobStatus)) {
      return
    }

    const jobId = offlineJobId
    let disposed = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const jobPath = offlineJobPath

    async function poll() {
      try {
        const response = await fetch(
          `/api/modal-drive/offline-download?jobId=${encodeURIComponent(jobId)}`,
          { cache: "no-store" },
        )
        if (!response.ok) {
          const details = await responseMessage(response)
          if (response.status === 401) handleUnauthorized()
          throw new Error(details.message)
        }

        const payload = (await response.json()) as OfflineDownloadJob
        if (disposed) return
        setOfflineJob((current) =>
          current?.jobId === jobId ? { ...current, ...payload } : current,
        )

        if (!isOfflineDownloadActive(payload.status)) {
          const completed = payload.completed || 0
          const failed = payload.failed || 0
          if (completed > 0 && (payload.path || jobPath) === path) {
            await loadFiles(path)
          }
          if (payload.status === "canceled") {
            toast.info(`离线下载已停止，已保存 ${completed} 个文件`)
          } else if (payload.status === "failed") {
            toast.error(payload.error || "离线下载任务失败")
          } else if (failed > 0) {
            toast.warning(`离线下载完成：成功 ${completed} 个，失败 ${failed} 个`)
          } else {
            toast.success(`离线下载完成：已保存 ${completed} 个文件`)
          }
          return
        }

        timer = setTimeout(poll, 1_000)
      } catch (requestError) {
        if (disposed) return
        const message =
          requestError instanceof Error ? requestError.message : "无法读取下载状态。"
        setOfflineJob((current) =>
          current && current.jobId === jobId
            ? { ...current, status: "failed" }
            : current,
        )
        setError(message)
      }
    }

    timer = setTimeout(poll, 1_000)
    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
    }
  }, [
    handleUnauthorized,
    loadFiles,
    offlineJobId,
    offlineJobPath,
    offlineJobStatus,
    path,
  ])

  const transferJobId = transferJob?.jobId
  const transferJobStatus = transferJob?.status

  React.useEffect(() => {
    if (!transferJobId || !isTransferActive(transferJobStatus)) return

    const jobId = transferJobId
    let disposed = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      try {
        const response = await fetch(
          `/api/modal-drive/transfer?jobId=${encodeURIComponent(jobId)}`,
          { cache: "no-store" },
        )
        if (!response.ok) {
          const details = await responseMessage(response)
          if (response.status === 401) handleUnauthorized()
          throw new Error(details.message)
        }

        const payload = (await response.json()) as TransferJob
        if (disposed) return
        setTransferJob((current) =>
          current?.jobId === jobId ? { ...current, ...payload } : current,
        )

        if (!isTransferActive(payload.status)) {
          if (payload.status === "completed") {
            toast.success(payload.operation === "copy" ? "复制完成" : "移动完成")
            await loadFiles(path)
          } else if (payload.status === "canceled") {
            toast.info(payload.operation === "copy" ? "复制已停止" : "移动已停止")
          } else {
            toast.error(payload.error || "文件传输失败")
          }
          return
        }
        timer = setTimeout(poll, 1_000)
      } catch (requestError) {
        if (disposed) return
        const message =
          requestError instanceof Error ? requestError.message : "无法读取传输状态。"
        setTransferJob((current) =>
          current?.jobId === jobId ? { ...current, status: "failed" } : current,
        )
        setError(message)
      }
    }

    timer = setTimeout(poll, 500)
    return () => {
      disposed = true
      if (timer) clearTimeout(timer)
    }
  }, [
    handleUnauthorized,
    loadFiles,
    path,
    transferJobId,
    transferJobStatus,
  ])

  const filteredEntries = React.useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return entries
    return entries.filter((entry) => entry.name.toLocaleLowerCase().includes(normalized))
  }, [entries, query])

  const totalSize = React.useMemo(
    () => entries.reduce((total, entry) => total + (entry.type === "file" ? entry.size : 0), 0),
    [entries],
  )

  async function unlock(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!password) return
    setUnlocking(true)
    setError("")
    try {
      const response = await fetch("/api/modal-drive/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      })
      if (!response.ok) throw new Error((await responseMessage(response)).message)
      setPassword("")
      setSession((current) => current ? { ...current, authorized: true } : current)
      await loadFiles("/")
      toast.success("Modal 网盘已解锁")
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "解锁失败。")
    } finally {
      setUnlocking(false)
    }
  }

  async function lockDrive() {
    await fetch("/api/modal-drive/session", { method: "DELETE" })
    setSession((current) => current ? { ...current, authorized: false } : current)
    setEntries([])
    setPath("/")
    toast.success("网盘已锁定")
  }

  async function uploadFiles(files: FileList | File[]) {
    const selectedFiles = Array.from(files)
    if (selectedFiles.length === 0) return
    if (isCloudIndex) {
      setError("请先进入 Cloud 中的一个远程网盘文件夹。")
      return
    }

    setUploading(true)
    setError("")
    let completed = 0
    try {
      for (const file of selectedFiles) {
        setUploadStatus(`${completed + 1} / ${selectedFiles.length} · ${file.name}`)
        const body = new FormData()
        body.append("file", file)
        const response = await fetch(`/api/modal-drive/upload?path=${encodeURIComponent(path)}`, {
          method: "POST",
          body,
        })
        if (!response.ok) {
          const details = await responseMessage(response)
          if (response.status === 401) handleUnauthorized()
          throw new Error(`${file.name}：${details.message}`)
        }
        completed += 1
      }
      toast.success(`已上传 ${completed} 个文件`)
      await loadFiles(path)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "上传失败。")
    } finally {
      setUploading(false)
      setUploadStatus("")
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  async function createFolder() {
    const name = folderName.trim()
    if (!name || name.includes("/") || name.includes("\\")) {
      setError("文件夹名称不能包含路径分隔符。")
      return
    }

    setMutating(true)
    try {
      const response = await fetch("/api/modal-drive/folders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: joinPath(path, name) }),
      })
      if (!response.ok) throw new Error((await responseMessage(response)).message)
      setFolderOpen(false)
      setFolderName("")
      toast.success("文件夹已创建")
      await loadFiles(path)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "创建文件夹失败。")
    } finally {
      setMutating(false)
    }
  }

  async function startOfflineDownload() {
    const urls = offlineLinks
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean)
    if (urls.length === 0) {
      setError("请至少输入一个下载链接。")
      return
    }
    if (urls.length > 50) {
      setError("每个离线下载任务最多支持 50 个链接。")
      return
    }

    setOfflineSubmitting(true)
    setError("")
    try {
      const response = await fetch("/api/modal-drive/offline-download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, urls }),
      })
      if (!response.ok) {
        const details = await responseMessage(response)
        if (response.status === 401) handleUnauthorized()
        throw new Error(details.message)
      }
      const job = (await response.json()) as OfflineDownloadJob
      setOfflineJob(job)
      toast.success(`已提交 ${urls.length} 个链接，将按顺序下载`)
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "提交离线下载失败。",
      )
    } finally {
      setOfflineSubmitting(false)
    }
  }

  async function stopOfflineDownload() {
    if (!offlineJob?.jobId || !isOfflineDownloadActive(offlineJob.status)) return

    setOfflineStopping(true)
    setError("")
    try {
      const response = await fetch(
        `/api/modal-drive/offline-download?jobId=${encodeURIComponent(offlineJob.jobId)}`,
        { method: "DELETE" },
      )
      if (!response.ok) {
        const details = await responseMessage(response)
        if (response.status === 401) handleUnauthorized()
        throw new Error(details.message)
      }
      const payload = (await response.json()) as OfflineDownloadJob
      setOfflineJob((current) =>
        current?.jobId === payload.jobId ? { ...current, ...payload } : current,
      )
      toast.info("已发送停止请求")
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "停止离线下载失败。",
      )
    } finally {
      setOfflineStopping(false)
    }
  }

  async function renameEntry() {
    const nextName = renameName.trim()
    if (!renameTarget || !nextName || nextName.includes("/") || nextName.includes("\\")) {
      setError("请输入不包含路径分隔符的新名称。")
      return
    }

    setMutating(true)
    try {
      const response = await fetch("/api/modal-drive/files", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: renameTarget.path, newName: nextName }),
      })
      if (!response.ok) throw new Error((await responseMessage(response)).message)
      setRenameTarget(null)
      setRenameName("")
      toast.success("名称已更新")
      await loadFiles(path)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "重命名失败。")
    } finally {
      setMutating(false)
    }
  }

  async function deleteEntry() {
    if (!deleteTarget) return
    setMutating(true)
    try {
      const response = await fetch(
        `/api/modal-drive/files?path=${encodeURIComponent(deleteTarget.path)}&recursive=true`,
        { method: "DELETE" },
      )
      if (!response.ok) throw new Error((await responseMessage(response)).message)
      setDeleteTarget(null)
      toast.success("已删除")
      await loadFiles(path)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "删除失败。")
    } finally {
      setMutating(false)
    }
  }

  function openTransfer(entry: DriveEntry, operation: "copy" | "move") {
    if (isTransferActive(transferJob?.status)) {
      toast.info("请先等待当前复制或移动任务结束")
      return
    }
    setTransferTarget(entry)
    setTransferOperation(operation)
    setTransferDestination("")
    setError("")
  }

  async function transferEntry() {
    const destinationPath = transferDestination.trim()
    if (!transferTarget || !destinationPath.startsWith("/")) {
      setError("请输入以 / 开头的完整目标路径。")
      return
    }
    if (destinationPath === transferTarget.path) {
      setError("目标路径不能与源路径相同。")
      return
    }

    setMutating(true)
    setError("")
    try {
      const response = await fetch(`/api/modal-drive/${transferOperation}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourcePath: transferTarget.path,
          destinationPath,
        }),
      })
      if (!response.ok) throw new Error((await responseMessage(response)).message)
      const job = (await response.json()) as TransferJob
      setTransferJob(job)
      setTransferTarget(null)
      setTransferDestination("")
      toast.success(transferOperation === "copy" ? "复制任务已提交" : "移动任务已提交")
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : transferOperation === "copy"
            ? "复制失败。"
            : "移动失败。",
      )
    } finally {
      setMutating(false)
    }
  }

  async function stopTransfer() {
    if (!transferJob?.jobId || !isTransferActive(transferJob.status)) return
    setTransferStopping(true)
    setError("")
    try {
      const response = await fetch(
        `/api/modal-drive/transfer?jobId=${encodeURIComponent(transferJob.jobId)}`,
        { method: "DELETE" },
      )
      if (!response.ok) throw new Error((await responseMessage(response)).message)
      const payload = (await response.json()) as TransferJob
      setTransferJob((current) =>
        current?.jobId === payload.jobId ? { ...current, ...payload } : current,
      )
      toast.info("已发送停止请求")
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "停止传输失败。",
      )
    } finally {
      setTransferStopping(false)
    }
  }

  function openEntry(entry: DriveEntry) {
    if (entry.type === "directory") {
      void loadFiles(entry.path)
      return
    }
    window.location.assign(`/api/modal-drive/download?path=${encodeURIComponent(entry.path)}`)
  }

  return (
    <section aria-labelledby="modal-drive-title">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 id="modal-drive-title" className="flex items-center gap-3 text-2xl font-semibold tracking-[-0.035em] sm:text-3xl">
            <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
              <HardDriveIcon className="size-5" />
            </span>
            Modal 网盘
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            使用 Modal Volume 保存本地文件，并通过 rclone 在 Cloud 目录访问外部网盘。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline"><CloudIcon data-icon="inline-start" />Volume + rclone</Badge>
          <Badge variant="outline"><ShieldCheckIcon data-icon="inline-start" />Proxy Auth</Badge>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive" className="mb-5">
          <AlertTitle>操作未完成</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {session === null ? (
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-64" />
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-48 w-full" />
          </CardContent>
        </Card>
      ) : null}

      {session && !session.configured ? (
        <Card>
          <CardContent>
            <Empty className="min-h-96">
              <EmptyHeader>
                <EmptyMedia variant="icon"><CloudIcon /></EmptyMedia>
                <EmptyTitle>等待连接 Modal Volume</EmptyTitle>
                <EmptyDescription>
                  先部署 Python 服务，再在 .env.local 配置 Web Function URL 与 Proxy Token。
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <div className="w-full rounded-lg bg-muted p-3 text-left font-mono text-xs leading-6 text-muted-foreground">
                  MODAL_DRIVE_API_URL<br />
                  MODAL_PROXY_TOKEN_ID<br />
                  MODAL_PROXY_TOKEN_SECRET
                </div>
                <p className="text-xs text-muted-foreground">部署步骤见 modal/README.md</p>
              </EmptyContent>
            </Empty>
          </CardContent>
        </Card>
      ) : null}

      {session?.configured && session.protected && !session.authorized ? (
        <Card className="mx-auto max-w-md">
          <CardHeader>
            <div className="mb-2 grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
              <LockKeyholeIcon className="size-5" />
            </div>
            <CardTitle>解锁个人网盘</CardTitle>
            <CardDescription>输入 TOOLBOX 网盘访问密码，Modal 凭据不会发送到浏览器。</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={unlock}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="modal-drive-password">访问密码</FieldLabel>
                  <InputGroup>
                    <InputGroupAddon><KeyRoundIcon /></InputGroupAddon>
                    <InputGroupInput
                      id="modal-drive-password"
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="输入访问密码"
                    />
                  </InputGroup>
                  <FieldDescription>验证结果保存在 12 小时有效的 HttpOnly Cookie 中。</FieldDescription>
                </Field>
                <Button type="submit" size="lg" disabled={unlocking || !password}>
                  {unlocking ? <Spinner data-icon="inline-start" /> : <LockKeyholeIcon data-icon="inline-start" />}
                  {unlocking ? "正在验证…" : "解锁网盘"}
                </Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {session?.configured && session.authorized ? (
        <Card
          onDragEnter={(event) => {
            event.preventDefault()
            setDragging(true)
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
          }}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            void uploadFiles(event.dataTransfer.files)
          }}
          className={cn(dragging && "ring-2 ring-primary")}
        >
          <CardHeader className="border-b">
            <CardTitle className="flex items-center gap-2">
              <FolderOpenIcon className="size-5" />
              文件管理
            </CardTitle>
            <CardDescription>
              {entries.length} 项 · 当前目录文件 {formatBytes(totalSize)}
            </CardDescription>
            <CardAction className="flex items-center gap-1">
              {session.protected ? (
                <Button type="button" variant="ghost" size="sm" onClick={() => void lockDrive()}>
                  <LogOutIcon data-icon="inline-start" />
                  锁定
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="刷新当前目录"
                disabled={loading}
                onClick={() => void loadFiles(path)}
              >
                {loading ? <Spinner /> : <RefreshCwIcon />}
              </Button>
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {offlineJob && isOfflineDownloadActive(offlineJob.status) ? (
              <OfflineDownloadProgress
                job={offlineJob}
                stopping={offlineStopping}
                onStop={() => void stopOfflineDownload()}
              />
            ) : null}
            {transferJob && isTransferActive(transferJob.status) ? (
              <TransferProgress
                job={transferJob}
                stopping={transferStopping}
                onStop={() => void stopTransfer()}
              />
            ) : null}
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <PathBreadcrumbs path={path} onNavigate={(nextPath) => void loadFiles(nextPath)} />
              <div className="flex flex-wrap items-center gap-2">
                <InputGroup className="w-full sm:w-56">
                  <InputGroupAddon><SearchIcon /></InputGroupAddon>
                  <InputGroupInput
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="搜索当前目录"
                    aria-label="搜索当前目录"
                  />
                </InputGroup>
                <Button
                  type="button"
                  variant="outline"
                  disabled={isCloudIndex}
                  onClick={() => setFolderOpen(true)}
                >
                  <PlusIcon data-icon="inline-start" />
                  新建文件夹
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={isCloudIndex}
                  onClick={() => setOfflineOpen(true)}
                >
                  {isOfflineDownloadActive(offlineJob?.status) ? (
                    <Spinner data-icon="inline-start" />
                  ) : (
                    <CloudDownloadIcon data-icon="inline-start" />
                  )}
                  离线下载
                </Button>
                <Button
                  type="button"
                  disabled={uploading || isCloudIndex}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? <Spinner data-icon="inline-start" /> : <UploadCloudIcon data-icon="inline-start" />}
                  {uploading ? uploadStatus || "正在上传…" : "上传文件"}
                </Button>
                <input
                  ref={fileInputRef}
                  className="sr-only"
                  type="file"
                  multiple
                  onChange={(event) => {
                    if (event.target.files) void uploadFiles(event.target.files)
                  }}
                />
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border">
              <div className="hidden grid-cols-[minmax(0,1fr)_100px_140px_auto] gap-3 border-b bg-muted/50 px-4 py-2 text-xs font-medium text-muted-foreground sm:grid">
                <span>名称</span>
                <span>大小</span>
                <span>修改时间</span>
                <span className="text-right">操作</span>
              </div>

              {loading ? (
                <div className="flex flex-col gap-2 p-4">
                  {[0, 1, 2].map((item) => <Skeleton key={item} className="h-12 w-full" />)}
                </div>
              ) : null}

              {!loading && filteredEntries.length > 0 ? filteredEntries.map((entry) => (
                <DriveRow
                  key={entry.path}
                  entry={entry}
                  onOpen={openEntry}
                  onRename={(target) => {
                    setRenameTarget(target)
                    setRenameName(target.name)
                  }}
                  onCopy={(target) => openTransfer(target, "copy")}
                  onMove={(target) => openTransfer(target, "move")}
                  onDelete={setDeleteTarget}
                />
              )) : null}

              {!loading && filteredEntries.length === 0 ? (
                <Empty className="min-h-64">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">{query ? <SearchIcon /> : <FolderOpenIcon />}</EmptyMedia>
                    <EmptyTitle>
                      {query
                        ? "没有匹配的文件"
                        : isCloudIndex
                          ? "没有可用的远程网盘"
                          : "这个文件夹是空的"}
                    </EmptyTitle>
                    <EmptyDescription>
                      {query
                        ? "尝试更换搜索关键词。"
                        : isCloudIndex
                          ? "请检查传入的 rclone 配置文件中是否包含 remote。"
                          : "拖入文件，或点击上传按钮开始使用。"}
                    </EmptyDescription>
                  </EmptyHeader>
                  {!query && !isCloudIndex ? (
                    <EmptyContent>
                      <Button type="button" variant="outline" onClick={() => fileInputRef.current?.click()}>
                        <UploadCloudIcon data-icon="inline-start" />
                        选择文件
                      </Button>
                    </EmptyContent>
                  ) : null}
                </Empty>
              ) : null}
            </div>
          </CardContent>
          <CardFooter className="justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <ShieldCheckIcon className="size-3.5" />
              Modal Proxy Token 仅保存在服务端
            </span>
            <span className="hidden sm:inline">支持拖放上传</span>
          </CardFooter>
        </Card>
      ) : null}

      <Dialog open={folderOpen} onOpenChange={setFolderOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建文件夹</DialogTitle>
            <DialogDescription>将在 {path} 下创建新的目录。</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="new-folder-name">文件夹名称</FieldLabel>
            <Input
              id="new-folder-name"
              value={folderName}
              onChange={(event) => setFolderName(event.target.value)}
              placeholder="例如：Documents"
              autoFocus
            />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setFolderOpen(false)}>取消</Button>
            <Button type="button" disabled={mutating || !folderName.trim()} onClick={() => void createFolder()}>
              {mutating ? <Spinner data-icon="inline-start" /> : <PlusIcon data-icon="inline-start" />}
              创建
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={offlineOpen} onOpenChange={setOfflineOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>离线下载</DialogTitle>
            <DialogDescription>
              文件将保存到 {path}。多个链接会严格按照输入顺序逐个下载。
            </DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="offline-download-links">下载链接</FieldLabel>
            <Textarea
              id="offline-download-links"
              className="min-h-40 resize-y font-mono text-xs"
              value={offlineLinks}
              onChange={(event) => setOfflineLinks(event.target.value)}
              placeholder={"https://example.com/video.mp4\nhttps://example.com/archive.zip"}
              disabled={
                offlineSubmitting ||
                isOfflineDownloadActive(offlineJob?.status)
              }
              autoFocus
            />
            <FieldDescription>
              每行一个 HTTP 或 HTTPS 直链，每批最多 50 个；同名文件会自动添加序号。
            </FieldDescription>
          </Field>

          {offlineJob && isOfflineDownloadActive(offlineJob.status) ? (
            <OfflineDownloadProgress
              job={offlineJob}
              stopping={offlineStopping}
              onStop={() => void stopOfflineDownload()}
            />
          ) : null}

          {offlineJob && !isOfflineDownloadActive(offlineJob.status) && offlineJob.results ? (
            <div className="max-h-52 space-y-2 overflow-y-auto rounded-lg border p-3">
              {offlineJob.results.map((result, index) => (
                <div
                  key={`${result.url}-${index}`}
                  className="flex items-start justify-between gap-3 text-xs"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">
                      {result.entry?.name || result.url}
                    </p>
                    {result.error ? (
                      <p className="mt-0.5 break-words text-destructive">
                        {result.error}
                      </p>
                    ) : null}
                  </div>
                  <Badge
                    variant={
                      result.status === "completed"
                        ? "secondary"
                        : result.status === "canceled"
                          ? "outline"
                          : "destructive"
                    }
                  >
                    {result.status === "completed"
                      ? "完成"
                      : result.status === "canceled"
                        ? "已停止"
                        : "失败"}
                  </Badge>
                </div>
              ))}
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOfflineOpen(false)}>
              关闭
            </Button>
            <Button
              type="button"
              disabled={
                offlineSubmitting ||
                !offlineLinks.trim() ||
                isOfflineDownloadActive(offlineJob?.status)
              }
              onClick={() => void startOfflineDownload()}
            >
              {offlineSubmitting ? (
                <Spinner data-icon="inline-start" />
              ) : (
                <CloudDownloadIcon data-icon="inline-start" />
              )}
              提交任务
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(renameTarget)} onOpenChange={(open) => !open && setRenameTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重命名</DialogTitle>
            <DialogDescription>修改“{renameTarget?.name}”的名称。</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="rename-entry">新名称</FieldLabel>
            <Input
              id="rename-entry"
              value={renameName}
              onChange={(event) => setRenameName(event.target.value)}
              autoFocus
            />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setRenameTarget(null)}>取消</Button>
            <Button type="button" disabled={mutating || !renameName.trim()} onClick={() => void renameEntry()}>
              {mutating ? <Spinner data-icon="inline-start" /> : <PencilIcon data-icon="inline-start" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(transferTarget)}
        onOpenChange={(open) => {
          if (!open) {
            setTransferTarget(null)
            setTransferDestination("")
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {transferOperation === "copy" ? "复制" : "移动"}“{transferTarget?.name}”
            </DialogTitle>
            <DialogDescription>
              输入包含名称的完整目标路径。Cloud 路径格式为 /Cloud/远程名称/文件路径。
            </DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field>
              <FieldLabel>源路径</FieldLabel>
              <Input value={transferTarget?.path || ""} readOnly />
            </Field>
            <Field>
              <FieldLabel htmlFor="transfer-destination">目标路径</FieldLabel>
              <Input
                id="transfer-destination"
                value={transferDestination}
                onChange={(event) => setTransferDestination(event.target.value)}
                placeholder={`/Cloud/远程名称/${transferTarget?.name || "文件名"}`}
                autoFocus
              />
              <FieldDescription>
                例如 /Cloud/onedrive/Backup/{transferTarget?.name || "文件名"}；目标已存在时不会覆盖。
              </FieldDescription>
            </Field>
          </FieldGroup>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setTransferTarget(null)}>
              取消
            </Button>
            <Button
              type="button"
              disabled={
                mutating ||
                !transferDestination.trim() ||
                transferDestination.trim() === transferTarget?.path
              }
              onClick={() => void transferEntry()}
            >
              {mutating ? (
                <Spinner data-icon="inline-start" />
              ) : transferOperation === "copy" ? (
                <CopyIcon data-icon="inline-start" />
              ) : (
                <MoveRightIcon data-icon="inline-start" />
              )}
              {transferOperation === "copy" ? "开始复制" : "开始移动"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>删除“{deleteTarget?.name}”</DialogTitle>
            <DialogDescription>
              {deleteTarget?.type === "directory"
                ? "文件夹及其全部内容会被永久删除。"
                : deleteTarget?.path.startsWith("/Cloud/")
                  ? "文件会从 rclone 远端网盘中永久删除。"
                  : "文件会从 Modal Volume 中永久删除。"}
            </DialogDescription>
          </DialogHeader>
          <Alert variant="destructive">
            <Trash2Icon />
            <AlertTitle>此操作不可撤销</AlertTitle>
            <AlertDescription>Modal 删除的数据可能继续计费数日，但无法恢复。</AlertDescription>
          </Alert>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button>
            <Button type="button" variant="destructive" disabled={mutating} onClick={() => void deleteEntry()}>
              {mutating ? <Spinner data-icon="inline-start" /> : <Trash2Icon data-icon="inline-start" />}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
