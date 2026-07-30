import "server-only"

import { randomUUID } from "node:crypto"

import { openLocalDatabase } from "@/lib/local-database"

export type DriveEntryRecord = {
  name: string
  path: string
  type: "file" | "directory"
  size: number
  mimeType?: string | null
  modifiedAt: string
}

export type VideoMetadataRecord = {
  durationSeconds?: number | null
  width?: number | null
  height?: number | null
  videoCodec?: string | null
  audioCodec?: string | null
  frameRate?: number | null
  bitRate?: number | null
  containerFormat?: string | null
}

function database() {
  const db = openLocalDatabase("modal_drive.sqlite3")
  db.exec(`
    CREATE TABLE IF NOT EXISTS drive_entries (
      path TEXT PRIMARY KEY,
      parent_path TEXT NOT NULL,
      name TEXT NOT NULL,
      entry_type TEXT NOT NULL,
      size INTEGER NOT NULL DEFAULT 0,
      mime_type TEXT,
      modified_at TEXT NOT NULL,
      indexed_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_drive_entries_parent
    ON drive_entries(parent_path, entry_type, name);

    CREATE TABLE IF NOT EXISTS video_metadata (
      path TEXT PRIMARY KEY,
      duration_seconds REAL,
      width INTEGER,
      height INTEGER,
      video_codec TEXT,
      audio_codec TEXT,
      frame_rate REAL,
      bit_rate INTEGER,
      container_format TEXT,
      source_modified_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(path) REFERENCES drive_entries(path)
        ON DELETE CASCADE ON UPDATE CASCADE
    );

    CREATE TABLE IF NOT EXISTS drive_events (
      id TEXT PRIMARY KEY,
      event_type TEXT NOT NULL,
      path TEXT NOT NULL,
      destination_path TEXT,
      size INTEGER,
      details_json TEXT,
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_drive_events_created
    ON drive_events(created_at DESC);
  `)
  return db
}

function parentPath(path: string) {
  const parts = path.split("/").filter(Boolean)
  parts.pop()
  return parts.length ? `/${parts.join("/")}` : "/"
}

function inferredMimeType(entry: DriveEntryRecord) {
  if (entry.mimeType) return entry.mimeType
  const extension = entry.name.split(".").pop()?.toLowerCase()
  if (["mp4", "mov", "mkv", "webm", "avi", "m4v"].includes(extension || "")) {
    return "video/unknown"
  }
  return null
}

export function upsertDriveEntry(entry: DriveEntryRecord) {
  database()
    .prepare(`
      INSERT INTO drive_entries (
        path, parent_path, name, entry_type, size,
        mime_type, modified_at, indexed_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(path) DO UPDATE SET
        parent_path = excluded.parent_path,
        name = excluded.name,
        entry_type = excluded.entry_type,
        size = excluded.size,
        mime_type = excluded.mime_type,
        modified_at = excluded.modified_at,
        indexed_at = excluded.indexed_at
    `)
    .run(
      entry.path,
      parentPath(entry.path),
      entry.name,
      entry.type,
      entry.size,
      inferredMimeType(entry),
      entry.modifiedAt,
      new Date().toISOString(),
    )
}

export function recordDriveListing(path: string, entries: DriveEntryRecord[]) {
  const db = database()
  db.exec("BEGIN IMMEDIATE")
  try {
    for (const entry of entries) upsertDriveEntry(entry)
    const currentPaths = new Set(entries.map((entry) => entry.path))
    const stored = db
      .prepare("SELECT path FROM drive_entries WHERE parent_path = ?")
      .all(path) as Array<{ path: string }>
    const remove = db.prepare("DELETE FROM drive_entries WHERE path = ?")
    for (const row of stored) {
      if (!currentPaths.has(row.path)) remove.run(row.path)
    }
    db.exec("COMMIT")
  } catch (error) {
    db.exec("ROLLBACK")
    throw error
  }
}

export function removeDriveEntry(path: string) {
  const db = database()
  db.prepare("DELETE FROM drive_entries WHERE path = ? OR path LIKE ?").run(
    path,
    `${path}/%`,
  )
}

export function recordDriveEvent(input: {
  type: string
  path: string
  destinationPath?: string | null
  size?: number | null
  details?: Record<string, unknown> | null
}) {
  database()
    .prepare(`
      INSERT INTO drive_events (
        id, event_type, path, destination_path, size, details_json, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
    `)
    .run(
      randomUUID(),
      input.type,
      input.path,
      input.destinationPath ?? null,
      input.size ?? null,
      input.details ? JSON.stringify(input.details) : null,
      new Date().toISOString(),
    )
}

export function needsVideoMetadata(entry: DriveEntryRecord) {
  const mimeType = inferredMimeType(entry)
  if (!mimeType?.startsWith("video/")) return false
  const row = database()
    .prepare("SELECT source_modified_at FROM video_metadata WHERE path = ?")
    .get(entry.path) as { source_modified_at: string } | undefined
  return !row || row.source_modified_at !== entry.modifiedAt
}

export function upsertVideoMetadata(
  entry: DriveEntryRecord,
  metadata: VideoMetadataRecord,
) {
  upsertDriveEntry(entry)
  database()
    .prepare(`
      INSERT INTO video_metadata (
        path, duration_seconds, width, height, video_codec, audio_codec,
        frame_rate, bit_rate, container_format, source_modified_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(path) DO UPDATE SET
        duration_seconds = excluded.duration_seconds,
        width = excluded.width,
        height = excluded.height,
        video_codec = excluded.video_codec,
        audio_codec = excluded.audio_codec,
        frame_rate = excluded.frame_rate,
        bit_rate = excluded.bit_rate,
        container_format = excluded.container_format,
        source_modified_at = excluded.source_modified_at,
        updated_at = excluded.updated_at
    `)
    .run(
      entry.path,
      metadata.durationSeconds ?? null,
      metadata.width ?? null,
      metadata.height ?? null,
      metadata.videoCodec ?? null,
      metadata.audioCodec ?? null,
      metadata.frameRate ?? null,
      metadata.bitRate ?? null,
      metadata.containerFormat ?? null,
      entry.modifiedAt,
      new Date().toISOString(),
    )
}

export function driveCatalog(path = "/") {
  const entries = database()
    .prepare(`
      SELECT
        entries.*,
        video.duration_seconds,
        video.width,
        video.height,
        video.video_codec,
        video.audio_codec,
        video.frame_rate,
        video.bit_rate,
        video.container_format
      FROM drive_entries AS entries
      LEFT JOIN video_metadata AS video ON video.path = entries.path
      WHERE entries.parent_path = ?
      ORDER BY entries.entry_type DESC, entries.name COLLATE NOCASE
    `)
    .all(path)
  const events = database()
    .prepare("SELECT * FROM drive_events ORDER BY created_at DESC LIMIT 50")
    .all()
  return { entries, events }
}
