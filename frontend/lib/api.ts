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
  { apiKey }: ApiClientOptions,
  headers: HeadersInit | undefined,
  json: boolean,
) {
  const nextHeaders = new Headers(headers)
  nextHeaders.set("X-API-Key", apiKey)
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

// A 5xx without a message from our own backend means the server is down or restarting
// (the Next proxy answers a bare "Internal Server Error"); say so instead of "HTTP 500".
function failureMessage(response: Response, payload: unknown) {
  const fallback = `HTTP ${response.status}`
  const message = errorMessage(payload, fallback)
  const isBareServerError =
    response.status >= 500 && (message === fallback || typeof payload === "string")
  return isBareServerError
    ? "The server is temporarily unavailable (it may be restarting). Please wait a minute and try again."
    : message
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
    throw new ApiError(failureMessage(response, payload), response.status, payload)
  }

  return payload as T
}

export async function apiDownload(
  path: string,
  auth: ApiClientOptions,
  jsonBody?: Record<string, unknown>,
): Promise<{ blob: Blob; filename: string }> {
  // With a jsonBody the download is requested with POST (e.g. a link to fetch).
  const response = await fetch(`${API_PREFIX}${path}`, {
    method: jsonBody ? "POST" : "GET",
    headers: apiHeaders(auth, undefined, !!jsonBody),
    body: jsonBody ? JSON.stringify(jsonBody) : undefined,
  })

  if (!response.ok) {
    const payload = await parseResponse(response)
    throw new ApiError(failureMessage(response, payload), response.status, payload)
  }

  const disposition = response.headers.get("Content-Disposition") || ""
  const filename = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i)?.[1]
  return {
    blob: await response.blob(),
    filename: filename ? decodeURIComponent(filename.replace(/\"$/, "")) : "database-datei.xlsm",
  }
}

export function backendMediaUrl(path: string) {
  return `${API_PREFIX}${path}`
}
