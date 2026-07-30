import {
  clearModalDriveSession,
  createModalDriveSession,
  isModalDriveAuthorized,
  isModalDriveProtected,
} from "@/lib/modal-drive-auth"
import { isModalDriveConfigured } from "@/lib/modal-drive"

export const dynamic = "force-dynamic"

export async function GET() {
  return Response.json(
    {
      configured: isModalDriveConfigured(),
      protected: isModalDriveProtected(),
      authorized: await isModalDriveAuthorized(),
    },
    { headers: { "Cache-Control": "no-store" } },
  )
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as { password?: unknown } | null
  const password = typeof body?.password === "string" ? body.password : ""
  if (!password || password.length > 512 || !(await createModalDriveSession(password))) {
    return Response.json(
      { message: "访问密码不正确。" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    )
  }

  return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } })
}

export async function DELETE() {
  await clearModalDriveSession()
  return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } })
}
