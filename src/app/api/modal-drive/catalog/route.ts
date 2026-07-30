import { isModalDriveAuthorized } from "@/lib/modal-drive-auth"
import { driveCatalog } from "@/lib/modal-drive-database"

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  if (!(await isModalDriveAuthorized())) {
    return Response.json(
      { message: "请先解锁 Modal 网盘。", code: "DRIVE_AUTH_REQUIRED" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    )
  }
  const path = new URL(request.url).searchParams.get("path") || "/"
  return Response.json(driveCatalog(path), {
    headers: { "Cache-Control": "no-store" },
  })
}
