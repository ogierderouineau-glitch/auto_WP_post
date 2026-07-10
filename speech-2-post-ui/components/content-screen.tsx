"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  FileText,
  Loader2,
  RefreshCw,
  Save,
  Send,
  Sparkles,
} from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  approveSessionContent,
  loadSessionJob,
  regenerateSessionDraft,
  saveSessionDraftFields,
  startSessionGeneration,
  type ContentSession,
} from "@/lib/content-sessions"

type FieldScope = "shared" | "acf"
type OperationState = "idle" | "loading" | "success" | "error"
const ACTIVE_JOB_STORAGE = "speech2post_active_job"

type DraftField = {
  id: string
  scope: FieldScope
  key: string
  label: string
  value: string
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

function buildFields(session: ContentSession | null): DraftField[] {
  if (!session) return []
  const shared = Object.entries(session.shared_fields || {}).map(([key, value]) => ({
    id: `shared:${key}`,
    scope: "shared" as const,
    key,
    label: labelFromKey(key),
    value: displayValue(value),
  }))
  const acf = Object.entries(session.acf_source_fields || {}).map(([key, value]) => ({
    id: `acf:${key}`,
    scope: "acf" as const,
    key,
    label: labelFromKey(key),
    value: displayValue(value),
  }))
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

export function ContentScreen({
  auth,
  session,
  onSessionChange,
  onBackToFacts,
  onContinueToWordPress,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  onSessionChange: (session: ContentSession) => void
  onBackToFacts: () => void
  onContinueToWordPress: () => void
}) {
  const fields = useMemo(() => buildFields(session), [session])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [operation, setOperation] = useState<OperationState>("idle")
  const [autosave, setAutosave] = useState<OperationState>("idle")
  const [message, setMessage] = useState("")
  const [agentMessage, setAgentMessage] = useState("")
  const [traceOpen, setTraceOpen] = useState(false)

  useEffect(() => {
    setDrafts(Object.fromEntries(fields.map((field) => [field.id, field.value])))
  }, [session?.session_id, session?.version])

  const changed = changedMaps(fields, drafts)
  const changedCount = Object.keys(changed.shared).length + Object.keys(changed.acf).length
  const changedSignature = JSON.stringify(changed)
  const draftReady = hasDraft(session)
  const canGenerate = !!auth && !!session && ["ready_to_generate", "needs_review", "ready_to_publish", "published"].includes(session.state)
  const canApprove = !!auth && !!session && draftReady && session.state === "needs_review"

  useEffect(() => {
    if (!auth || !session || !draftReady || !changedCount || operation === "loading") return
    let cancelled = false
    const timeout = window.setTimeout(() => {
      setAutosave("loading")
      saveSessionDraftFields(auth, session, changed.shared, changed.acf)
        .then((data) => {
          if (!cancelled) {
            onSessionChange(data.session)
            setAutosave("success")
          }
        })
        .catch(() => {
          if (!cancelled) setAutosave("error")
        })
    }, 900)

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [auth, changedCount, changedSignature, draftReady, onSessionChange, operation, session])

  async function pollJob(jobId: string, signal?: AbortSignal) {
    if (!auth) throw new Error("Authentication is required.")
    while (!signal?.aborted) {
      const job = await loadSessionJob(auth, jobId, signal)
      if (job.status === "complete" && job.session) return job.session
      if (job.status === "failed") throw new Error(job.error || "Generation failed.")
      if (job.status === "not_found") throw new Error(job.error || "Generation job was not found.")
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    throw new DOMException("Generation polling was cancelled.", "AbortError")
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
    if (storedJob.operation !== "generate" || storedJob.sessionId !== session.session_id || !storedJob.jobId) return

    const controller = new AbortController()
    setOperation("loading")
    setMessage("Generating content...")
    void pollJob(storedJob.jobId, controller.signal)
      .then((nextSession) => {
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        onSessionChange(nextSession)
        setOperation("success")
        setMessage("Draft generated.")
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return
        setOperation("error")
        setMessage(error instanceof Error ? error.message : "Could not generate draft.")
      })

    return () => controller.abort()
  }, [auth, session?.session_id])

  async function handleGenerate() {
    if (!auth || !session) return
    setOperation("loading")
    setMessage("Starting generation...")
    try {
      const job = await startSessionGeneration(auth, session)
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
      setMessage("Draft generated.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not generate draft.")
    }
  }

  async function handleSave() {
    if (!auth || !session || !changedCount) return session
    setOperation("loading")
    setMessage("Saving draft fields...")
    const data = await saveSessionDraftFields(auth, session, changed.shared, changed.acf)
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
    if (!auth || !session || !agentMessage.trim()) return
    setOperation("loading")
    setMessage("Sending instruction to content agent...")
    try {
      const saved = changedCount ? await handleSave() : session
      const data = await regenerateSessionDraft(auth, saved || session, agentMessage.trim())
      onSessionChange(data.session)
      setAgentMessage("")
      setOperation("success")
      setMessage("Draft regenerated.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not regenerate draft.")
    }
  }

  async function handleApprove() {
    if (!auth || !session) return
    setOperation("loading")
    setMessage("Approving content...")
    try {
      const saved = changedCount ? await handleSave() : session
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
              type="button"
              onClick={handleGenerate}
              disabled={operation === "loading" || !canGenerate}
              className="inline-flex items-center gap-2 rounded-md bg-ai px-3 py-2 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
            >
              {operation === "loading" ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              {draftReady ? "Regenerate draft" : "Generate draft"}
            </button>
            <button
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
          <p className={`mt-4 rounded-md px-3 py-2 text-sm ${operation === "error" ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"}`}>
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
            <section className="min-w-0 rounded-xl border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <h2 className="text-sm font-semibold">Draft fields</h2>
              </div>
              <div className="divide-y divide-border">
                {fields.map((field) => {
                  const value = drafts[field.id] ?? field.value
                  const multiline = value.length > 90 || value.includes("\n")
                  return (
                    <label key={field.id} className="block p-3">
                      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                        <span>
                          <span className="text-sm font-medium text-foreground">{field.label}</span>
                          <span className="ml-2 font-mono text-[11px] text-muted-foreground">{field.scope}:{field.key}</span>
                        </span>
                        {value !== field.value && (
                          <span className="rounded bg-ai/10 px-1.5 py-0.5 text-[10px] font-semibold text-ai">Edited</span>
                        )}
                      </div>
                      {multiline ? (
                        <textarea
                          value={value}
                          rows={4}
                          onChange={(event) => setDrafts((current) => ({ ...current, [field.id]: event.target.value }))}
                          className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                        />
                      ) : (
                        <input
                          value={value}
                          onChange={(event) => setDrafts((current) => ({ ...current, [field.id]: event.target.value }))}
                          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                        />
                      )}
                    </label>
                  )
                })}
              </div>
            </section>

            <aside className="min-w-0 space-y-4 lg:sticky lg:top-24 lg:self-start">
              <section className="rounded-xl border border-border bg-card p-4">
                <h2 className="text-sm font-semibold">Content agent</h2>
                <textarea
                  value={agentMessage}
                  onChange={(event) => setAgentMessage(event.target.value)}
                  rows={5}
                  placeholder="Describe what should change in the draft."
                  className="mt-3 w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
                />
                <button
                  type="button"
                  onClick={handleAgentRegenerate}
                  disabled={operation === "loading" || !agentMessage.trim()}
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-ai px-3 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
                >
                  {operation === "loading" ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  Regenerate content
                </button>
              </section>

              <section className="rounded-xl border border-border bg-card p-4">
                <button
                  type="button"
                  onClick={() => setTraceOpen((current) => !current)}
                  className="flex w-full items-center justify-between gap-2 text-left text-sm font-semibold"
                >
                  Prompt trace
                  <span className="text-xs text-muted-foreground">{traceOpen ? "Hide" : "Show"}</span>
                </button>
                {traceOpen && <div className="mt-3"><TracePanel trace={session.generation_trace || {}} /></div>}
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
