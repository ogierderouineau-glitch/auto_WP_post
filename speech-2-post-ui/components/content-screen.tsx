"use client"

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronLeft,
  FileText,
  Loader2,
  Search,
  RefreshCw,
  Save,
  Send,
  Sparkles,
} from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  approveSessionContent,
  loadContentSession,
  regenerateSessionDraft,
  startImageMetadataGeneration,
  saveSessionDraftFields,
  startSessionGeneration,
  startSessionPublish,
  waitForSessionJob,
  type ContentSession,
  type WorkbookStatus,
} from "@/lib/content-sessions"
import { ApiError } from "@/lib/api"
import { statusMessageClass } from "@/lib/status-style"

type FieldScope = "shared" | "acf"
type ContentSectionId = "wordpress" | "acf"
type OperationState = "idle" | "loading" | "success" | "error"
const ACTIVE_JOB_STORAGE = "speech2post_active_job"

type DraftField = {
  id: string
  scope: FieldScope
  key: string
  displayKey: string
  label: string
  value: string
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

function buildFields(session: ContentSession | null, workbook: WorkbookStatus | null): DraftField[] {
  if (!session) return []
  const shared = Object.entries(session.shared_fields || {}).map(([key, value]) => ({
    id: `shared:${key}`,
    scope: "shared" as const,
    key,
    displayKey: key,
    label: labelFromKey(key),
    value: displayValue(value),
    section: "wordpress" as const,
    trace: fieldTrace(session, key),
  }))
  const acf = Object.entries(session.acf_source_fields || {}).map(([key, value]) => {
    const trace = fieldTrace(session, key)
    const schema = workbook?.acf_fields?.find((field) => field.field_key === key)
    return { id: `acf:${key}`, scope: "acf" as const, key, displayKey: schema?.acf_field_name || key, label: schema?.label || labelFromKey(key), value: displayValue(value), section: "acf" as const, trace }
  })
  return [...shared, ...acf]
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

function hasMissingImageMetadata(session: ContentSession) {
  if (!session.image_refs.length) return false
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
  return session.image_refs.some((image) => !completed.has(image.media_id))
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
  onAiAssistedLinkPlacementChange,
  onBackToFacts,
  onContinueToWordPress,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  workbook: WorkbookStatus | null
  onSessionChange: (session: ContentSession) => void
  onRevisionFieldIdsChange: (fieldIds: string[]) => void
  onSelectedLinksChange: (links: Record<string, string>[]) => void
  onAiAssistedLinkPlacementChange: (enabled: boolean) => void
  onBackToFacts: () => void
  onContinueToWordPress: () => void
}) {
  const fields = useMemo(() => buildFields(session, workbook), [session, workbook])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [operation, setOperation] = useState<OperationState>("idle")
  const [activeAction, setActiveAction] = useState<"generate" | "revise" | null>(null)
  const [autosave, setAutosave] = useState<OperationState>("idle")
  const [backgroundMetadata, setBackgroundMetadata] = useState(false)
  const [message, setMessage] = useState("")
  const [agentMessage, setAgentMessage] = useState("")
  const [openSection, setOpenSection] = useState<ContentSectionId | null>("wordpress")
  const [openTrace, setOpenTrace] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [queuedLinks, setQueuedLinks] = useState<Record<string, string>>({})
  const [manualRevisionFieldIds, setManualRevisionFieldIds] = useState<string[]>([])
  const [linkRevisionFieldIds, setLinkRevisionFieldIds] = useState<Record<string, string[]>>({})
  const [aiAssistedLinkPlacement, setAiAssistedLinkPlacement] = useState(false)
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
  const canGenerate = !!auth && !!session && ["ready_to_generate", "needs_review", "ready_to_publish", "published"].includes(session.state)
  const canApprove = !!auth && !!session && draftReady && session.state === "needs_review"
  const visibleLinkIds = useMemo(() => {
    const selected = new Set((session?.selected_links || []).map((selection) => selection.link_id))
    return selected.size ? selected : new Set(session?.eligible_link_ids || [])
  }, [session?.eligible_link_ids, session?.selected_links])
  const linkCandidates = useMemo(
    () => (workbook?.internal_link_candidates || []).filter(
      (candidate) => !visibleLinkIds.size || visibleLinkIds.has(candidate.link_id),
    ),
    [visibleLinkIds, workbook?.internal_link_candidates],
  )
  const currentDraftContent = fields.map((field) => drafts[field.id] ?? field.value).join("\n")
  const usedLinkIds = new Set(
    linkCandidates
      .filter((candidate) => currentDraftContent.includes(candidate.target_url))
      .map((candidate) => candidate.link_id),
  )
  const normalizedSearch = search.trim().toLowerCase()
  const filteredFields = fields.filter((field) => !normalizedSearch || `${field.label} ${field.key} ${drafts[field.id] ?? field.value}`.toLowerCase().includes(normalizedSearch))
  const groupedFields = Object.fromEntries((Object.keys(CONTENT_SECTIONS) as ContentSectionId[]).map((id) => [id, filteredFields.filter((field) => field.section === id)])) as Record<ContentSectionId, DraftField[]>
  const selectedRevisionFieldIds = useMemo(
    () => [...new Set([
      ...manualRevisionFieldIds,
      ...Object.values(linkRevisionFieldIds).flat(),
    ])],
    [linkRevisionFieldIds, manualRevisionFieldIds],
  )
  const selectedRevisionFields = new Set(selectedRevisionFieldIds)
  const allRevisionFieldsSelected = fields.length > 0 && selectedRevisionFieldIds.length === fields.length
  const hasQueuedLinkInstruction = Object.values(queuedLinks).some(Boolean)

  useEffect(() => {
    onRevisionFieldIdsChange(selectedRevisionFieldIds)
  }, [onRevisionFieldIdsChange, selectedRevisionFieldIds])

  const selectedLinksForAgent = useMemo(() => {
    const selections = new Map(
      (session?.selected_links || []).map((selection) => [selection.link_id, { ...selection }]),
    )
    for (const [linkId, destination] of Object.entries(queuedLinks)) {
      if (!destination) continue
      const existing = selections.get(linkId)
      const candidate = linkCandidates.find((item) => item.link_id === linkId)
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
  }, [linkCandidates, queuedLinks, session?.selected_links])

  useEffect(() => {
    onSelectedLinksChange(selectedLinksForAgent)
  }, [onSelectedLinksChange, selectedLinksForAgent])

  useEffect(() => {
    onAiAssistedLinkPlacementChange(aiAssistedLinkPlacement)
  }, [aiAssistedLinkPlacement, onAiAssistedLinkPlacementChange])

  function toggleRevisionField(fieldId: string) {
    setManualRevisionFieldIds((current) => {
      const next = new Set(current)
      if (next.has(fieldId)) next.delete(fieldId)
      else next.add(fieldId)
      return [...next]
    })
  }

  function linkDestinationFieldIds(destination: string) {
    if (!destination) return []
    const matchingFieldIds = fields.filter((field) =>
      field.scope === "acf" && workbook?.acf_fields?.some((schema) =>
        schema.field_key === field.key && schema.acf_field_name === destination,
      ),
    ).map((field) => field.id)
    return matchingFieldIds
  }

  function setLinkDestination(linkId: string, destination: string) {
    setQueuedLinks((current) => ({ ...current, [linkId]: destination }))
    setLinkRevisionFieldIds((current) => ({
      ...current,
      [linkId]: linkDestinationFieldIds(destination),
    }))
  }

  function removeQueuedLink(linkId: string) {
    setQueuedLinks((current) => {
      const next = { ...current }
      delete next[linkId]
      return next
    })
    setLinkRevisionFieldIds((current) => {
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
    return sessionRef.current || session
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
    if (!["generate", "regenerate"].includes(storedJob.operation || "") || storedJob.sessionId !== session.session_id || !storedJob.jobId) return

    const controller = new AbortController()
    setOperation("loading")
    setActiveAction(storedJob.operation === "regenerate" ? "revise" : "generate")
    setMessage(storedJob.operation === "regenerate" ? "Regenerating selected fields..." : "Generating content...")
    void pollJob(storedJob.jobId, controller.signal)
      .then((nextSession) => {
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        onSessionChange(nextSession)
        setOperation("success")
        setMessage(storedJob.operation === "regenerate" ? "Selected fields regenerated." : "Draft generated.")
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return
        setOperation("error")
        setMessage(error instanceof Error ? error.message : "Could not generate draft.")
      })
      .finally(() => setActiveAction(null))

    return () => controller.abort()
  }, [auth, session?.session_id])

  async function handleGenerate() {
    if (!auth || !session) return
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
      const shouldRunBackgroundMetadata = hasMissingImageMetadata(nextSession)
      if (shouldRunBackgroundMetadata) {
        setBackgroundMetadata(true)
        void Promise.resolve(nextSession)
          .then(async (generatedSession) => {
            setMessage(isFirstGeneration ? "Generating image metadata before publishing..." : "Generating image metadata in the background...")
            const metadataJob = await startImageMetadataGeneration(auth, generatedSession)
            const metadataSession = await waitForSessionJob(auth, metadataJob.job_id)
            onSessionChange(metadataSession)
            return metadataSession
          })
          .then(async (metadataSession) => {
            if (!isFirstGeneration) {
              setMessage("Draft regenerated. Image metadata updated in the background.")
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
            setMessage(error instanceof Error ? `Draft regenerated, but background image metadata failed: ${error.message}` : "Draft regenerated, but background image metadata failed.")
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

  async function runSave() {
    try {
      await handleSave()
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not save draft fields.")
    }
  }

  async function handleAgentRegenerate() {
    if (!auth || !session || (!agentMessage.trim() && !hasQueuedLinkInstruction) || !selectedRevisionFieldIds.length) return
    setOperation("loading")
    setActiveAction("revise")
    setMessage("Sending instruction to content agent...")
    try {
      const saved = changedCount ? await handleSave() : await latestSessionAfterAutosave()
      let job
      try {
        job = await regenerateSessionDraft(
          auth,
          saved || session,
          agentMessage.trim(),
          selectedRevisionFieldIds,
          selectedLinksForAgent,
          aiAssistedLinkPlacement,
        )
      } catch (error) {
        if (!isSessionVersionConflict(error)) throw error
        setMessage("Session updated in the background. Syncing latest version and retrying regeneration...")
        const latestSession = await reloadLatestSession()
        job = await regenerateSessionDraft(
          auth,
          latestSession,
          agentMessage.trim(),
          selectedRevisionFieldIds,
          selectedLinksForAgent,
          aiAssistedLinkPlacement,
        )
      }
      sessionStorage.setItem(
        ACTIVE_JOB_STORAGE,
        JSON.stringify({
          jobId: job.job_id,
          operation: "regenerate",
          sessionId: session.session_id,
          at: new Date().toISOString(),
        }),
      )
      setMessage("Regenerating selected fields...")
      const nextSession = await pollJob(job.job_id)
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      onSessionChange(nextSession)
      setAgentMessage("")
      setManualRevisionFieldIds([])
      setLinkRevisionFieldIds({})
      setQueuedLinks({})
      setOperation("success")
      setMessage("Selected fields regenerated.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not regenerate draft.")
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
      <div className="pb-28">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-foreground sm:text-xl">Review generated content</h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Generate the draft, edit returned fields, inspect trace details, then approve before WordPress.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              id="s2p-content-generate-draft"
              type="button"
              onClick={handleGenerate}
              title={draftReady ? "Regenerates the full draft and ranks a fresh set of internal-link candidates." : "Generates the draft and ranks internal-link candidates."}
              disabled={operation === "loading" || !canGenerate}
              className="inline-flex items-center gap-2 rounded-md bg-ai px-3 py-2 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
            >
              {activeAction === "generate" ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              {draftReady ? "Regenerate draft" : "Generate draft"}
            </button>
            <button
              id="s2p-content-save-edits"
              type="button"
              onClick={runSave}
              disabled={operation === "loading" || !changedCount || !draftReady}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:opacity-60"
            >
              <Save className="size-4" />
              Save edits
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-border bg-card px-3 py-2">
            <p className="text-xs text-muted-foreground">Session state</p>
            <p className="mt-1 text-sm font-semibold text-foreground">{session.state}</p>
          </div>
          <div className="rounded-lg border border-border bg-card px-3 py-2">
            <p className="text-xs text-muted-foreground">Shared fields</p>
            <p className="mt-1 text-sm font-semibold text-foreground">{Object.keys(session.shared_fields || {}).length}</p>
          </div>
          <div className="rounded-lg border border-border bg-card px-3 py-2">
            <p className="text-xs text-muted-foreground">ACF fields</p>
            <p className="mt-1 text-sm font-semibold text-foreground">{Object.keys(session.acf_source_fields || {}).length}</p>
          </div>
          <div className="rounded-lg border border-border bg-card px-3 py-2">
            <p className="text-xs text-muted-foreground">Unsaved edits</p>
            <p className="mt-1 text-sm font-semibold text-foreground">
              {autosave === "loading" ? "Saving..." : autosave === "error" ? "Save failed" : changedCount}
            </p>
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
                      {multiline ? (
                        <textarea
                          id={`s2p-content-field-${field.id}`}
                          value={value}
                          rows={4}
                          onChange={(event) => setDrafts((current) => ({ ...current, [field.id]: event.target.value }))}
                          className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                        />
                      ) : (
                        <input
                          id={`s2p-content-field-${field.id}`}
                          value={value}
                          onChange={(event) => setDrafts((current) => ({ ...current, [field.id]: event.target.value }))}
                          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                        />
                      )}
                      {openTrace === field.id && <div className="mt-2"><TracePanel trace={field.trace || {}} /></div>}
                    </div>
                  )
                }) : <p className="px-4 py-5 text-sm text-muted-foreground">{normalizedSearch ? "No matching fields in this section." : "No fields in this section."}</p>}</div>}
                </div>
              })}
            </section>

            <aside className="min-w-0 space-y-4 lg:sticky lg:top-24 lg:self-start">
              <section className="rounded-xl border border-border bg-card p-4">
                <h2 className="text-sm font-semibold">Content agent</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {selectedRevisionFieldIds.length} of {fields.length} fields selected for revision.
                </p>
                <textarea
                  id="s2p-content-agent-instruction"
                  value={agentMessage}
                  onChange={(event) => setAgentMessage(event.target.value)}
                  rows={5}
                  placeholder="Describe what should change in the draft."
                  className="mt-3 w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                />
                <label
                  htmlFor="s2p-content-ai-assisted-placement"
                  className="mt-3 flex items-start gap-2 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground"
                >
                  <input
                    id="s2p-content-ai-assisted-placement"
                    type="checkbox"
                    checked={aiAssistedLinkPlacement}
                    onChange={(event) => setAiAssistedLinkPlacement(event.target.checked)}
                    disabled={operation === "loading"}
                    className="mt-0.5 size-4 accent-gold"
                  />
                  <span>
                    <span className="block font-medium text-foreground">AI-assisted placement</span>
                    <span className="block">
                      Let the agent place selected links by rewriting text when an exact anchor is not already present.
                    </span>
                  </span>
                </label>
                <button
                  id="s2p-content-revise-selected-fields"
                  type="button"
                  onClick={handleAgentRegenerate}
                  title="Revises the draft while preserving its candidates and adding checked unused links with their selected ACF destinations."
                  disabled={operation === "loading" || (!agentMessage.trim() && !hasQueuedLinkInstruction) || !selectedRevisionFieldIds.length}
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-ai px-3 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
                >
                  {activeAction === "revise" ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  Revise selected fields
                </button>
              </section>

              <section className="rounded-xl border border-border bg-card p-4">
                <h2 className="text-sm font-semibold">Internal links</h2>
                <div className="mt-3 space-y-2">
                  {linkCandidates.length ? linkCandidates.map((candidate) => {
                    const used = usedLinkIds.has(candidate.link_id)
                    const queued = Object.prototype.hasOwnProperty.call(queuedLinks, candidate.link_id)
                    return (
                      <div key={candidate.link_id} className="rounded-md border border-border bg-background p-2.5">
                        <label className="flex items-start gap-2">
                          {used ? (
                            <Check className="mt-0.5 size-4 shrink-0 text-confirm" aria-label="Used" />
                          ) : (
                            <input
                              id={`s2p-content-link-${candidate.link_id}`}
                              type="checkbox"
                              checked={queued}
                              onChange={(event) => {
                                const firstDestination = workbook?.internal_link_acf_fields?.[0]?.acf_field_name || ""
                                if (event.target.checked && firstDestination) {
                                  setLinkDestination(candidate.link_id, firstDestination)
                                } else {
                                  removeQueuedLink(candidate.link_id)
                                }
                              }}
                              disabled={!workbook?.internal_link_acf_fields?.length}
                              className="mt-0.5 size-4 accent-gold"
                            />
                          )}
                          <span className="min-w-0">
                            <span className="block text-xs font-medium text-foreground">{candidate.anchor_text}</span>
                            <span className="block truncate text-[11px] text-muted-foreground">{candidate.target_url}</span>
                          </span>
                        </label>
                        {!used && queued && (
                          <select
                            id={`s2p-content-link-destination-${candidate.link_id}`}
                            autoFocus
                            value={queuedLinks[candidate.link_id]}
                            onChange={(event) => {
                              const destination = event.target.value
                              setLinkDestination(candidate.link_id, destination)
                            }}
                            className="mt-2 w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs text-foreground"
                          >
                            {(workbook?.internal_link_acf_fields || []).map((field) => (
                              <option key={field.acf_field_name} value={field.acf_field_name}>{field.acf_field_name}</option>
                            ))}
                          </select>
                        )}
                        {!used && queued && queuedLinks[candidate.link_id] && (
                          <p className="mt-2 text-[11px] text-muted-foreground">
                            This ACF is preferred; the agent may fall back to another suitable field.
                          </p>
                        )}
                      </div>
                    )
                  }) : <p className="text-xs text-muted-foreground">No eligible link candidates.</p>}
                </div>
              </section>

              {!!Object.keys(session.validation_report || {}).length && (
                <section className="rounded-xl border border-warn/40 bg-card p-4">
                  <h2 className="flex items-center gap-2 text-sm font-semibold">
                    <AlertTriangle className="size-4 text-warn-foreground" />
                    Validation report
                  </h2>
                  <pre className="mt-3 max-h-56 overflow-auto rounded-md bg-background p-3 text-xs text-muted-foreground">
                    {JSON.stringify(session.validation_report, null, 2)}
                  </pre>
                </section>
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
            {session.approval.approved ? "Content is approved." : draftReady ? "Save edits before approving." : "Generate a draft to continue."}
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
