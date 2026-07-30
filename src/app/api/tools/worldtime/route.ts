import { apiErrorResponse, fetchUapi, liveJson } from "@/lib/uapi"

type WorldTimeResponse = {
  datetime: string
  offset_seconds: number
  offset_string: string
  query: string
  timestamp_unix: number
  timezone: string
  weekday: string
}

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  const searchParams = new URL(request.url).searchParams
  const city = (
    searchParams.get("city") ||
    process.env.TOOLBOX_DEFAULT_TIMEZONE ||
    "Asia/Shanghai"
  ).trim()

  if (!city || city.length > 80) {
    return Response.json(
      { message: "请输入有效的 IANA 时区，例如 Asia/Shanghai。" },
      { status: 400 },
    )
  }

  try {
    const data = await fetchUapi<WorldTimeResponse>("misc/worldtime", { city })
    return liveJson(data)
  } catch (error) {
    return apiErrorResponse(error)
  }
}
