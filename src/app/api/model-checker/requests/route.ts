import {
  clearModelRequests,
  listModelRequests,
} from "@/lib/model-tester-database"

export const dynamic = "force-dynamic"

export function GET(request: Request) {
  const search = new URL(request.url).searchParams
  const channelId = search.get("channelId")?.trim() || undefined
  const limit = Number(search.get("limit") || 50)
  return Response.json(
    {
      requests: listModelRequests(
        channelId,
        Number.isFinite(limit) ? limit : 50,
      ),
    },
    { headers: { "Cache-Control": "no-store" } },
  )
}

export function DELETE(request: Request) {
  const channelId = new URL(request.url).searchParams.get("channelId")?.trim() || undefined
  clearModelRequests(channelId)
  return Response.json({ ok: true }, { headers: { "Cache-Control": "no-store" } })
}
