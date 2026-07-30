import {
  modalDriveErrorResponse,
  proxyModalDriveRequest,
} from "@/lib/modal-drive"
import { isModalDriveAuthorized } from "@/lib/modal-drive-auth"

export const dynamic = "force-dynamic"

async function handle(
  request: Request,
  { params }: { params: Promise<{ endpoint: string }> },
) {
  if (!(await isModalDriveAuthorized())) {
    return Response.json(
      { message: "请先解锁 Modal 网盘。", code: "DRIVE_AUTH_REQUIRED" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    )
  }

  try {
    const { endpoint } = await params
    return await proxyModalDriveRequest(request, endpoint)
  } catch (error) {
    return modalDriveErrorResponse(error)
  }
}

export const GET = handle
export const POST = handle
export const PATCH = handle
export const DELETE = handle
