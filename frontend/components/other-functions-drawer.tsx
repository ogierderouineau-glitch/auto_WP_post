"use client"

import { useEffect, useRef, useState } from "react"
import {
  Check,
  ChevronDown,
  Database,
  Download,
  FileClock,
  FolderOpen,
  Info,
  KeyRound,
  Loader2,
  Upload,
  RefreshCw,
  Server,
  Settings2,
  Trash2,
  X,
} from "lucide-react"
import type { AuthResult } from "@/components/auth-modal"
import {
  loadSessionJob,
  saveSessionGenerationSettings,
  type ContentSession,
  type RecentSession,
  type WorkbookStatus,
} from "@/lib/content-sessions"
import { formatTimestamp } from "@/lib/utils"

export type OperationLogEntry = {
  id: string
  label: string
  detail: string
  at: string
  status: "running" | "success" | "error" | "info"
}

type StoredJob = {
  jobId: string
  operation: string
  sessionId: string
  at: string
}

const ACTIVE_JOB_STORAGE = "speech2post_active_job"
const SLOW_OPERATION_THRESHOLD_SECONDS = 45

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="max-w-[70%] text-right text-sm font-medium text-foreground">{value}</span>
    </div>
  )
}

function Section({
  title,
  icon,
  children,
}: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  const sectionId = title.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
  return (
    <details id={`s2p-other-section-${sectionId}`} className="group rounded-lg border border-border bg-card">
      <summary
        id={`s2p-other-section-toggle-${sectionId}`}
        className="flex cursor-pointer list-none items-center gap-2 p-4 text-sm font-semibold text-foreground [&::-webkit-details-marker]:hidden"
      >
        {icon}
        <span>{title}</span>
        <ChevronDown className="ml-auto size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <div className="px-4 pb-4">{children}</div>
    </details>
  )
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

function formatDuration(seconds: number) {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

function formatOperation(value: string) {
  return value.replaceAll("_", " ").replace(/^\w/, (character) => character.toUpperCase())
}

function numberValue(value: unknown) {
  const number = typeof value === "number" ? value : Number(value)
  return Number.isFinite(number) ? number : 0
}

function formatInteger(value: unknown) {
  return new Intl.NumberFormat("en-US").format(Math.round(numberValue(value)))
}

function formatUsd(value: unknown) {
  const amount = numberValue(value)
  if (amount > 0 && amount < 0.01) return `$${amount.toFixed(4)}`
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

function formatServiceName(value: string) {
  return value.replace(/^openai_/, "").replaceAll("_", " ")
}

function UsageSummary({ usage }: { usage: Record<string, unknown> }) {
  const services = usage.services && typeof usage.services === "object" ? usage.services : {}
  const serviceRows = Object.entries(services as Record<string, Record<string, unknown>>)
  const unknownCalls = numberValue(usage.unknown_usage_calls)

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border border-border bg-panel px-3 py-2">
          <span className="block text-xs text-muted-foreground">Estimated cost</span>
          <span className="mt-1 block text-lg font-semibold text-foreground">
            {formatUsd(usage.estimated_cost_usd)}
          </span>
        </div>
        <div className="rounded-md border border-border bg-panel px-3 py-2">
          <span className="block text-xs text-muted-foreground">AI calls</span>
          <span className="mt-1 block text-lg font-semibold text-foreground">
            {formatInteger(usage.call_count)}
          </span>
        </div>
        <div className="rounded-md border border-border bg-panel px-3 py-2">
          <span className="block text-xs text-muted-foreground">Input tokens</span>
          <span className="mt-1 block text-sm font-semibold text-foreground">
            {formatInteger(usage.prompt_tokens)}
          </span>
        </div>
        <div className="rounded-md border border-border bg-panel px-3 py-2">
          <span className="block text-xs text-muted-foreground">Output tokens</span>
          <span className="mt-1 block text-sm font-semibold text-foreground">
            {formatInteger(usage.completion_tokens)}
          </span>
        </div>
      </div>

      {unknownCalls > 0 ? (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {formatInteger(unknownCalls)} call{unknownCalls === 1 ? "" : "s"} did not include a known USD estimate.
        </p>
      ) : null}

      {serviceRows.length ? (
        <div className="overflow-hidden rounded-md border border-border bg-panel">
          {serviceRows.map(([service, stats]) => (
            <div key={service} className="border-b border-border px-3 py-2 last:border-b-0">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium capitalize text-foreground">{formatServiceName(service)}</span>
                <span className="text-sm font-semibold text-foreground">{formatUsd(stats.estimated_cost_usd)}</span>
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatInteger(stats.call_count)} calls · {formatInteger(stats.total_tokens)} tokens
              </p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

type ModelCallDetail = {
  call_name?: string
  model?: string
  duration_seconds?: number
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  estimated_cost_usd?: number | null
}

function OperationModelCalls({ operationId, details }: { operationId: string; details: Record<string, unknown> }) {
  const calls = Array.isArray(details.model_calls) ? details.model_calls as ModelCallDetail[] : []
  if (!calls.length) return null

  return (
    <details id={`s2p-operation-calls-${operationId}`} className="mt-2 rounded-md border border-border bg-background px-2.5 py-2">
      <summary id={`s2p-operation-calls-toggle-${operationId}`} className="cursor-pointer text-xs font-semibold text-foreground">
        Model calls ({calls.length})
      </summary>
      <div className="mt-2 space-y-2">
        {calls.map((call, index) => (
          <div key={`${call.call_name || "call"}-${index}`} className="rounded border border-border bg-panel px-2.5 py-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-1">
              <span className="font-medium text-foreground">{formatOperation(call.call_name || `Call ${index + 1}`)}</span>
              <span className="text-muted-foreground">{call.duration_seconds != null ? formatDuration(call.duration_seconds) : "Duration unavailable"}</span>
            </div>
            <p className="mt-1 text-muted-foreground">
              {call.model || "Unknown model"}
              {call.total_tokens ? ` · ${formatInteger(call.total_tokens)} tokens` : ""}
              {call.estimated_cost_usd != null ? ` · ${formatUsd(call.estimated_cost_usd)}` : ""}
            </p>
            <p className="mt-0.5 text-muted-foreground">
              {formatInteger(call.prompt_tokens)} input · {formatInteger(call.completion_tokens)} output
            </p>
          </div>
        ))}
      </div>
    </details>
  )
}

export function OtherFunctionsDrawer({
  open,
  auth,
  workbook,
  session,
  recentSessions,
  loading,
  statusText,
  error,
  operationLog,
  onClose,
  onRefreshRecent,
  onReloadSession,
  onOpenSessionMenu,
  onLoadSession,
  onDeleteSession,
  onSessionChange,
  onUploadWorkbook,
  onDownloadWorkbook,
}: {
  open: boolean
  auth: AuthResult | null
  workbook: WorkbookStatus | null
  session: ContentSession | null
  recentSessions: RecentSession[]
  loading: boolean
  statusText: string
  error: string
  operationLog: OperationLogEntry[]
  onClose: () => void
  onRefreshRecent: () => void
  onReloadSession: () => void
  onOpenSessionMenu: () => void
  onLoadSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
  onSessionChange: (session: ContentSession) => void
  onUploadWorkbook: (file: File) => Promise<void>
  onDownloadWorkbook: () => Promise<void>
}) {
  const [storedJob, setStoredJob] = useState<StoredJob | null>(null)
  const [jobRecovery, setJobRecovery] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [jobRecoveryMessage, setJobRecoveryMessage] = useState("")
  const [workbookOperation, setWorkbookOperation] = useState<"idle" | "uploading" | "downloading">("idle")
  const [workbookMessage, setWorkbookMessage] = useState("")
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [settingsMessage, setSettingsMessage] = useState("")
  const settingsSavingRef = useRef(false)
  const latestSessionRef = useRef(session)

  useEffect(() => {
    latestSessionRef.current = session
  }, [session])

  const generationSettings = workbook?.generation_settings
  const selectedLanguageModel = session?.language_model || generationSettings?.default_language_model || "gpt-5.6"
  const configuredReasoningEffort = session?.reasoning_effort || generationSettings?.default_reasoning_effort || "low"
  const selectedReasoningEffort = selectedLanguageModel === "gpt-5-mini" && configuredReasoningEffort === "none"
    ? "minimal"
    : configuredReasoningEffort
  const selectedGenerationMode = session?.generation_mode || "batched"
  const languageModels = Array.from(new Set([selectedLanguageModel, ...(generationSettings?.language_models || [])]))
  const reasoningEfforts = Array.from(new Set([selectedReasoningEffort, ...(generationSettings?.reasoning_efforts || [])]))
    .filter((effort) => selectedLanguageModel !== "gpt-5-mini" || effort !== "none")

  async function saveGenerationSettings(
    languageModel: string,
    reasoningEffort: string,
    generationMode: "batched" | "single" = selectedGenerationMode,
  ) {
    const currentSession = latestSessionRef.current
    if (!auth || !currentSession || settingsSavingRef.current) return
    settingsSavingRef.current = true
    setSettingsSaving(true)
    setSettingsMessage("")
    try {
      const response = await saveSessionGenerationSettings(auth, currentSession, languageModel, reasoningEffort, generationMode)
      latestSessionRef.current = response.session
      onSessionChange(response.session)
      setSettingsMessage("Generation settings saved for this session.")
    } catch (error) {
      setSettingsMessage(error instanceof Error ? error.message : "Could not save generation settings.")
    } finally {
      settingsSavingRef.current = false
      setSettingsSaving(false)
    }
  }

  async function runWorkbookAction(action: "uploading" | "downloading", callback: () => Promise<void>) {
    setWorkbookOperation(action)
    setWorkbookMessage("")
    try {
      await callback()
      setWorkbookMessage(action === "uploading" ? "Database Datei aktualisiert." : "Database Datei heruntergeladen.")
    } catch (error) {
      setWorkbookMessage(error instanceof Error ? error.message : "Workbook operation failed.")
    } finally {
      setWorkbookOperation("idle")
    }
  }

  useEffect(() => {
    if (!open) return
    try {
      const raw = sessionStorage.getItem(ACTIVE_JOB_STORAGE)
      setStoredJob(raw ? (JSON.parse(raw) as StoredJob) : null)
    } catch {
      setStoredJob(null)
    }
  }, [open])

  async function recoverStoredJob() {
    if (!auth || !storedJob) return
    setJobRecovery("loading")
    setJobRecoveryMessage("Checking backend job status...")
    try {
      const job = await loadSessionJob(auth, storedJob.jobId)
      if (job.status === "complete" && job.session) {
        onSessionChange(job.session)
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        setStoredJob(null)
        setJobRecovery("success")
        setJobRecoveryMessage("Recovered completed job and refreshed the session.")
        return
      }
      if (job.status === "failed" || job.status === "not_found") {
        setJobRecovery("error")
        setJobRecoveryMessage(job.error || `Job status: ${job.status}`)
        return
      }
      setJobRecovery("idle")
      setJobRecoveryMessage(`Job is still ${job.status}. Try again shortly.`)
    } catch (error) {
      setJobRecovery("error")
      setJobRecoveryMessage(error instanceof Error ? error.message : "Could not recover job.")
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 bg-topbar/50 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="ml-auto flex h-full w-full max-w-xl flex-col border-l border-border bg-background shadow-xl">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h1 className="text-base font-semibold text-foreground">Other functions</h1>
            <p className="text-xs text-muted-foreground">Workspace status, recovery, config and session tools.</p>
          </div>
          <button
            id="s2p-other-close"
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
            aria-label="Close other functions"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          <Section title="Generation settings" icon={<Settings2 className="size-4 text-gold" aria-hidden="true" />}>
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="space-y-1.5 text-sm font-medium text-foreground">
                <span>Language model</span>
                <select
                  id="s2p-other-language-model"
                  value={selectedLanguageModel}
                  disabled={!session || loading || settingsSaving}
                  onChange={(event) => {
                    const model = event.target.value
                    const effort = model === "gpt-5-mini" && selectedReasoningEffort === "none"
                      ? "minimal"
                      : selectedReasoningEffort
                    void saveGenerationSettings(model, effort)
                  }}
                  className="w-full rounded-md border border-border bg-panel px-3 py-2 text-sm text-foreground disabled:opacity-60"
                >
                  {languageModels.map((model) => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1.5 text-sm font-medium text-foreground">
                <span>Reasoning effort</span>
                <select
                  id="s2p-other-reasoning-effort"
                  value={selectedReasoningEffort}
                  disabled={!session || loading || settingsSaving}
                  onChange={(event) => void saveGenerationSettings(selectedLanguageModel, event.target.value)}
                  className="w-full rounded-md border border-border bg-panel px-3 py-2 text-sm capitalize text-foreground disabled:opacity-60"
                >
                  {reasoningEfforts.map((effort) => (
                    <option key={effort} value={effort}>{effort}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1.5 text-sm font-medium text-foreground">
                <span>Generation calls</span>
                <select
                  id="s2p-other-generation-mode"
                  value={selectedGenerationMode}
                  disabled={!session || loading || settingsSaving}
                  onChange={(event) => void saveGenerationSettings(
                    selectedLanguageModel,
                    selectedReasoningEffort,
                    event.target.value as "batched" | "single",
                  )}
                  className="w-full rounded-md border border-border bg-panel px-3 py-2 text-sm text-foreground disabled:opacity-60"
                >
                  <option value="batched">Batched (safer)</option>
                  <option value="single">Single call (test)</option>
                </select>
              </label>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Controls analysis and full draft generation for this session. Single call avoids repeated context but sends a larger schema and response, which may be more vulnerable to provider timeouts.
            </p>
            {settingsMessage ? <p className="mt-2 text-xs text-muted-foreground">{settingsMessage}</p> : null}
          </Section>

          <Section title="Usage" icon={<FileClock className="size-4 text-gold" aria-hidden="true" />}>
            {session?.ai_usage && Object.keys(session.ai_usage).length ? (
              <UsageSummary usage={session.ai_usage} />
            ) : (
              <p className="text-sm text-muted-foreground">No AI usage recorded for this session yet.</p>
            )}
          </Section>

          <Section title="Operations log" icon={<FileClock className="size-4 text-gold" aria-hidden="true" />}>
            {session?.operation_log?.length ? (
              <ol className="mb-3 space-y-2">
                {session.operation_log.map((entry) => (
                  <li key={entry.operation_id} className="rounded-md border border-border bg-panel px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                        {formatOperation(entry.operation)}
                        {entry.duration_seconds >= SLOW_OPERATION_THRESHOLD_SECONDS ? (
                          <span className="rounded bg-warn/20 px-1.5 py-0.5 text-[10px] font-semibold text-warn-foreground">
                            &gt;45s
                          </span>
                        ) : null}
                      </span>
                      <span className="text-xs text-muted-foreground">{formatTime(entry.finished_at)}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {entry.status} · {formatDuration(entry.duration_seconds)}
                      {entry.total_tokens ? ` · ${formatInteger(entry.total_tokens)} tokens` : ""}
                      {entry.estimated_cost_usd != null ? ` · ${formatUsd(entry.estimated_cost_usd)}` : ""}
                      {entry.details?.model ? ` · ${String(entry.details.model)}` : ""}
                      {entry.details?.reasoning_effort ? ` · reasoning ${String(entry.details.reasoning_effort)}` : ""}
                      {entry.details?.generation_mode ? ` · ${String(entry.details.generation_mode)}` : ""}
                      {entry.details?.rating ? ` · ${String(entry.details.rating).replace("_", " ")}` : ""}
                      {typeof entry.details?.finding_count === "number" ? ` · ${entry.details.finding_count} finding(s)` : ""}
                    </p>
                    <OperationModelCalls operationId={entry.operation_id} details={entry.details || {}} />
                    {entry.error ? <p className="mt-1 text-xs text-destructive">{entry.error}</p> : null}
                  </li>
                ))}
              </ol>
            ) : null}
            {operationLog.length ? (
              <ol className="space-y-2">
                {operationLog.map((entry) => (
                  <li key={entry.id} className="rounded-md border border-border bg-panel px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-foreground">{entry.label}</span>
                      <span className="text-xs text-muted-foreground">{formatTime(entry.at)}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{entry.detail}</p>
                  </li>
                ))}
              </ol>
            ) : (
              !session?.operation_log?.length ? <p className="text-sm text-muted-foreground">No session operations recorded yet.</p> : null
            )}
          </Section>

          <Section title="Sessions archive" icon={<FolderOpen className="size-4 text-gold" aria-hidden="true" />}>
            <div className="mb-3 flex justify-end">
              <button
                id="s2p-other-refresh-archive"
                type="button"
                onClick={onRefreshRecent}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted disabled:opacity-60"
              >
                <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
                Refresh
              </button>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-panel">
              {recentSessions.length ? (
                recentSessions.map((item) => {
                  const isActive = item.session_id === session?.session_id
                  return (
                    <div
                      key={item.session_id}
                      className={`flex border-b border-border last:border-b-0 ${isActive ? "bg-gold/15 ring-1 ring-inset ring-gold/50" : "hover:bg-muted"}`}
                    >
                    <button
                      id={`s2p-other-load-session-${item.session_id}`}
                      type="button"
                      onClick={() => onLoadSession(item.session_id)}
                      disabled={loading}
                      aria-current={isActive ? "true" : undefined}
                      className="min-w-0 flex-1 px-3 py-2 text-left disabled:opacity-60"
                    >
                      <span className="block truncate font-mono text-xs text-foreground">{item.session_id}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {formatTimestamp(item.created_at)} - {item.post_type_key || item.post_type || "-"} - {item.state || item.status || "-"}
                      </span>
                    </button>
                    <button
                      id={`s2p-other-delete-session-${item.session_id}`}
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Permanently delete session ${item.session_id} and its files from GCS?`)) {
                          onDeleteSession(item.session_id)
                        }
                      }}
                      disabled={loading}
                      className="m-2 flex size-8 shrink-0 items-center justify-center rounded-md text-destructive hover:bg-destructive/10 disabled:opacity-60"
                      aria-label={`Delete session ${item.session_id}`}
                      title="Delete session from GCS"
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                    </button>
                    </div>
                  )
                })
              ) : (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">No recent V2 sessions found.</p>
              )}
            </div>
          </Section>

          <Section title="Workbook config" icon={<Database className="size-4 text-gold" aria-hidden="true" />}>
            <div className="divide-y divide-border rounded-md border border-border bg-panel px-3">
              <InfoRow label="File" value={workbook?.filename || "-"} />
              <InfoRow label="Storage" value={workbook?.storage_mode || "-"} />
              <InfoRow label="Hash" value={workbook?.sha256 ? workbook.sha256.slice(0, 12) : "-"} />
              <InfoRow label="Post types" value={workbook?.post_types.length ?? 0} />
              <InfoRow label="Fact fields" value={workbook?.fact_schema.length ?? 0} />
            </div>
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-center text-sm font-semibold text-foreground hover:bg-muted has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60">
                {workbookOperation === "uploading" ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
                Database Datei aktualisieren
                <input
                  id="s2p-other-workbook-upload"
                  type="file"
                  accept=".xlsm,.xlsx"
                  className="sr-only"
                  disabled={!auth || workbookOperation !== "idle"}
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    event.target.value = ""
                    if (file) void runWorkbookAction("uploading", () => onUploadWorkbook(file))
                  }}
                />
              </label>
              <button
                id="s2p-other-workbook-download"
                type="button"
                disabled={!auth || workbookOperation !== "idle"}
                onClick={() => void runWorkbookAction("downloading", onDownloadWorkbook)}
                className="inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
              >
                {workbookOperation === "downloading" ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
                Aktuelle Database Datei herunterladen
              </button>
            </div>
            {workbookMessage && <p className="mt-2 text-xs text-muted-foreground">{workbookMessage}</p>}
          </Section>

          <Section title="Credentials" icon={<KeyRound className="size-4 text-gold" aria-hidden="true" />}>
            <div className="divide-y divide-border rounded-md border border-border bg-panel px-3">
              <InfoRow label="Client" value={auth?.client.client_id || "-"} />
              <InfoRow label="User ID" value={auth?.userId || "-"} />
              <InfoRow label="Access key" value={auth ? "Stored in sessionStorage for this browser tab" : "Not connected"} />
            </div>
          </Section>

          <Section title="Current session" icon={<Info className="size-4 text-gold" aria-hidden="true" />}>
            {session ? (
              <div className="divide-y divide-border rounded-md border border-border bg-panel px-3">
                <InfoRow label="Session ID" value={<span className="font-mono text-xs">{session.session_id}</span>} />
                <InfoRow label="Post type" value={session.post_type_key} />
                <InfoRow label="Images" value={session.image_refs.length} />
                <InfoRow label="Audio" value={session.audio_refs.length} />
                <InfoRow label="Confirmed facts" value={Object.keys(session.confirmed_facts || {}).length} />
                <InfoRow label="Generated fields" value={Object.keys(session.shared_fields || {}).length + Object.keys(session.acf_source_fields || {}).length} />
                <InfoRow label="WordPress post" value={session.wordpress_result?.post_id ? `#${session.wordpress_result.post_id}` : "-"} />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No active session.</p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                id="s2p-other-reload-session"
                type="button"
                onClick={onReloadSession}
                disabled={!session || loading}
                className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted disabled:opacity-60"
              >
                <RefreshCw className="size-4" />
                Reload session
              </button>
              <button
                id="s2p-other-open-session-menu"
                type="button"
                onClick={onOpenSessionMenu}
                className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted"
              >
                <FolderOpen className="size-4" />
                Session menu
              </button>
            </div>
          </Section>

          <Section title="Global status" icon={<Server className="size-4 text-gold" aria-hidden="true" />}>
            <div className="divide-y divide-border rounded-md border border-border bg-panel px-3">
              <InfoRow
                label="Frontend"
                value={
                  <span className="inline-flex items-center gap-1.5">
                    {loading ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5 text-confirm" />}
                    {loading ? "Working" : statusText}
                  </span>
                }
              />
              <InfoRow label="Backend session" value={session ? `v${session.version} · ${session.state}` : "No session"} />
              <InfoRow label="Error" value={error || "None"} />
            </div>
          </Section>

          <Section title="Recovery note" icon={<Info className="size-4 text-gold" aria-hidden="true" />}>
            {storedJob && (
              <div className="mb-3 rounded-md border border-border bg-panel p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-foreground">Recover last {storedJob.operation} job</p>
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">{storedJob.jobId}</p>
                  </div>
                  <button
                    id="s2p-other-recover-job"
                    type="button"
                    onClick={() => void recoverStoredJob()}
                    disabled={jobRecovery === "loading"}
                    className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground hover:bg-muted disabled:opacity-60"
                  >
                    {jobRecovery === "loading" ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                    Recover
                  </button>
                </div>
                {jobRecoveryMessage && (
                  <p className={`mt-2 text-xs ${jobRecovery === "error" ? "text-destructive" : "text-muted-foreground"}`}>
                    {jobRecoveryMessage}
                  </p>
                )}
              </div>
            )}
            <p className="text-sm leading-relaxed text-muted-foreground">
              Generation and publish jobs are currently stored in FastAPI process memory. Polling can recover while the
              same server process is alive, but a backend restart loses job records. Durable recovery needs persistent
              job storage in a later backend phase.
            </p>
          </Section>
        </div>
      </div>
    </div>
  )
}
