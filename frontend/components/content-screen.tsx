"use client"

import { InternalLinksPanel } from "@/components/internal-links-panel"
import { ActionHint } from "@/components/action-hint"

import { useActionWarning } from "@/components/action-warning"

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronLeft,
  FileText,
  Loader2,
  Search,
  Send,
  ScanText,
  Sparkles,
} from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  editSessionLinkCandidates,
  insertSessionLink,
  loadSessionLinkOptions,
  loadDraftFieldOptions,
  mergeDraftFieldValues,
  type DraftFieldOptions,
  type SessionLinkOptions,
  approveSessionContent,
  loadContentSession,
  startImageMetadataGeneration,
  startContentQualityCheck,
  saveSessionDraftFields,
  startSessionGeneration,
  startSessionPublish,
  waitForSessionJob,
  type ContentSession,
  type HtmlPatternOption,
  type WorkbookStatus,
} from "@/lib/content-sessions"
import { ApiError } from "@/lib/api"
import { statusMessageClass } from "@/lib/status-style"

type FieldScope = "shared" | "acf"
type ContentSectionId = "wordpress" | "acf"
type OperationState = "idle" | "loading" | "success" | "error"
type QualityFinding = {
  field_id: string
  category: string
  severity: "low" | "medium" | "high"
  explanation: string
  suggestion: string
}
type QualityCheck = {
  rating: "natural" | "needs_polish" | "formulaic"
  summary: string
  findings: QualityFinding[]
  reviewed_at?: string
}
const ACTIVE_JOB_STORAGE = "speech2post_active_job"

type DraftField = {
  id: string
  scope: FieldScope
  key: string
  displayKey: string
  label: string
  value: string
  valueType: string
  htmlPatternKeys: string[]
  section: ContentSectionId
  trace: Record<string, unknown> | null
}

function displayValue(value: unknown) {
  if (value == null) return ""
  if (typeof value === "string") return value
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ")
  if (typeof value === "object") return JSON.stringify(value, null, 2)
  return String(value)
}

function parseDraftValue(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return ""
  if (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  ) {
    try {
      return JSON.parse(trimmed) as unknown
    } catch {
      return value
    }
  }
  return value
}

function labelFromKey(key: string) {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function fieldTrace(session: ContentSession, key: string) {
  const trace = session.generation_trace || {}
  const candidates = [key, key.toLowerCase(), key.replace(/[- ]+/g, "_")]
  for (const candidate of candidates) {
    const value = trace[candidate]
    if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>
  }
  return null
}

function buildFields(session: ContentSession | null, workbook: WorkbookStatus | null, options: DraftFieldOptions | null): DraftField[] {
  if (!session) return []
  const shared = Object.entries(mergeDraftFieldValues(session.shared_fields || {}, options?.shared_fields)).map(([key, value]) => ({
    id: `shared:${key}`,
    scope: "shared" as const,
    key,
    displayKey: key,
    label: options?.shared_fields.find((field) => field.field_key === key)?.label || labelFromKey(key),
    value: displayValue(value),
    valueType: options?.shared_fields.find((field) => field.field_key === key)?.value_type || "string",
    htmlPatternKeys: [],
    section: "wordpress" as const,
    trace: fieldTrace(session, key),
  }))
  const acf = Object.entries(mergeDraftFieldValues(session.acf_source_fields || {}, options?.acf_fields)).map(([key, value]) => {
    const trace = fieldTrace(session, key)
    const schema = options?.acf_fields.find((field) => field.field_key === key) || workbook?.acf_fields?.find((field) => field.field_key === key)
    return { id: `acf:${key}`, scope: "acf" as const, key, displayKey: schema?.acf_field_name || key, label: schema?.label || labelFromKey(key), value: displayValue(value), valueType: schema?.value_type || "string", htmlPatternKeys: schema?.html_pattern_keys || [], section: "acf" as const, trace }
  })
  return [...shared, ...acf]
}

function htmlPreviewValue(value: string) {
  return value
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, "")
    // Keep malformed or self-closing script tags from reaching the sandboxed iframe.
    .replace(/<script\b/gi, "&lt;script")
    .replace(/<\/script\s*>/gi, "&lt;/script&gt;")
    .replace(/\s+on[a-z][\w:-]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, "")
    .replace(/\s+(href|src)\s*=\s*(["'])\s*javascript:[\s\S]*?\2/gi, "")
}

function HtmlFieldEditor({
  id,
  label,
  value,
  patterns,
  onChange,
  onSelect,
}: {
  id: string
  label: string
  value: string
  patterns: HtmlPatternOption[]
  onChange: (value: string) => void
  onSelect: (element: HTMLTextAreaElement) => void
}) {
  return (
    <div className="grid gap-2 lg:grid-cols-2">
      <div>
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">HTML source</span>
          {!!patterns.length && (
            <select
              aria-label={`Insert HTML mechanic into ${label}`}
              defaultValue=""
              onChange={(event) => {
                const pattern = patterns.find((item) => item.pattern_key === event.target.value)
                if (pattern) onChange(`${value}${value.trim() ? "\n\n" : ""}${pattern.template_html}`)
                event.target.value = ""
              }}
              className="max-w-56 rounded border border-border bg-background px-2 py-1 text-xs text-foreground"
            >
              <option value="" disabled>Insert HTML mechanic…</option>
              {patterns.map((pattern) => (
                <option key={pattern.pattern_key} value={pattern.pattern_key}>
                  {pattern.label_de}
                </option>
              ))}
            </select>
          )}
        </div>
        <textarea
          id={id}
          value={value}
          rows={8}
          spellCheck={false}
          onSelect={(event) => onSelect(event.currentTarget)}
          onChange={(event) => onChange(event.target.value)}
          className="h-48 w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-xs leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
        />
      </div>
      <div>
        <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Preview</span>
        <iframe
          key={value}
          title={`${label} HTML preview`}
          sandbox=""
          srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;padding:12px;font:14px/1.5 system-ui,sans-serif;color:#222;overflow-wrap:anywhere}img,video{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}td,th{border:1px solid #ddd;padding:6px}</style></head><body>${htmlPreviewValue(value)}</body></html>`}
          className="h-48 w-full rounded-md border border-border bg-white"
        />
      </div>
    </div>
  )
}

function changedMaps(fields: DraftField[], drafts: Record<string, string>) {
  const shared: Record<string, unknown> = {}
  const acf: Record<string, unknown> = {}
  for (const field of fields) {
    const draft = drafts[field.id] ?? field.value
    if (draft === field.value) continue
    if (field.scope === "shared") shared[field.key] = parseDraftValue(draft)
    else acf[field.key] = parseDraftValue(draft)
  }
  return { shared, acf }
}

function hasDraft(session: ContentSession | null) {
  if (!session) return false
  return Object.keys(session.shared_fields || {}).length > 0 || Object.keys(session.acf_source_fields || {}).length > 0
}

function contentQualityCheck(session: ContentSession | null): QualityCheck | null {
  const value = session?.generation_trace?.quality_check
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  const review = value as Record<string, unknown>
  if (typeof review.rating !== "string" || typeof review.summary !== "string") return null
  return {
    rating: review.rating as QualityCheck["rating"],
    summary: review.summary,
    findings: Array.isArray(review.findings) ? review.findings as QualityFinding[] : [],
    reviewed_at: typeof review.reviewed_at === "string" ? review.reviewed_at : undefined,
  }
}

function hasMissingMediaMetadata(session: ContentSession) {
  const completed = new Set(
    (session.image_metadata || [])
      .filter((row) => {
        if (!row || typeof row !== "object") return false
        const item = row as Record<string, unknown>
        return !!(
          item.image_alt ||
          item.image_title ||
          item.image_caption ||
          item.image_description ||
          item.image_description_wp ||
          item.image_filename
        )
      })
      .map((row) => String((row as Record<string, unknown>).media_id || ""))
      .filter(Boolean),
  )
  const missingImageMetadata = session.image_refs.some((image) => !completed.has(image.media_id))
  const videoMetadata = new Map(
    (session.video_metadata || []).map((row) => [String(row.media_id || ""), row]),
  )
  const missingVideoMetadata = (session.video_refs || []).some((video) => {
    const row = videoMetadata.get(video.media_id)
    return !row?.video_title || !row?.video_caption || !row?.video_description
  })
  return missingImageMetadata || missingVideoMetadata
}

function hasMedia(session: ContentSession) {
  return session.image_refs.length > 0 || (session.video_refs || []).length > 0
}

function TracePanel({ trace }: { trace: Record<string, unknown> }) {
  if (!Object.keys(trace || {}).length) {
    return <p className="text-sm text-muted-foreground">No generation trace yet.</p>
  }
  return (
    <pre className="max-h-80 overflow-auto rounded-lg border border-border bg-background p-3 text-xs leading-relaxed text-muted-foreground">
      {JSON.stringify(trace, null, 2)}
    </pre>
  )
}

const CONTENT_SECTIONS = {
  wordpress: { label: "WordPress fields", tone: "border-gold/40 bg-gold/10 text-foreground" },
  acf: { label: "ACF fields", tone: "border-ai/40 bg-ai/10 text-ai" },
} as const

export function ContentScreen({
  auth,
  session,
  workbook,
  onSessionChange,
  onRevisionFieldIdsChange,
  onSelectedLinksChange,
  onBackToFacts,
  onContinueToWordPress,
  onOpenAgent,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  workbook: WorkbookStatus | null
  onSessionChange: (session: ContentSession) => void
  onRevisionFieldIdsChange: (fieldIds: string[]) => void
  onSelectedLinksChange: (links: Record<string, string>[]) => void
  onBackToFacts: () => void
  onContinueToWordPress: () => void
  onOpenAgent: () => void
}) {
  const [draftFieldOptions, setDraftFieldOptions] = useState<DraftFieldOptions | null>(null)
  const fields = useMemo(() => buildFields(session, workbook, draftFieldOptions), [session, workbook, draftFieldOptions])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [operation, setOperation] = useState<OperationState>("idle")
  const [activeAction, setActiveAction] = useState<"generate" | "revise" | "review" | null>(null)
  const [autosave, setAutosave] = useState<OperationState>("idle")
  const [backgroundMetadata, setBackgroundMetadata] = useState(false)
  const [message, setMessage] = useState("")
  const [openSection, setOpenSection] = useState<ContentSectionId | null>("wordpress")
  const [openTrace, setOpenTrace] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [queuedLinks, setQueuedLinks] = useState<Record<string, string>>({})
  const [manualRevisionFieldIds, setManualRevisionFieldIds] = useState<string[]>([])
  const sessionRef = useRef<ContentSession | null>(session)
  const autosaveTimerRef = useRef<number | null>(null)
  const autosavePromiseRef = useRef<Promise<ContentSession | null> | null>(null)

  useEffect(() => {
    sessionRef.current = session
  }, [session])

  useLayoutEffect(() => {
    setDrafts(Object.fromEntries(fields.map((field) => [field.id, field.value])))
  }, [session?.session_id, session?.version])

  const changed = changedMaps(fields, drafts)
  const changedCount = Object.keys(changed.shared).length + Object.keys(changed.acf).length
  const changedSignature = JSON.stringify(changed)
  const draftReady = hasDraft(session)
  const review = contentQualityCheck(session)
  const canGenerate = !!auth && !!session && ["ready_to_generate", "needs_review", "ready_to_publish", "published"].includes(session.state)
  const canApprove = !!auth && !!session && draftReady && session.state === "needs_review"
  const [linkOptions, setLinkOptions] = useState<SessionLinkOptions | null>(null)
  const [linkSelection, setLinkSelection] = useState<{ fieldId: string; start: number; end: number; text: string } | null>(null)
  const [linkDialogOpen, setLinkDialogOpen] = useState(false)
  const [linkUrl, setLinkUrl] = useState("")
  const linkDialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (linkDialogOpen) linkDialog.current?.showModal()
  }, [linkDialogOpen])
  useEffect(() => {
    if (!auth || !session || !draftReady) return
    let cancelled = false
    Promise.all([loadSessionLinkOptions(auth, session), loadDraftFieldOptions(auth, session)]).then(([links, fields]) => {
      if (!cancelled) {
        setLinkOptions(links)
        setDraftFieldOptions(fields)
      }
    }).catch((error) => {
      if (!cancelled) setMessage(error instanceof Error ? error.message : "Could not load draft fields or link candidates.")
    })
    return () => { cancelled = true }
  }, [auth, session, draftReady])
  const linkCandidates = (linkOptions?.links || []).filter((link) => session?.selected_links.some((item) => item.link_id === link.link_id))
  const usedLinkIds = new Set(linkOptions?.placed_link_ids || [])
  const hasQueuedLinks = Object.keys(queuedLinks).some((id) => !usedLinkIds.has(id))
  const normalizedSearch = search.trim().toLowerCase()
  const filteredFields = fields.filter((field) => !normalizedSearch || `${field.label} ${field.key} ${drafts[field.id] ?? field.value}`.toLowerCase().includes(normalizedSearch))
  const groupedFields = Object.fromEntries((Object.keys(CONTENT_SECTIONS) as ContentSectionId[]).map((id) => [id, filteredFields.filter((field) => field.section === id)])) as Record<ContentSectionId, DraftField[]>
  // Candidate-only revisions choose their destination on the backend. Keep the
  // checked-field list manual so quality-check instructions do not trigger an
  // unnecessary model rewrite for an otherwise deterministic link insertion.
  const selectedRevisionFieldIds = manualRevisionFieldIds
  const revisionDisabledReason = !auth || !session ? "Create or load a session first."
    : operation === "loading" ? "Wait for the current content operation to finish."
    : !draftReady ? "Generate content before revising fields."
    : !selectedRevisionFieldIds.length && !hasQueuedLinks ? "Select at least one content field or link candidate to revise." : ""
  const selectedRevisionFields = new Set(selectedRevisionFieldIds)
  const allRevisionFieldsSelected = fields.length > 0 && selectedRevisionFieldIds.length === fields.length

  useEffect(() => {
    onRevisionFieldIdsChange(selectedRevisionFieldIds)
  }, [onRevisionFieldIdsChange, selectedRevisionFieldIds])

  const selectedLinksForAgent = useMemo(() => {
    const selections = new Map(
      (session?.selected_links || []).map((selection) => [selection.link_id, { ...selection }]),
    )
    const placed = new Set(linkOptions?.placed_link_ids || [])
    for (const [linkId, destination] of Object.entries(queuedLinks)) {
      if (placed.has(linkId) || !selections.has(linkId)) continue
      const existing = selections.get(linkId)
      const candidate = linkOptions?.links.find((item) => item.link_id === linkId)
      const selection = {
        ...existing,
        link_id: linkId,
        anchor_text: existing?.anchor_text || candidate?.anchor_text || "",
        destination_acf: destination,
        revision_requested: "true",
      }
      selections.set(linkId, selection)
    }
    return [...selections.values()]
  }, [linkOptions, queuedLinks, session?.selected_links])

  useEffect(() => {
    onSelectedLinksChange(selectedLinksForAgent)
  }, [onSelectedLinksChange, selectedLinksForAgent])

  function toggleRevisionField(fieldId: string) {
    setManualRevisionFieldIds((current) => {
      const next = new Set(current)
      if (next.has(fieldId)) next.delete(fieldId)
      else next.add(fieldId)
      return [...next]
    })
  }

  function setLinkDestination(linkId: string, destination: string) {
    setQueuedLinks((current) => ({ ...current, [linkId]: destination }))
  }

  function removeQueuedLink(linkId: string) {
    setQueuedLinks((current) => {
      const next = { ...current }
      delete next[linkId]
      return next
    })
  }

  function toggleContentSection(id: ContentSectionId) {
    setOpenSection((current) => current === id ? null : id)
  }

  useEffect(() => {
    if (!auth || !session || !draftReady || !changedCount || operation === "loading") return
    let cancelled = false
    autosaveTimerRef.current = window.setTimeout(() => {
      autosaveTimerRef.current = null
      setAutosave("loading")
      const requestSession = sessionRef.current || session
      const promise = saveSessionDraftFields(auth, requestSession, changed.shared, changed.acf)
        .then((data) => {
          if (!sessionRef.current || data.session.version >= sessionRef.current.version) {
            sessionRef.current = data.session
            onSessionChange(data.session)
          }
          if (!cancelled) setAutosave("success")
          return data.session
        })
        .catch(async (error) => {
          if (!isSessionVersionConflict(error)) {
            if (!cancelled) setAutosave("error")
            return null
          }
          const latest = await loadContentSession(auth, requestSession.session_id)
          sessionRef.current = latest.session
          onSessionChange(latest.session)
          const retried = await saveSessionDraftFields(auth, latest.session, changed.shared, changed.acf)
          sessionRef.current = retried.session
          onSessionChange(retried.session)
          if (!cancelled) setAutosave("success")
          return retried.session
        })
        .catch(() => {
          if (!cancelled) setAutosave("error")
          return null
        })
        .finally(() => {
          if (autosavePromiseRef.current === promise) autosavePromiseRef.current = null
        })
      autosavePromiseRef.current = promise
    }, 900)

    return () => {
      cancelled = true
      if (autosaveTimerRef.current !== null) {
        window.clearTimeout(autosaveTimerRef.current)
        autosaveTimerRef.current = null
      }
    }
  }, [auth, changedCount, changedSignature, draftReady, onSessionChange, operation, session])

  async function latestSessionAfterAutosave() {
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current)
      autosaveTimerRef.current = null
    }
    await autosavePromiseRef.current
    const latest = sessionRef.current || session
    if (auth && latest && changedCount) {
      const data = await saveSessionDraftFields(auth, latest, changed.shared, changed.acf)
      sessionRef.current = data.session
      onSessionChange(data.session)
      return data.session
    }
    return latest
  }

  async function pollJob(jobId: string, signal?: AbortSignal) {
    if (!auth) throw new Error("Authentication is required.")
    return waitForSessionJob(auth, jobId, {
      signal,
      onConnectionIssue: () => setMessage("Connection interrupted. Generation is still running; reconnecting..."),
      onConnectionRestored: () => setMessage("Connection restored. Generating content..."),
    })
  }

  function isSessionVersionConflict(error: unknown) {
    if (!(error instanceof ApiError) || error.status !== 409) return false
    if (/changed from version/i.test(error.message)) return true
    const payload = error.payload as { error_code?: unknown; detail?: { error_code?: unknown } | unknown } | null
    const code = typeof payload?.error_code === "string"
      ? payload.error_code
      : (typeof payload?.detail === "object" && payload?.detail && "error_code" in payload.detail && typeof (payload.detail as { error_code?: unknown }).error_code === "string")
        ? (payload.detail as { error_code: string }).error_code
        : ""
    return code === "session_version_conflict"
  }

  async function reloadLatestSession() {
    if (!auth || !session) throw new Error("Authentication is required.")
    const latest = await loadContentSession(auth, session.session_id)
    sessionRef.current = latest.session
    onSessionChange(latest.session)
    return latest.session
  }

  useEffect(() => {
    if (!auth || !session) return

    const rawJob = sessionStorage.getItem(ACTIVE_JOB_STORAGE)
    if (!rawJob) return

    let storedJob: { jobId?: string; operation?: string; sessionId?: string }
    try {
      storedJob = JSON.parse(rawJob) as typeof storedJob
    } catch {
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      return
    }
    if (!["generate", "regenerate", "quality_check"].includes(storedJob.operation || "") || storedJob.sessionId !== session.session_id || !storedJob.jobId) return

    const controller = new AbortController()
    setOperation("loading")
    setActiveAction(storedJob.operation === "quality_check" ? "review" : storedJob.operation === "regenerate" ? "revise" : "generate")
    setMessage(storedJob.operation === "quality_check" ? "Running quality check..." : storedJob.operation === "regenerate" ? "Regenerating selected fields..." : "Generating content...")
    void pollJob(storedJob.jobId, controller.signal)
      .then((nextSession) => {
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        onSessionChange(nextSession)
        setOperation("success")
        setMessage(storedJob.operation === "quality_check" ? "Quality check completed." : storedJob.operation === "regenerate" ? "Selected fields regenerated." : "Draft generated.")
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return
        setOperation("error")
        setMessage(error instanceof Error ? error.message : "Could not generate draft.")
      })
      .finally(() => setActiveAction(null))

    return () => controller.abort()
  }, [auth, session?.session_id])

  function captureLinkSelection(fieldId: string, element: HTMLInputElement | HTMLTextAreaElement) {
    const start = element.selectionStart || 0
    const end = element.selectionEnd || 0
    setLinkSelection(end > start ? { fieldId, start, end, text: element.value.slice(start, end) } : null)
  }

  async function handleCandidateAction(action: "add" | "remove" | "refresh", id?: string) {
    if (!auth || !session || operation === "loading") return
    setOperation("loading")
    try {
      const latest = await latestSessionAfterAutosave()
      if (!latest) return
      const data = await editSessionLinkCandidates(auth, latest, action, id)
      sessionRef.current = data.session
      onSessionChange(data.session)
      if (id) removeQueuedLink(id)
      if (action === "refresh") setQueuedLinks({})
      setOperation("success")
      setMessage(action === "refresh" ? "Unplaced candidates refreshed. Placed links kept; fewer suggestions are shown if no relevant alternatives remain."
        : action === "remove" ? "Candidate removed. Any linked text was kept." : "Candidate added. Select it to place it during revision.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not change candidates.")
    }
  }

  async function handleInsertLink() {
    if (!auth || !session || !linkSelection || operation === "loading") return
    const field = fields.find((field) => field.id === linkSelection.fieldId)
    if (!field) return
    setOperation("loading")
    try {
      const latest = await latestSessionAfterAutosave()
      if (!latest) return
      const data = await insertSessionLink(auth, latest, field.key, linkUrl, linkSelection)
      sessionRef.current = data.session
      onSessionChange(data.session)
      setLinkDialogOpen(false)
      setLinkSelection(null)
      setOperation("success")
      setMessage("Link added to the selected text.")
    } catch (error) {
      setLinkDialogOpen(false)
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not add link.")
    }
  }

  const { confirm, warningDialog } = useActionWarning()

  async function handleGenerate() {
    if (!auth || !session) return
    if (draftReady && !await confirm({
      message: "Regenerating replaces the full draft and refreshes internal links and media metadata. Revise selected fields to limit the changes.",
      alternative: selectedRevisionFieldIds.length || hasQueuedLinks ? { label: "Revise selected fields", action: onOpenAgent } : undefined,
    })) return
    const isFirstGeneration = !draftReady
    setOperation("loading")
    setActiveAction("generate")
    setMessage("Starting generation...")
    try {
      const currentSession = await latestSessionAfterAutosave()
      if (!currentSession) throw new Error("Session is unavailable.")
      const job = await startSessionGeneration(auth, currentSession, [])
      sessionStorage.setItem(
        ACTIVE_JOB_STORAGE,
        JSON.stringify({
          jobId: job.job_id,
          operation: "generate",
          sessionId: session.session_id,
          at: new Date().toISOString(),
        }),
      )
      setMessage("Generating content...")
      const nextSession = await pollJob(job.job_id)
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      onSessionChange(nextSession)
      setOperation("success")
      setMessage(isFirstGeneration ? "Draft generated. Preparing the WordPress post in the background..." : "Draft regenerated.")
      setQueuedLinks({})
      const shouldRunBackgroundMetadata = isFirstGeneration
        ? hasMissingMediaMetadata(nextSession)
        : hasMedia(nextSession)
      if (shouldRunBackgroundMetadata) {
        setBackgroundMetadata(true)
        void Promise.resolve(nextSession)
          .then(async (generatedSession) => {
            setMessage(isFirstGeneration ? "Generating media metadata before publishing..." : "Generating media metadata in the background...")
            const metadataJob = await startImageMetadataGeneration(auth, generatedSession)
            const metadataSession = await waitForSessionJob(auth, metadataJob.job_id)
            onSessionChange(metadataSession)
            return metadataSession
          })
          .then(async (metadataSession) => {
            if (!isFirstGeneration) {
              setMessage("Draft regenerated. Media metadata updated in the background.")
              return metadataSession
            }
            setMessage("Approving the first draft for WordPress...")
            const approved = await approveSessionContent(auth, metadataSession)
            onSessionChange(approved.session)
            setMessage("Creating the WordPress post...")
            const publishJob = await startSessionPublish(auth, approved.session)
            sessionStorage.setItem(
              ACTIVE_JOB_STORAGE,
              JSON.stringify({
                jobId: publishJob.job_id,
                operation: "publish",
                sessionId: approved.session.session_id,
                at: new Date().toISOString(),
              }),
            )
            const publishedSession = await waitForSessionJob(auth, publishJob.job_id)
            sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
            onSessionChange(publishedSession)
            setMessage("Draft generated and WordPress post created.")
          })
          .catch((error) => {
            if (isFirstGeneration) {
              setOperation("error")
              setMessage(error instanceof Error ? `Draft generated, but automatic WordPress publishing failed: ${error.message}` : "Draft generated, but automatic WordPress publishing failed.")
              return
            }
            setMessage(error instanceof Error ? `Draft regenerated, but background media metadata failed: ${error.message}` : "Draft regenerated, but background media metadata failed.")
          })
          .finally(() => setBackgroundMetadata(false))
      }
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not generate draft.")
    } finally {
      setActiveAction(null)
    }
  }

  async function handleSave() {
    if (!auth || !session || !changedCount) return session
    setOperation("loading")
    setActiveAction("revise")
    setMessage("Saving draft fields...")
    const currentSession = await latestSessionAfterAutosave()
    if (!currentSession) throw new Error("Session is unavailable.")
    let data
    try {
      data = await saveSessionDraftFields(auth, currentSession, changed.shared, changed.acf)
    } catch (error) {
      if (!isSessionVersionConflict(error)) throw error
      setMessage("Session updated in the background. Syncing latest version and retrying save...")
      const latestSession = await reloadLatestSession()
      data = await saveSessionDraftFields(auth, latestSession, changed.shared, changed.acf)
    }
    sessionRef.current = data.session
    onSessionChange(data.session)
    setOperation("success")
    setMessage("Draft fields saved.")
    return data.session
  }

  async function handleQualityCheck() {
    if (!auth || !session || !draftReady) return
    setOperation("loading")
    setActiveAction("review")
    setMessage("Starting quality check...")
    try {
      const currentSession = await latestSessionAfterAutosave()
      if (!currentSession) throw new Error("Session is unavailable.")
      const job = await startContentQualityCheck(auth, currentSession)
      sessionStorage.setItem(
        ACTIVE_JOB_STORAGE,
        JSON.stringify({
          jobId: job.job_id,
          operation: "quality_check",
          sessionId: currentSession.session_id,
          at: new Date().toISOString(),
        }),
      )
      setMessage("Reviewing clarity, tone, specificity, repetition and sentence rhythm...")
      const nextSession = await pollJob(job.job_id)
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      sessionRef.current = nextSession
      onSessionChange(nextSession)
      setOperation("success")
      setMessage("Quality check completed.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not complete the quality check.")
    } finally {
      setActiveAction(null)
    }
  }

  async function handleApprove() {
    if (!auth || !session) return
    setOperation("loading")
    setMessage("Approving content...")
    try {
      const saved = changedCount ? await handleSave() : await latestSessionAfterAutosave()
      const data = await approveSessionContent(auth, saved || session)
      onSessionChange(data.session)
      setOperation("success")
      setMessage("Content approved.")
      onContinueToWordPress()
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not approve content.")
    }
  }

  if (!session) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        Create or load a session before generating content.
      </div>
    )
  }

  return (
    <>
      {warningDialog}
      {linkDialogOpen && <dialog ref={linkDialog} aria-label="Add link" onCancel={() => setLinkDialogOpen(false)}
        className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-border bg-card p-5 text-foreground backdrop:bg-black/50">
        <form onSubmit={(event) => { event.preventDefault(); void handleInsertLink() }}>
          <h2 className="font-semibold">Add link to selected text</h2>
          <p className="my-3 break-words text-sm">{linkSelection?.text}</p>
          <input autoFocus type="url" required aria-label="Link URL" placeholder="https://…" value={linkUrl}
            onChange={(event) => setLinkUrl(event.target.value)} className="w-full rounded-md border border-border bg-background p-2 text-sm" />
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={() => setLinkDialogOpen(false)} className="rounded-md border border-border px-3 py-2 text-sm">Cancel</button>
            <button type="submit" disabled={operation === "loading"} className="rounded-md bg-ai px-3 py-2 text-sm text-ai-foreground disabled:opacity-50">Add link</button>
          </div>
        </form>
      </dialog>}
      <div className="pb-28">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-foreground sm:text-xl">Review generated content</h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Generate the draft, edit returned fields, inspect trace details, then approve before WordPress.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {draftReady && (
              <>
                <button
                  id="s2p-content-quality-check"
                  type="button"
                  onClick={handleQualityCheck}
                  title="Reviews the saved draft without changing it."
                  disabled={operation === "loading" || !draftReady}
                  className="inline-flex items-center gap-2 rounded-md border border-ai/40 bg-card px-3 py-2 text-sm font-semibold text-foreground transition-colors hover:bg-ai/10 disabled:opacity-60"
                >
                  {activeAction === "review" ? <Loader2 className="size-4 animate-spin" /> : <ScanText className="size-4 text-ai" />}
                  Quality check
                </button>
                <ActionHint reason={revisionDisabledReason}>
                <button type="button" id="s2p-content-revise-selected" onClick={onOpenAgent}
                  disabled={!!revisionDisabledReason}
                  title={revisionDisabledReason || "Give the content agent instructions for the selected fields."}
                  className="rounded-md border border-ai/40 bg-card px-3 py-2 text-sm font-semibold text-foreground disabled:opacity-60">
                  Revise selected fields
                </button>
                </ActionHint>
              </>
            )}
            <button
              id="s2p-content-generate-draft"
              type="button"
              onClick={handleGenerate}
              title={draftReady ? "Regenerates the full draft, ranks fresh internal-link candidates, and refreshes media metadata." : "Generates the draft and ranks internal-link candidates."}
              disabled={operation === "loading" || !canGenerate}
              className={`inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors hover:opacity-90 disabled:opacity-60 ${draftReady ? "bg-destructive text-white" : "bg-ai text-ai-foreground"}`}
            >
              {activeAction === "generate" ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              {draftReady ? "Regenerate draft" : "Generate draft"}
            </button>
          </div>
        </div>

        {message && (
          <p
            className={`mt-4 rounded-md px-3 py-2 text-sm ${statusMessageClass(operation, message)}`}
          >
            {message}
          </p>
        )}

        {!draftReady ? (
          <div className="mt-4 rounded-xl border border-border bg-card p-6 text-center">
            <FileText className="mx-auto size-8 text-muted-foreground" />
            <p className="mt-2 text-sm font-medium text-foreground">No generated draft yet</p>
            <p className="mt-1 text-sm text-muted-foreground">Generate content after facts are confirmed.</p>
          </div>
        ) : (
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <section className="min-w-0 space-y-3">
              <div className="rounded-xl border border-border bg-card p-3">
                <label className="flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2">
                  <Search className="size-4 text-muted-foreground" aria-hidden="true" />
                  <input id="s2p-content-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search fields, keys or content" className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
                </label>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(Object.keys(CONTENT_SECTIONS) as ContentSectionId[]).map((id) => (
                    <button key={id} id={`s2p-content-filter-${id}`} type="button" onClick={() => toggleContentSection(id)} aria-pressed={openSection === id} className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-opacity ${CONTENT_SECTIONS[id].tone} ${openSection === id ? "ring-2 ring-current/20" : "opacity-70 hover:opacity-100"}`}>
                      {CONTENT_SECTIONS[id].label} ({groupedFields[id].length})
                    </button>
                  ))}
                  <button
                    id="s2p-content-filter-internal-links"
                    type="button"
                    onClick={() => document.getElementById("s2p-content-internal-links")?.scrollIntoView({ behavior: "smooth", block: "start" })}
                    className="rounded-full border border-confirm/40 bg-confirm/10 px-3 py-1.5 text-xs font-semibold text-foreground transition-colors hover:bg-confirm/20"
                  >
                    Internal links ({linkCandidates.length})
                  </button>
                  <button
                    id="s2p-content-toggle-all-revision-fields"
                    type="button"
                    onClick={() => setManualRevisionFieldIds(allRevisionFieldsSelected ? [] : fields.map((field) => field.id))}
                    className="ml-auto rounded-full border border-border px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-muted"
                  >
                    {allRevisionFieldsSelected ? "Clear revision selection" : "Select all for revision"}
                  </button>
                </div>
              </div>
              {(Object.keys(CONTENT_SECTIONS) as ContentSectionId[]).map((id) => {
                const section = CONTENT_SECTIONS[id]
                const sectionFields = groupedFields[id]
                return <div key={id} className={`overflow-hidden rounded-xl border bg-card ${section.tone.split(" ")[0]}`}>
                  <button id={`s2p-content-section-${id}`} type="button" onClick={() => toggleContentSection(id)} aria-expanded={openSection === id} className={`flex w-full items-center justify-between px-4 py-3 text-left ${section.tone}`}>
                    <span className="text-sm font-semibold">{section.label} <span className="ml-1 text-xs opacity-70">({sectionFields.length})</span></span>
                    <ChevronDown className={`size-4 transition-transform ${openSection === id ? "rotate-180" : ""}`} />
                  </button>
                  {openSection === id && <div className="divide-y divide-border">{sectionFields.length ? sectionFields.map((field) => {
                  const value = drafts[field.id] ?? field.value
                  const multiline = value.length > 90 || value.includes("\n")
                  return (
                    <div key={field.id} className="block p-3">
                      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                        <label className="flex cursor-pointer items-start gap-2">
                          <input
                            id={`s2p-content-revise-field-${field.id}`}
                            type="checkbox"
                            checked={selectedRevisionFields.has(field.id)}
                            onChange={() => toggleRevisionField(field.id)}
                            aria-label={`Include ${field.label} in revision`}
                          className="mt-0.5 size-4 shrink-0 accent-ai"
                          />
                          <span>
                            <span className="text-sm font-medium text-foreground">{field.label}</span>
                            <span className="ml-2 font-mono text-[11px] text-muted-foreground">{field.scope}:{field.displayKey}</span>
                          </span>
                        </label>
                        <span className="flex items-center gap-2">{value !== field.value && (
                          <span className="rounded bg-ai/10 px-1.5 py-0.5 text-[10px] font-semibold text-ai">Edited</span>
                        )}<button id={`s2p-content-rules-trace-${field.id}`} type="button" onClick={() => setOpenTrace((current) => current === field.id ? null : field.id)} className="rounded-full border border-border px-2 py-0.5 text-[10px] font-semibold text-muted-foreground hover:bg-muted" aria-expanded={openTrace === field.id}>Rules trace</button></span>
                      </div>
                      {field.valueType === "html" ? (
                        <HtmlFieldEditor
                          id={`s2p-content-field-${field.id}`}
                          label={field.label}
                          value={value}
                          onSelect={(element) => captureLinkSelection(field.id, element)}
                          patterns={(workbook?.html_patterns || []).filter((pattern) => field.htmlPatternKeys.includes(pattern.pattern_key))}
                          onChange={(nextValue) => setDrafts((current) => ({ ...current, [field.id]: nextValue }))}
                        />
                      ) : multiline ? (
                        <textarea
                          id={`s2p-content-field-${field.id}`}
                          value={value}
                          rows={4}
                          onSelect={(event) => captureLinkSelection(field.id, event.currentTarget)}
                          onChange={(event) => setDrafts((current) => ({ ...current, [field.id]: event.target.value }))}
                          className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                        />
                      ) : (
                        <input
                          id={`s2p-content-field-${field.id}`}
                          value={value}
                          onSelect={(event) => captureLinkSelection(field.id, event.currentTarget)}
                          onChange={(event) => setDrafts((current) => ({ ...current, [field.id]: event.target.value }))}
                          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                        />
                      )}
                      {draftReady && field.scope === "acf" && linkOptions?.fields.some((item) => item.field_key === field.key) && (
                        <button type="button" id={`s2p-content-add-link-${field.id}`} disabled={operation === "loading" || linkSelection?.fieldId !== field.id}
                          title="Select text in this editor, then paste a URL. In HTML fields, select text in the source editor."
                          onClick={() => { setLinkUrl(""); setLinkDialogOpen(true) }}
                          className="mt-2 rounded-md border border-border px-3 py-1.5 text-xs font-semibold disabled:opacity-50">Add link to selected text</button>
                      )}
                      {openTrace === field.id && <div className="mt-2"><TracePanel trace={field.trace || {}} /></div>}
                    </div>
                  )
                }) : <p className="px-4 py-5 text-sm text-muted-foreground">{normalizedSearch ? "No matching fields in this section." : "No fields in this section."}</p>}</div>}
                </div>
              })}
            </section>

            <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-24 lg:self-start">
              {review && (
                <details open className="group order-2 rounded-xl border border-ai/40 bg-card">
                  <summary className="flex cursor-pointer list-none items-start justify-between gap-3 p-4">
                    <div>
                      <h2 className="flex items-center gap-2 text-sm font-semibold">
                        Quality check
                        <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
                      </h2>
                    </div>
                    <span className={[
                      "shrink-0 rounded-full px-2 py-1 text-[10px] font-semibold",
                      review.rating === "natural"
                        ? "bg-confirm/12 text-confirm"
                        : review.rating === "formulaic"
                          ? "bg-warn/20 text-warn-foreground"
                          : "bg-ai/10 text-ai",
                    ].join(" ")}>
                      {review.rating.replace("_", " ")}
                    </span>
                  </summary>
                  <div className="border-t border-border px-4 pb-4">
                    <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                      Overall diagnostic: {review.summary}
                    </p>
                    {!!review.findings.length && (
                      <div className="mt-3 flex items-center justify-between gap-2">
                      <span className="text-[11px] text-muted-foreground">
                        Select fields for revision
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          const flaggedFieldIds = [...new Set(review.findings.map((finding) => finding.field_id))]
                          const allSelected = flaggedFieldIds.every((fieldId) => selectedRevisionFields.has(fieldId))
                          setManualRevisionFieldIds((current) => allSelected
                            ? current.filter((fieldId) => !flaggedFieldIds.includes(fieldId))
                            : [...new Set([...current, ...flaggedFieldIds])])
                        }}
                        className="rounded-full border border-border px-2 py-1 text-[10px] font-semibold text-foreground hover:bg-muted"
                      >
                        {[...new Set(review.findings.map((finding) => finding.field_id))]
                          .every((fieldId) => selectedRevisionFields.has(fieldId))
                          ? "Clear flagged"
                          : "Select all flagged"}
                      </button>
                      </div>
                    )}
                    <div className="mt-3 max-h-80 space-y-2 overflow-y-auto pr-1">
                      {review.findings.length ? review.findings.map((finding, index) => (
                      <div key={`${finding.field_id}-${index}`} className="rounded-md border border-border bg-background p-3">
                        <div className="flex items-center justify-between gap-2">
                          <label className="flex min-w-0 cursor-pointer items-start gap-2">
                            <input
                              type="checkbox"
                              checked={selectedRevisionFields.has(finding.field_id)}
                              onChange={() => toggleRevisionField(finding.field_id)}
                              aria-label={`Include ${finding.field_id} in revision`}
                              className="mt-0.5 size-4 shrink-0 accent-ai"
                            />
                            <button
                              type="button"
                              onClick={(event) => {
                                event.preventDefault()
                                document.getElementById(`s2p-content-field-${finding.field_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
                              }}
                              className="truncate font-mono text-[11px] font-semibold text-ai hover:underline"
                            >
                              {finding.field_id}
                            </button>
                          </label>
                          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
                            {finding.severity}
                          </span>
                        </div>
                        <p className="mt-2 text-xs leading-relaxed text-foreground">{finding.explanation}</p>
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                          Suggestion: {finding.suggestion}
                        </p>
                      </div>
                      )) : (
                        <p className="rounded-md bg-confirm/10 px-3 py-2 text-xs text-foreground">
                          No concrete quality issues were found.
                        </p>
                      )}
                    </div>
                  </div>
                </details>
              )}
              <InternalLinksPanel session={session} options={linkOptions} queued={queuedLinks} busy={operation === "loading" || backgroundMetadata}
                onDestination={setLinkDestination}
                onToggle={(id) => Object.hasOwn(queuedLinks, id) ? removeQueuedLink(id) : setLinkDestination(id, "")}
                onAction={(action, id) => { void handleCandidateAction(action, id) }} />

              {!!Object.keys(session.validation_report || {}).length && (
                <details className="group order-3 rounded-xl border border-warn/40 bg-card p-4">
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-semibold">
                    <AlertTriangle className="size-4 text-warn-foreground" />
                    Validation report
                    <ChevronDown className="ml-auto size-4 transition-transform group-open:rotate-180" />
                  </summary>
                  <pre className="mt-3 max-h-56 overflow-auto rounded-md bg-background p-3 text-xs text-muted-foreground">
                    {JSON.stringify(session.validation_report, null, 2)}
                  </pre>
                </details>
              )}
            </aside>
          </div>
        )}
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-3 sm:px-4">
          <button
            id="s2p-content-back-to-facts"
            type="button"
            onClick={onBackToFacts}
            className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
          >
            <ChevronLeft className="size-4" />
            Back to Facts
          </button>
          <div className="hidden flex-1 text-sm text-muted-foreground sm:block">
            {session.approval.approved ? "Content is approved." : draftReady ? "Edits save automatically before approval." : "Generate a draft to continue."}
          </div>
          <button
            id="s2p-content-approve"
            type="button"
            onClick={handleApprove}
            disabled={operation === "loading" || !canApprove}
            className="ml-auto inline-flex items-center gap-2 rounded-md bg-confirm px-4 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 sm:ml-0"
          >
            {operation === "loading" ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
            Approve content
          </button>
          {session.approval.approved && (
            <button
              id="s2p-content-continue-to-wordpress"
              type="button"
              onClick={onContinueToWordPress}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
            >
              <Send className="size-4" />
              WordPress
            </button>
          )}
        </div>
      </div>
    </>
  )
}
