import "server-only"

import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
} from "node:crypto"
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs"
import { isAbsolute, join, resolve } from "node:path"
import { DatabaseSync } from "node:sqlite"

type DatabaseGlobals = typeof globalThis & {
  __toolboxDatabases?: Map<string, DatabaseSync>
  __toolboxEncryptionKey?: Buffer
}

const databaseGlobals = globalThis as DatabaseGlobals
type LocalDatabaseName = "model_tester.sqlite3" | "modal_drive.sqlite3"

export function localDataDirectory() {
  const configured = process.env.TOOLBOX_DATA_DIR?.trim()
  const directory = configured
    ? isAbsolute(configured)
      ? configured
      : resolve(/* turbopackIgnore: true */ process.cwd(), configured)
    : join(process.cwd(), "data")
  mkdirSync(directory, { recursive: true })
  return directory
}

export function openLocalDatabase(name: LocalDatabaseName) {
  const databases = databaseGlobals.__toolboxDatabases ?? new Map<string, DatabaseSync>()
  databaseGlobals.__toolboxDatabases = databases

  const existing = databases.get(name)
  if (existing) return existing

  const databasePath =
    name === "model_tester.sqlite3"
      ? join(localDataDirectory(), "model_tester.sqlite3")
      : join(localDataDirectory(), "modal_drive.sqlite3")
  const database = new DatabaseSync(databasePath, {
    timeout: 30_000,
  })
  database.exec(`
    PRAGMA foreign_keys = ON;
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;
    PRAGMA busy_timeout = 30000;
  `)
  databases.set(name, database)
  return database
}

function localEncryptionKey() {
  if (databaseGlobals.__toolboxEncryptionKey) {
    return databaseGlobals.__toolboxEncryptionKey
  }

  const configured = process.env.MODEL_TESTER_DATABASE_KEY?.trim()
  if (configured) {
    const key = createHash("sha256").update(configured).digest()
    databaseGlobals.__toolboxEncryptionKey = key
    return key
  }

  const keyPath = join(localDataDirectory(), ".model-tester.key")
  if (!existsSync(keyPath)) {
    try {
      writeFileSync(keyPath, randomBytes(32), { flag: "wx", mode: 0o600 })
    } catch (error) {
      if (!existsSync(keyPath)) throw error
    }
  }

  const stored = readFileSync(keyPath)
  if (stored.length !== 32) {
    throw new Error("本地模型数据库加密密钥无效。")
  }
  databaseGlobals.__toolboxEncryptionKey = stored
  return stored
}

export function encryptLocalSecret(value: string) {
  if (!value) return null
  const iv = randomBytes(12)
  const cipher = createCipheriv("aes-256-gcm", localEncryptionKey(), iv)
  const encrypted = Buffer.concat([cipher.update(value, "utf8"), cipher.final()])
  const tag = cipher.getAuthTag()
  return [
    "v1",
    iv.toString("base64url"),
    tag.toString("base64url"),
    encrypted.toString("base64url"),
  ].join(":")
}

export function decryptLocalSecret(value: string | null) {
  if (!value) return ""
  const [version, ivValue, tagValue, encryptedValue] = value.split(":")
  if (version !== "v1" || !ivValue || !tagValue || !encryptedValue) {
    throw new Error("本地渠道密钥格式无效。")
  }

  const decipher = createDecipheriv(
    "aes-256-gcm",
    localEncryptionKey(),
    Buffer.from(ivValue, "base64url"),
  )
  decipher.setAuthTag(Buffer.from(tagValue, "base64url"))
  return Buffer.concat([
    decipher.update(Buffer.from(encryptedValue, "base64url")),
    decipher.final(),
  ]).toString("utf8")
}
