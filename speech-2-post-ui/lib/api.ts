export type ApiErrorPayload = {
  detail?: unknown
  message?: unknown
  error?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly payload: unknown

  constructor(message: string, status: number, payload: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.payload = payload
  }
}

export type ApiClientOptions = {
  apiKey: string
  userId: string
}

export type ApiRequestOptions = Omit<RequestInit, "body" | "headers"> & {
  body?: BodyInit | Record<string, unknown> | null
  headers?: HeadersInit
  json?: boolean
}

const API_PREFIX = "/backend"

function apiHeaders(
  { apiKey, userId }: ApiClientOptions,
  headers: HeadersInit | undefined,
  json: boolean,
) {
  const nextHeaders = new Headers(headers)
  nextHeaders.set("X-API-Key", apiKey)
  nextHeaders.set("X-User-ID", userId)
  if (json) nextHeaders.set("Content-Type", "application/json")
  return nextHeaders
}

function errorMessage(payload: unknown, fallback: string) {
  if (!payload || typeof payload !== "object") return fallback

  const data = payload as ApiErrorPayload
  const detail = data.detail ?? data.message ?? data.error
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item)
        const record = item as { loc?: unknown; msg?: unknown; message?: unknown }
        const location = Array.isArray(record.loc) ? record.loc.join(".") : ""
        const message = record.msg ?? record.message ?? JSON.stringify(item)
        return location ? `${location}: ${message}` : String(message)
      })
      .join("; ")
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail)
  return detail ? String(detail) : fallback
}

async function parseResponse(response: Response) {
  const text = await response.text()
  if (!text) return null

  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

export async function apiRequest<T>(
  path: string,
  auth: ApiClientOptions,
  options: ApiRequestOptions = {},
): Promise<T> {
  const json = options.json ?? !(options.body instanceof FormData)
  const body =
    json && options.body && !(options.body instanceof FormData)
      ? JSON.stringify(options.body)
      : (options.body as BodyInit | null | undefined)

  const response = await fetch(`${API_PREFIX}${path}`, {
    ...options,
    headers: apiHeaders(auth, options.headers, json),
    body,
  })
  const payload = await parseResponse(response)

  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, `HTTP ${response.status}`),
      response.status,
      payload,
    )
  }

  return payload as T
}

export function backendMediaUrl(path: string) {
  return `${API_PREFIX}${path}`
}
