import "server-only"

import { randomUUID } from "node:crypto"

import {
  decryptLocalSecret,
  encryptLocalSecret,
  openLocalDatabase,
} from "@/lib/local-database"

type ChannelRow = {
  id: string
  name: string
  provider: string
  base_url: string
  encrypted_api_key: string | null
  enabled: number
  created_at: string
  updated_at: string
}

type ModelRow = {
  id: string
  channel_id: string
  model_id: string
  display_name: string | null
  source: string
  enabled: number
  created_at: string
  updated_at: string
  last_seen_at: string | null
}

type RequestRow = {
  id: string
  channel_id: string | null
  channel_name: string | null
  model_record_id: string | null
  model_id: string | null
  request_type: string
  status: string
  http_status: number | null
  latency_ms: number | null
  prompt_preview: string | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  response_chars: number | null
  error_message: string | null
  created_at: string
}

export type ModelChannel = {
  id: string
  name: string
  provider: string
  baseUrl: string
  hasApiKey: boolean
  enabled: boolean
  createdAt: string
  updatedAt: string
}

export type StoredModel = {
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

export type ModelRequestRecord = {
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

export type RequestLogInput = {
  channelId?: string | null
  modelRecordId?: string | null
  modelId?: string | null
  requestType: string
  status: "success" | "error" | "cancelled"
  httpStatus?: number | null
  latencyMs?: number | null
  promptPreview?: string | null
  request?: Record<string, unknown> | null
  usage?: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
  } | null
  responseChars?: number | null
  errorMessage?: string | null
}

function database() {
  const db = openLocalDatabase("model_tester.sqlite3")
  db.exec(`
    CREATE TABLE IF NOT EXISTS channels (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      provider TEXT NOT NULL DEFAULT 'custom',
      base_url TEXT NOT NULL,
      encrypted_api_key TEXT,
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS models (
      id TEXT PRIMARY KEY,
      channel_id TEXT NOT NULL,
      model_id TEXT NOT NULL,
      display_name TEXT,
      source TEXT NOT NULL DEFAULT 'manual',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      last_seen_at TEXT,
      UNIQUE(channel_id, model_id),
      FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_models_channel
    ON models(channel_id, enabled, model_id);

    CREATE TABLE IF NOT EXISTS request_logs (
      id TEXT PRIMARY KEY,
      channel_id TEXT,
      model_record_id TEXT,
      model_id TEXT,
      request_type TEXT NOT NULL,
      status TEXT NOT NULL,
      http_status INTEGER,
      latency_ms INTEGER,
      prompt_preview TEXT,
      request_json TEXT,
      input_tokens INTEGER,
      output_tokens INTEGER,
      total_tokens INTEGER,
      response_chars INTEGER,
      error_message TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE SET NULL,
      FOREIGN KEY(model_record_id) REFERENCES models(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_request_logs_created
    ON request_logs(created_at DESC);
  `)
  return db
}

function channelFromRow(row: ChannelRow): ModelChannel {
  return {
    id: row.id,
    name: row.name,
    provider: row.provider,
    baseUrl: row.base_url,
    hasApiKey: Boolean(row.encrypted_api_key),
    enabled: Boolean(row.enabled),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  }
}

function modelFromRow(row: ModelRow): StoredModel {
  return {
    id: row.id,
    channelId: row.channel_id,
    modelId: row.model_id,
    displayName: row.display_name || row.model_id,
    source: row.source,
    enabled: Boolean(row.enabled),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    lastSeenAt: row.last_seen_at,
  }
}

function requestFromRow(row: RequestRow): ModelRequestRecord {
  return {
    id: row.id,
    channelId: row.channel_id,
    channelName: row.channel_name,
    modelId: row.model_id,
    requestType: row.request_type,
    status: row.status,
    httpStatus: row.http_status,
    latencyMs: row.latency_ms,
    promptPreview: row.prompt_preview,
    inputTokens: row.input_tokens,
    outputTokens: row.output_tokens,
    totalTokens: row.total_tokens,
    responseChars: row.response_chars,
    errorMessage: row.error_message,
    createdAt: row.created_at,
  }
}

export function listChannels() {
  return (
    database()
      .prepare("SELECT * FROM channels ORDER BY enabled DESC, name COLLATE NOCASE")
      .all() as ChannelRow[]
  ).map(channelFromRow)
}

export function getChannel(channelId: string, includeDisabled = false) {
  const row = database()
    .prepare(
      `SELECT * FROM channels WHERE id = ? ${includeDisabled ? "" : "AND enabled = 1"}`,
    )
    .get(channelId) as ChannelRow | undefined
  return row ? channelFromRow(row) : null
}

export function getChannelCredentials(channelId: string) {
  const row = database()
    .prepare("SELECT * FROM channels WHERE id = ? AND enabled = 1")
    .get(channelId) as ChannelRow | undefined
  if (!row) return null
  return {
    ...channelFromRow(row),
    apiKey: decryptLocalSecret(row.encrypted_api_key),
  }
}

export function createChannel(input: {
  name: string
  provider: string
  baseUrl: string
  apiKey: string
}) {
  const id = randomUUID()
  const now = new Date().toISOString()
  database()
    .prepare(`
      INSERT INTO channels (
        id, name, provider, base_url, encrypted_api_key,
        enabled, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    `)
    .run(
      id,
      input.name,
      input.provider,
      input.baseUrl,
      encryptLocalSecret(input.apiKey),
      now,
      now,
    )
  return getChannel(id, true)!
}

export function updateChannel(
  channelId: string,
  input: {
    name?: string
    provider?: string
    baseUrl?: string
    apiKey?: string
    enabled?: boolean
  },
) {
  const db = database()
  const current = db
    .prepare("SELECT * FROM channels WHERE id = ?")
    .get(channelId) as ChannelRow | undefined
  if (!current) return null

  db.prepare(`
    UPDATE channels
    SET name = ?, provider = ?, base_url = ?, encrypted_api_key = ?,
        enabled = ?, updated_at = ?
    WHERE id = ?
  `).run(
    input.name ?? current.name,
    input.provider ?? current.provider,
    input.baseUrl ?? current.base_url,
    input.apiKey === undefined
      ? current.encrypted_api_key
      : encryptLocalSecret(input.apiKey),
    input.enabled === undefined ? current.enabled : input.enabled ? 1 : 0,
    new Date().toISOString(),
    channelId,
  )
  return getChannel(channelId, true)
}

export function deleteChannel(channelId: string) {
  return database().prepare("DELETE FROM channels WHERE id = ?").run(channelId)
    .changes > 0
}

export function listModels(channelId?: string, includeDisabled = false) {
  const clauses: string[] = []
  const values: string[] = []
  if (channelId) {
    clauses.push("channel_id = ?")
    values.push(channelId)
  }
  if (!includeDisabled) clauses.push("enabled = 1")
  const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : ""
  return (
    database()
      .prepare(`
        SELECT * FROM models
        ${where}
        ORDER BY channel_id, model_id COLLATE NOCASE
      `)
      .all(...values) as ModelRow[]
  ).map(modelFromRow)
}

export function findModel(channelId: string, modelId: string) {
  const row = database()
    .prepare(`
      SELECT * FROM models
      WHERE channel_id = ? AND model_id = ? AND enabled = 1
    `)
    .get(channelId, modelId) as ModelRow | undefined
  return row ? modelFromRow(row) : null
}

export function replaceSyncedModels(channelId: string, modelIds: string[]) {
  const db = database()
  const now = new Date().toISOString()
  db.exec("BEGIN IMMEDIATE")
  try {
    db.prepare(`
      UPDATE models SET enabled = 0, updated_at = ?
      WHERE channel_id = ? AND source = 'synced'
    `).run(now, channelId)
    const upsert = db.prepare(`
      INSERT INTO models (
        id, channel_id, model_id, display_name, source,
        enabled, created_at, updated_at, last_seen_at
      ) VALUES (?, ?, ?, ?, 'synced', 1, ?, ?, ?)
      ON CONFLICT(channel_id, model_id) DO UPDATE SET
        enabled = 1,
        updated_at = excluded.updated_at,
        last_seen_at = excluded.last_seen_at
    `)
    for (const modelId of modelIds) {
      upsert.run(randomUUID(), channelId, modelId, modelId, now, now, now)
    }
    db.exec("COMMIT")
  } catch (error) {
    db.exec("ROLLBACK")
    throw error
  }
  return listModels(channelId)
}

export function createManualModel(input: {
  channelId: string
  modelId: string
  displayName?: string
}) {
  const id = randomUUID()
  const now = new Date().toISOString()
  database()
    .prepare(`
      INSERT INTO models (
        id, channel_id, model_id, display_name, source,
        enabled, created_at, updated_at
      ) VALUES (?, ?, ?, ?, 'manual', 1, ?, ?)
    `)
    .run(
      id,
      input.channelId,
      input.modelId,
      input.displayName || input.modelId,
      now,
      now,
    )
  const row = database()
    .prepare("SELECT * FROM models WHERE id = ?")
    .get(id) as ModelRow
  return modelFromRow(row)
}

export function updateStoredModel(
  recordId: string,
  input: { modelId?: string; displayName?: string; enabled?: boolean },
) {
  const db = database()
  const current = db
    .prepare("SELECT * FROM models WHERE id = ?")
    .get(recordId) as ModelRow | undefined
  if (!current) return null
  db.prepare(`
    UPDATE models
    SET model_id = ?, display_name = ?, enabled = ?, updated_at = ?
    WHERE id = ?
  `).run(
    input.modelId ?? current.model_id,
    input.displayName ?? current.display_name ?? current.model_id,
    input.enabled === undefined ? current.enabled : input.enabled ? 1 : 0,
    new Date().toISOString(),
    recordId,
  )
  const row = db
    .prepare("SELECT * FROM models WHERE id = ?")
    .get(recordId) as ModelRow
  return modelFromRow(row)
}

export function deleteStoredModel(recordId: string) {
  return database().prepare("DELETE FROM models WHERE id = ?").run(recordId)
    .changes > 0
}

export function recordModelRequest(input: RequestLogInput) {
  const usage = input.usage ?? {}
  database()
    .prepare(`
      INSERT INTO request_logs (
        id, channel_id, model_record_id, model_id, request_type,
        status, http_status, latency_ms, prompt_preview, request_json,
        input_tokens, output_tokens, total_tokens, response_chars,
        error_message, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)
    .run(
      randomUUID(),
      input.channelId ?? null,
      input.modelRecordId ?? null,
      input.modelId ?? null,
      input.requestType,
      input.status,
      input.httpStatus ?? null,
      input.latencyMs ?? null,
      input.promptPreview?.slice(0, 500) ?? null,
      input.request ? JSON.stringify(input.request) : null,
      usage.prompt_tokens ?? null,
      usage.completion_tokens ?? null,
      usage.total_tokens ?? null,
      input.responseChars ?? null,
      input.errorMessage?.slice(0, 2000) ?? null,
      new Date().toISOString(),
    )
}

export function listModelRequests(channelId?: string, limit = 50) {
  const safeLimit = Math.min(Math.max(Math.round(limit), 1), 200)
  const where = channelId ? "WHERE logs.channel_id = ?" : ""
  const values: Array<string | number> = channelId
    ? [channelId, safeLimit]
    : [safeLimit]
  return (
    database()
      .prepare(`
        SELECT logs.*, channels.name AS channel_name
        FROM request_logs AS logs
        LEFT JOIN channels ON channels.id = logs.channel_id
        ${where}
        ORDER BY logs.created_at DESC
        LIMIT ?
      `)
      .all(...values) as RequestRow[]
  ).map(requestFromRow)
}

export function clearModelRequests(channelId?: string) {
  if (channelId) {
    database().prepare("DELETE FROM request_logs WHERE channel_id = ?").run(channelId)
  } else {
    database().exec("DELETE FROM request_logs")
  }
}
