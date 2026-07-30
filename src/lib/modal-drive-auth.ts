import "server-only"

import { createHash, timingSafeEqual } from "node:crypto"
import { cookies } from "next/headers"

const SESSION_COOKIE = "toolbox_modal_drive_session"
const SESSION_MAX_AGE = 60 * 60 * 12

function configuredPassword() {
  return process.env.MODAL_DRIVE_ACCESS_PASSWORD?.trim() || ""
}

function sessionValue(password: string) {
  return createHash("sha256")
    .update(`toolbox-modal-drive:${password}`)
    .digest("base64url")
}

function equalText(left: string, right: string) {
  const leftBuffer = Buffer.from(left)
  const rightBuffer = Buffer.from(right)
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer)
}

export function isModalDriveProtected() {
  return Boolean(configuredPassword())
}

export async function isModalDriveAuthorized() {
  const password = configuredPassword()
  if (!password) return true

  const cookieStore = await cookies()
  const current = cookieStore.get(SESSION_COOKIE)?.value || ""
  return equalText(current, sessionValue(password))
}

export async function createModalDriveSession(password: string) {
  const expected = configuredPassword()
  if (!expected || !equalText(password, expected)) return false

  const cookieStore = await cookies()
  cookieStore.set(SESSION_COOKIE, sessionValue(expected), {
    httpOnly: true,
    maxAge: SESSION_MAX_AGE,
    path: "/",
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
  })
  return true
}

export async function clearModalDriveSession() {
  const cookieStore = await cookies()
  cookieStore.delete(SESSION_COOKIE)
}
