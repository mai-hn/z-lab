import { apiErrorResponse, fetchUapi, liveJson } from "@/lib/uapi"

type WeatherResponse = {
  province: string
  city: string
  district?: string
  adcode?: string
  weather: string
  weather_icon: string
  temperature: number
  wind_direction: string
  wind_power: string
  humidity: number
  report_time: string
}

export const dynamic = "force-dynamic"

export async function GET(request: Request) {
  const searchParams = new URL(request.url).searchParams
  const city = (
    searchParams.get("city") ||
    process.env.TOOLBOX_DEFAULT_WEATHER_CITY ||
    "上海"
  ).trim()

  if (!city || city.length > 60) {
    return Response.json(
      { message: "请输入有效的城市名称。" },
      { status: 400 },
    )
  }

  try {
    const data = await fetchUapi<WeatherResponse>("misc/weather", {
      city,
      lang: "zh",
    })
    return liveJson(data)
  } catch (error) {
    return apiErrorResponse(error)
  }
}
