import { apiDownload, apiRequest, type ApiClientOptions } from "@/lib/api"

export type AuthClient = {
  client_id: string
  wp_base_url?: string
  status?: string
}

export type ClientsResponse = {
  clients: AuthClient[]
}

export type PostTypeOption = {
  post_type_key: string
  display_name_de: string
  wp_category_name?: string
  default_language?: string
  generation_enabled?: boolean
  template_ready?: boolean
  description_de?: string
  voice_instructions?: string
}

export type FactSchemaField = {
  field_key: string
  label: string
  required: boolean
}

export type WorkbookStatus = {
  filename?: string
  sha256?: string
  storage_mode?: string
  selected_post_type_key?: string | null
  post_types: PostTypeOption[]
  fact_schema: FactSchemaField[]
  acf_fields?: AcfFieldOption[]
  internal_link_candidates?: InternalLinkCandidate[]
  internal_link_acf_fields?: InternalLinkAcfField[]
}

export type InternalLinkCandidate = {
  link_id: string
  anchor_text: string
  target_url: string
  usage_context?: string
  priority?: string
}

export type InternalLinkAcfField = {
  acf_field_name: string
  label: string
}

export type AcfFieldOption = {
  field_key: string
  acf_field_name: string
  label: string
}

export type FactValue = {
  value: unknown
  source: string
  confidence: number
  confirmed: boolean
}

export type MediaReference = {
  media_id: string
  filename: string
  storage_uri: string
  content_type: string
  size_bytes: number
}

export type SessionImage = MediaReference & {
  processed_filename?: string
  processed_path?: string
  operations: string[]
  metadata: Record<string, unknown>
  context_transcript: string
  use_vision_for_metadata: boolean
  is_featured: boolean
}

export type SelectedMediaContext = {
  mediaId: string
  filename: string
  displayName: string
}

export type ContentSession = {
  session_id: string
  user_id: string
  post_type_key: string
  wordpress_post_type: string
  state: string
  language: string
  manual_text: string
  audio_refs: MediaReference[]
  image_refs: MediaReference[]
  transcript: string
  extracted_facts: Record<string, FactValue>
  confirmed_facts: Record<string, FactValue>
  clarification_questions: string[]
  shared_fields: Record<string, unknown>
  acf_source_fields: Record<string, unknown>
  selected_links: Record<string, string>[]
  eligible_link_ids: string[]
  processed_images: Record<string, unknown>[]
  image_metadata: Record<string, unknown>[]
  image_context_transcripts: Record<string, string>
  image_metadata_vision: Record<string, boolean>
  wordpress_payload: Record<string, unknown>
  published_wordpress_payload: Record<string, unknown>
  validation_report: Record<string, unknown>
  generation_trace: Record<string, unknown>
  draft_chat: Record<string, string>[]
  approval: {
    approved: boolean
    approved_by?: string | null
    approved_at?: string | null
  }
  wordpress_result: Record<string, unknown>
  ai_usage: Record<string, unknown>
  workflow_steps: Record<string, string>
  created_at: string
  updated_at: string
  version: number
}

export type SessionResponse = {
  session: ContentSession
}

export type RecentSession = {
  session_id: string
  user_id?: string
  client_id?: string
  post_type?: string
  post_type_key?: string
  state?: string
  status?: string
  created_at?: string
  updated_at?: string
  has_images?: boolean
  has_transcript?: boolean
  has_draft?: boolean
  wordpress_post_id?: number | null
}

export type RecentSessionsResponse = {
  sessions: RecentSession[]
}

export type SessionJob = {
  job_id: string
  session_id?: string
  operation?: string
  status: "queued" | "running" | "failed" | "complete" | "not_found"
  session?: ContentSession | null
  error?: string | null
}

export async function validateImportKey(auth: ApiClientOptions) {
  return apiRequest<ClientsResponse>("/clients", auth)
}

export async function loadWorkbook(auth: ApiClientOptions, postTypeKey?: string) {
  const suffix = postTypeKey ? `?post_type_key=${encodeURIComponent(postTypeKey)}` : ""
  return apiRequest<WorkbookStatus>(`/api/content-sessions/_workbook${suffix}`, auth, {
    json: false,
  })
}

export async function uploadKnowledgeWorkbook(auth: ApiClientOptions, file: File, postTypeKey = "") {
  const form = new FormData()
  form.append("workbook", file)
  if (postTypeKey) form.append("post_type", postTypeKey)
  return apiRequest<unknown>("/app/knowledge/workbook", auth, { method: "POST", body: form })
}

export async function downloadKnowledgeWorkbook(auth: ApiClientOptions) {
  const { blob, filename } = await apiDownload("/app/knowledge/workbook", auth)
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1500)
}

export async function createContentSession(auth: ApiClientOptions, postTypeKey: string) {
  return apiRequest<SessionResponse>("/api/content-sessions", auth, {
    method: "POST",
    body: {
      user_id: auth.userId,
      post_type_key: postTypeKey,
    },
  })
}

export async function loadContentSession(auth: ApiClientOptions, sessionId: string) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${encodeURIComponent(sessionId)}`, auth, {
    json: false,
  })
}

export async function loadRecentContentSessions(auth: ApiClientOptions, limit = 20) {
  return apiRequest<RecentSessionsResponse>(`/api/content-sessions/recent?limit=${limit}`, auth, {
    json: false,
  })
}

export async function uploadSessionImage(
  auth: ApiClientOptions,
  session: ContentSession,
  file: File,
  useVision = false,
) {
  const form = new FormData()
  form.append("expected_version", String(session.version))
  form.append("kind", "image")
  form.append("use_vision", String(useVision))
  form.append("upload", file)

  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/uploads`, auth, {
    method: "POST",
    body: form,
  })
}

export async function setSessionFeaturedImage(
  auth: ApiClientOptions,
  session: ContentSession,
  filename: string,
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/featured-image`, auth, {
    method: "PUT",
    body: {
      expected_version: session.version,
      filename,
    },
  })
}

export async function saveSessionImageMetadata(
  auth: ApiClientOptions,
  session: ContentSession,
  filename: string,
  metadata: Record<string, unknown>,
  useVisionForMetadata: boolean,
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/image-metadata`, auth, {
    method: "PUT",
    body: {
      expected_version: session.version,
      filename,
      metadata,
      use_vision_for_metadata: useVisionForMetadata,
    },
  })
}

export async function saveSessionImageContextTranscript(
  auth: ApiClientOptions,
  session: ContentSession,
  filename: string,
  transcript: string,
) {
  return apiRequest<SessionResponse>(
    `/api/content-sessions/${session.session_id}/image-context-transcript`,
    auth,
    {
      method: "PUT",
      body: {
        expected_version: session.version,
        filename,
        transcript,
      },
    },
  )
}

export async function optimizeSessionImage(
  auth: ApiClientOptions,
  session: ContentSession,
  filename: string,
  prompt: string,
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/images/optimize`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      filename,
      prompt,
    },
  })
}

export async function restoreSessionImageOriginal(
  auth: ApiClientOptions,
  session: ContentSession,
  filename: string,
) {
  return apiRequest<SessionResponse>(
    `/api/content-sessions/${session.session_id}/images/restore-original?filename=${encodeURIComponent(filename)}`,
    auth,
    {
      method: "POST",
      body: {
        expected_version: session.version,
      },
    },
  )
}

export async function removeSessionImage(
  auth: ApiClientOptions,
  session: ContentSession,
  filename: string,
) {
  return apiRequest<SessionResponse>(
    `/api/content-sessions/${session.session_id}/media/images/${encodeURIComponent(filename)}`,
    auth,
    {
      method: "DELETE",
      body: {
        expected_version: session.version,
      },
    },
  )
}

export async function transcribeSessionRecording(
  auth: ApiClientOptions,
  session: ContentSession,
  file: File,
) {
  const form = new FormData()
  form.append("upload", file)

  return apiRequest<{ text: string }>(
    `/api/content-sessions/${session.session_id}/draft-chat/transcribe`,
    auth,
    {
      method: "POST",
      body: form,
    },
  )
}

export async function saveSessionTranscript(
  auth: ApiClientOptions,
  session: ContentSession,
  transcript: string,
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/inputs`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      manual_text: transcript,
      confirmed_facts: {},
    },
  })
}

export async function analyzeSessionInputs(
  auth: ApiClientOptions,
  session: ContentSession,
  reviewFactKeys?: string[],
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/analyze`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      ...(reviewFactKeys ? { review_fact_keys: reviewFactKeys } : {}),
    },
  })
}

export async function saveSessionFactCorrections(
  auth: ApiClientOptions,
  session: ContentSession,
  corrections: Record<string, unknown>,
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/answers`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      corrections,
    },
  })
}

export async function startSessionGeneration(
  auth: ApiClientOptions,
  session: ContentSession,
  selectedLinks = session.selected_links || [],
) {
  return apiRequest<SessionJob>(`/api/content-sessions/${session.session_id}/generate-job`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      shared_fields: {},
      acf_source_fields: {},
      selected_links: selectedLinks,
      current_url: null,
      use_vision_for_image_metadata: false,
    },
  })
}

export async function loadSessionJob(auth: ApiClientOptions, jobId: string, signal?: AbortSignal) {
  return apiRequest<SessionJob>(`/api/content-sessions/jobs/${jobId}`, auth, {
    json: false,
    signal,
  })
}

export async function saveSessionDraftFields(
  auth: ApiClientOptions,
  session: ContentSession,
  sharedFields: Record<string, unknown>,
  acfSourceFields: Record<string, unknown>,
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/draft-fields`, auth, {
    method: "PUT",
    body: {
      expected_version: session.version,
      shared_fields: sharedFields,
      acf_source_fields: acfSourceFields,
    },
  })
}

export async function regenerateSessionDraft(
  auth: ApiClientOptions,
  session: ContentSession,
  message: string,
  revisionFieldIds: string[],
  selectedLinks = session.selected_links || [],
) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/draft-chat`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      shared_fields: {},
      acf_source_fields: {},
      selected_links: selectedLinks,
      current_url: null,
      use_vision_for_image_metadata: false,
      message,
      revision_field_ids: revisionFieldIds,
    },
  })
}

export async function approveSessionContent(auth: ApiClientOptions, session: ContentSession) {
  return apiRequest<SessionResponse>(`/api/content-sessions/${session.session_id}/approve`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      user_id: auth.userId,
    },
  })
}

export async function startSessionPublish(
  auth: ApiClientOptions,
  session: ContentSession,
  {
    targetPostId = null,
    forceCreateNew = false,
    partialUpdate = false,
    sharedFields = {},
    acfSourceFields = {},
  }: {
    targetPostId?: number | null
    forceCreateNew?: boolean
    partialUpdate?: boolean
    sharedFields?: Record<string, unknown>
    acfSourceFields?: Record<string, unknown>
  } = {},
) {
  const postIdPart = targetPostId ? `update-${targetPostId}` : "create"
  const modePart = forceCreateNew ? "new" : partialUpdate ? "partial" : "full"
  return apiRequest<SessionJob>(`/api/content-sessions/${session.session_id}/publish-job`, auth, {
    method: "POST",
    body: {
      expected_version: session.version,
      idempotency_key: `${session.session_id}-${postIdPart}-${modePart}-${Date.now()}`,
      target_post_id: targetPostId,
      force_create_new: forceCreateNew,
      partial_update: partialUpdate,
      shared_fields: sharedFields,
      acf_source_fields: acfSourceFields,
    },
  })
}

export function sessionImages(session: ContentSession): SessionImage[] {
  const processedByMediaId = new Map(
    session.processed_images.map((item) => [String(item.media_id || ""), item]),
  )
  const metadataByMediaId = new Map(
    session.image_metadata.map((item) => [String(item.media_id || ""), item]),
  )
  const featuredMediaId = session.image_metadata.find(
    (item) => String(item.image_usage || "") === "featured",
  )?.media_id

  return session.image_refs.map((reference) => {
    const processed = processedByMediaId.get(reference.media_id)
    const metadata = metadataByMediaId.get(reference.media_id) || {}
    return {
      ...reference,
      processed_filename: typeof processed?.filename === "string" ? processed.filename : undefined,
      processed_path: typeof processed?.path === "string" ? processed.path : undefined,
      operations: Array.isArray(processed?.operations)
        ? processed.operations.map((item) => String(item))
        : [],
      metadata,
      context_transcript: (session.image_context_transcripts || {})[reference.media_id] || "",
      use_vision_for_metadata: session.image_metadata_vision?.[reference.media_id] === true,
      is_featured: featuredMediaId === reference.media_id,
    }
  })
}

export function imageUrl(session: ContentSession, filename: string, original = false) {
  const suffix = original ? "/original" : ""
  return `/backend/api/content-sessions/${session.session_id}/media/images/${encodeURIComponent(filename)}${suffix}?v=${session.version}`
}
