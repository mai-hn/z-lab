import "server-only"

import {
  needsVideoMetadata,
  recordDriveEvent,
  recordDriveListing,
  removeDriveEntry,
  type DriveEntryRecord,
  upsertDriveEntry,
  upsertVideoMetadata,
} from "@/lib/modal-drive-database"

type DrivePayload = {
  path?: string
  entries?: DriveEntryRecord[]
  entry?: DriveEntryRecord
  sourcePath?: string
  destinationPath?: string
  operation?: "copy" | "move"
  video?: Parameters<typeof upsertVideoMetadata>[1] | null
  status?: string
  results?: Array<{
    url?: string
    status?: string
    entry?: DriveEntryRecord
    error?: string
  }>
}

function requestPath(request: Request) {
  return new URL(request.url).searchParams.get("path") || "/"
}

export async function recordModalDriveResult(
  request: Request,
  endpoint: string,
  response: Response,
) {
  if (!response.ok) return [] as DriveEntryRecord[]
  const method = request.method.toUpperCase()

  if (endpoint === "download" && method === "GET") {
    recordDriveEvent({
      type: "file.downloaded",
      path: requestPath(request),
      size: Number(response.headers.get("content-length")) || null,
    })
    return []
  }

  const contentType = response.headers.get("content-type") || ""
  if (!contentType.includes("application/json")) return []
  const payload = (await response.json()) as DrivePayload

  if (endpoint === "files" && method === "GET" && Array.isArray(payload.entries)) {
    const path = typeof payload.path === "string" ? payload.path : requestPath(request)
    recordDriveListing(path, payload.entries)
    return payload.entries.filter(needsVideoMetadata)
  }

  if (endpoint === "upload" && method === "POST" && payload.entry) {
    upsertDriveEntry(payload.entry)
    recordDriveEvent({
      type: "file.uploaded",
      path: payload.entry.path,
      size: payload.entry.size,
      details: { mimeType: payload.entry.mimeType || null },
    })
    return needsVideoMetadata(payload.entry) ? [payload.entry] : []
  }

  if (
    endpoint === "offline-download" &&
    method === "GET" &&
    (payload.status === "completed" || payload.status === "canceled") &&
    Array.isArray(payload.results)
  ) {
    const entries = payload.results.flatMap((result) => {
      if (result.status !== "completed" || !result.entry) return []
      upsertDriveEntry(result.entry)
      recordDriveEvent({
        type: "file.offline-downloaded",
        path: result.entry.path,
        size: result.entry.size,
        details: { sourceUrl: result.url || null },
      })
      return [result.entry]
    })
    return entries.filter(needsVideoMetadata)
  }

  if (endpoint === "folders" && method === "POST" && payload.entry) {
    upsertDriveEntry(payload.entry)
    recordDriveEvent({ type: "folder.created", path: payload.entry.path })
    return []
  }

  if (endpoint === "files" && method === "PATCH" && payload.entry) {
    const body = (await request.json().catch(() => null)) as {
      path?: unknown
    } | null
    const oldPath = typeof body?.path === "string" ? body.path : ""
    if (oldPath) removeDriveEntry(oldPath)
    upsertDriveEntry(payload.entry)
    recordDriveEvent({
      type: "entry.renamed",
      path: oldPath || payload.entry.path,
      destinationPath: payload.entry.path,
    })
    return needsVideoMetadata(payload.entry) ? [payload.entry] : []
  }

  if (
    endpoint === "transfer" &&
    method === "GET" &&
    payload.status === "completed" &&
    payload.entry
  ) {
    const sourcePath = payload.sourcePath || ""
    const destinationPath = payload.destinationPath || payload.entry.path
    if (payload.operation === "move" && sourcePath) removeDriveEntry(sourcePath)
    upsertDriveEntry(payload.entry)
    recordDriveEvent({
      type: payload.operation === "move" ? "entry.moved" : "entry.copied",
      path: sourcePath || payload.entry.path,
      destinationPath,
      size: payload.entry.size,
    })
    return needsVideoMetadata(payload.entry) ? [payload.entry] : []
  }

  if (endpoint === "files" && method === "DELETE") {
    const path = requestPath(request)
    removeDriveEntry(path)
    recordDriveEvent({ type: "entry.deleted", path })
    return []
  }

  if (endpoint === "metadata" && method === "GET" && payload.entry) {
    upsertDriveEntry(payload.entry)
    if (payload.video) upsertVideoMetadata(payload.entry, payload.video)
  }

  return []
}
