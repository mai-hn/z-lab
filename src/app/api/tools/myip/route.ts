import { apiErrorResponse, fetchUapi, liveJson } from "@/lib/uapi"

type MyIpResponse = {
  ip: string
  region: string
  isp: string
  llc?: string
  asn: string
  latitude?: number
  longitude?: number
}

export const dynamic = "force-dynamic"

export async function GET() {
  try {
    const data = await fetchUapi<MyIpResponse>("network/myip")
    return liveJson(data)
  } catch (error) {
    return apiErrorResponse(error)
  }
}
