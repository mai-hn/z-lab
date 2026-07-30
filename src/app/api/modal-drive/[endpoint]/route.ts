import {
  fetchModalDriveMetadata,
  modalDriveErrorResponse,
  proxyModalDriveRequest,
} from "@/lib/modal-drive"
import { recordModalDriveResult } from "@/lib/modal-drive-catalog"
import { upsertVideoMetadata } from "@/lib/modal-drive-database"
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
    const requestForCatalog =
      endpoint === "files" && request.method === "PATCH"
        ? request.clone()
        : new Request(request.url, { method: request.method })
    const response = await proxyModalDriveRequest(request, endpoint)
    try {
      const metadataEntries = await recordModalDriveResult(
        requestForCatalog,
        endpoint,
        response.clone(),
      )
      const metadataResults = await Promise.allSettled(
        metadataEntries.slice(0, 5).map((entry) =>
          fetchModalDriveMetadata(entry.path),
        ),
      )
      for (const result of metadataResults) {
        if (result.status === "fulfilled" && result.value.video) {
          upsertVideoMetadata(result.value.entry, result.value.video)
        }
      }
    } catch {
      response.headers.set("X-Toolbox-Catalog-Warning", "local-database-write-failed")
    }
    return response
  } catch (error) {
    return modalDriveErrorResponse(error)
  }
}

export const GET = handle
export const POST = handle
export const PATCH = handle
export const DELETE = handle
