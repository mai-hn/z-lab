import { apiErrorResponse, fetchUapi, liveJson } from "@/lib/uapi"

type SayingResponse = { text: string }

export const dynamic = "force-dynamic"

export async function GET() {
  try {
    const data = await fetchUapi<SayingResponse>("saying")
    return liveJson(data)
  } catch (error) {
    return apiErrorResponse(error)
  }
}
