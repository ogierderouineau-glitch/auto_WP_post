"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  CloudUpload,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  Pencil,
  RefreshCw,
} from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  startSessionPublish,
  waitForSessionJob,
  type ContentSession,
} from "@/lib/content-sessions"
import { statusMessageClass } from "@/lib/status-style"

type OperationState = "idle" | "loading" | "success" | "error"
type PublishStatus = "draft" | "private" | "publish"
const ACTIVE_JOB_STORAGE = "speech2post_active_job"

function resultValue(result: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = result[key]
    if (value != null && String(value).trim()) return String(value)
  }
  return ""
}

function payloadDiff(current: Record<string, unknown>, previous: Record<string, unknown>) {
  const groups = ["wordpress", "meta", "acf"] as const
  return groups.flatMap((group) => {
    const next = (current[group] || {}) as Record<string, unknown>
    const before = (previous[group] || {}) as Record<string, unknown>
    return Object.keys(next)
      .filter((key) => JSON.stringify(next[key]) !== JSON.stringify(before[key]))
      .map((key) => `${group}.${key}`)
  })
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-right text-sm font-medium text-foreground">{value}</span>
    </div>
  )
}

function JsonPanel({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold text-foreground">{title}</h2>
      {Object.keys(data || {}).length ? (
        <pre className="max-h-80 overflow-auto rounded-md border border-border bg-background p-3 text-xs leading-relaxed text-muted-foreground">
          {JSON.stringify(data, null, 2)}
        </pre>
      ) : (
        <p className="text-sm text-muted-foreground">No data yet.</p>
      )}
    </section>
  )
}

export function WordPressScreen({
  auth,
  session,
  onSessionChange,
  onBackToContent,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  onSessionChange: (session: ContentSession) => void
  onBackToContent: () => void
}) {
  const [postStatus, setPostStatus] = useState<PublishStatus>("draft")
  const [operation, setOperation] = useState<OperationState>("idle")
  const [message, setMessage] = useState("")

  const wordpressResult = session?.wordpress_result || {}
  const postId = resultValue(wordpressResult, "post_id", "id")
  const viewUrl = resultValue(wordpressResult, "view_url", "link")
  const editUrl = resultValue(wordpressResult, "edit_url")
  const sentPayload = session?.published_wordpress_payload || {}
  const currentPayload = session?.wordpress_payload || {}
  const changedFields = useMemo(
    () => payloadDiff(currentPayload, sentPayload),
    [currentPayload, sentPayload],
  )
  const approved = !!session?.approval.approved
  const canPublish = !!auth && !!session && approved && Object.keys(session.wordpress_payload || {}).length > 0
  const noChange = !!postId && changedFields.length === 0

  async function pollPublishJob(jobId: string, signal?: AbortSignal) {
    if (!auth) throw new Error("Authentication is required.")
    return waitForSessionJob(auth, jobId, {
      signal,
      onConnectionIssue: () => setMessage("Connection interrupted. Publishing continues; reconnecting..."),
      onConnectionRestored: () => setMessage("Connection restored. Publishing continues..."),
    })
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
    if (storedJob.operation !== "publish" || storedJob.sessionId !== session.session_id || !storedJob.jobId) return

    const controller = new AbortController()
    setOperation("loading")
    setMessage("Checking WordPress publication...")
    void pollPublishJob(storedJob.jobId, controller.signal)
      .then((nextSession) => {
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        onSessionChange(nextSession)
        setOperation("success")
        setMessage("WordPress post created.")
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return
        setOperation("error")
        setMessage(error instanceof Error ? error.message : "WordPress action failed.")
      })

    return () => controller.abort()
  }, [auth, session?.session_id])

  async function runPublish(options: { targetPostId?: number | null; forceCreateNew?: boolean; partialUpdate?: boolean }) {
    if (!auth || !session) return
    setOperation("loading")
    setMessage(options.partialUpdate ? "Updating WordPress post..." : "Creating WordPress post...")
    try {
      const sharedFields =
        options.forceCreateNew && postStatus
          ? {
              ...session.shared_fields,
              status: postStatus,
            }
          : {}
      const job = await startSessionPublish(auth, session, {
        ...options,
        sharedFields,
      })
      sessionStorage.setItem(
        ACTIVE_JOB_STORAGE,
        JSON.stringify({
          jobId: job.job_id,
          operation: "publish",
          sessionId: session.session_id,
          at: new Date().toISOString(),
        }),
      )
      const nextSession = await pollPublishJob(job.job_id)
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      onSessionChange(nextSession)
      setOperation("success")
      setMessage(options.partialUpdate ? "WordPress post updated." : "WordPress post created.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "WordPress action failed.")
    }
  }

  if (!session) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        Create or load a session before publishing to WordPress.
      </div>
    )
  }

  return (
    <div className="pb-24">
      <div className="mb-4">
        <h1 className="text-xl font-semibold tracking-tight text-foreground sm:text-2xl">Publish to WordPress</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Create or update the WordPress post using the approved V2 payload.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex flex-col gap-4">
          <section className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
              <CloudUpload className="size-4 text-gold" aria-hidden="true" />
              Publish destination
            </h2>

            <div className="divide-y divide-border rounded-md border border-border bg-panel px-3">
              <InfoRow
                label="Client website"
                value={
                  <span className="inline-flex items-center gap-1.5">
                    <Globe className="size-3.5 text-muted-foreground" aria-hidden="true" />
                    {auth?.userId || "-"}
                  </span>
                }
              />
              <InfoRow label="Post type" value={session.wordpress_post_type || session.post_type_key} />
              <InfoRow
                label="Content status"
                value={
                  approved ? (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-confirm/12 px-2 py-0.5 text-xs font-medium text-confirm">
                      <Check className="size-3" aria-hidden="true" />
                      Approved
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-warn/20 px-2 py-0.5 text-xs font-medium text-warn-foreground">
                      <AlertTriangle className="size-3" aria-hidden="true" />
                      Needs approval
                    </span>
                  )
                }
              />
              <InfoRow label="Session state" value={session.state} />
            </div>

            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="sm:w-44">
                <label htmlFor="s2p-wordpress-post-status" className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  New post status
                </label>
                <select
                  id="s2p-wordpress-post-status"
                  value={postStatus}
                  onChange={(event) => setPostStatus(event.target.value as PublishStatus)}
                  className="w-full rounded-md border border-input bg-card px-3 py-2.5 text-sm font-medium text-foreground outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="draft">Draft</option>
                  <option value="private">Private</option>
                  <option value="publish">Publish</option>
                </select>
              </div>

              <button
                id="s2p-wordpress-create-post"
                type="button"
                onClick={() => runPublish({ forceCreateNew: true })}
                disabled={operation === "loading" || !canPublish}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-confirm px-4 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {operation === "loading" ? <Loader2 className="size-4 animate-spin" /> : <CloudUpload className="size-4" />}
                Create post
              </button>
            </div>
          </section>

          <section className="rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Current WordPress target</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  V2 currently stores one WordPress result per session.
                </p>
              </div>
            </div>

            {message && (
              <div
                className={[
                  "mb-3 rounded-md px-3 py-2 text-sm",
                  statusMessageClass(operation, message),
                ].join(" ")}
              >
                {message}
              </div>
            )}

            {postId ? (
              <>
                {noChange ? (
                  <div className="mb-3 flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-sm font-medium text-muted-foreground">
                    <Check className="size-4 shrink-0" aria-hidden="true" />
                    No content fields have changed since the last successful publish.
                  </div>
                ) : (
                  <div className="mb-3 flex items-center gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm font-medium text-warn-foreground">
                    <RefreshCw className="size-4 shrink-0" aria-hidden="true" />
                    {changedFields.length} changed WordPress payload field(s) detected.
                  </div>
                )}

                <div className="grid grid-cols-1 gap-x-6 rounded-md border border-border bg-panel px-3 sm:grid-cols-2">
                  <InfoRow label="WordPress post ID" value={`#${postId}`} />
                  <InfoRow label="Returned status" value={resultValue(wordpressResult, "status") || "-"} />
                  <InfoRow label="Idempotency key" value={resultValue(wordpressResult, "idempotency_key") || "-"} />
                  <InfoRow label="Changed fields" value={changedFields.length} />
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {viewUrl && (
                    <a
                      href={viewUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
                    >
                      <ExternalLink className="size-4" aria-hidden="true" />
                      View post
                    </a>
                  )}
                  {editUrl && (
                    <a
                      href={editUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
                    >
                      <Pencil className="size-4" aria-hidden="true" />
                      Edit post
                    </a>
                  )}
                  <button
                    id="s2p-wordpress-update-post"
                    type="button"
                    onClick={() => runPublish({ targetPostId: Number(postId), partialUpdate: true })}
                    disabled={operation === "loading" || !canPublish || noChange}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-ai px-3.5 py-2 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {operation === "loading" ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                    Update post
                  </button>
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-dashed border-border bg-card/50 p-8 text-center">
                <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-muted">
                  <CloudUpload className="size-5 text-muted-foreground" aria-hidden="true" />
                </div>
                <p className="text-sm font-medium text-foreground">No WordPress post created yet</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Create a post after content has been approved.
                </p>
              </div>
            )}
          </section>

          {!!changedFields.length && (
            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-semibold text-foreground">Changed payload fields</h2>
              <div className="flex flex-wrap gap-2">
                {changedFields.map((field) => (
                  <span key={field} className="rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                    {field}
                  </span>
                ))}
              </div>
            </section>
          )}

          <JsonPanel title="Sent WordPress payload" data={sentPayload} />
        </div>

        <aside className="flex flex-col gap-4">
          <section className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-2 text-sm font-semibold text-foreground">Publishing checklist</h2>
            <ul className="flex flex-col gap-2 text-sm">
              {[
                { label: "Content approved", ok: approved },
                { label: "WordPress payload generated", ok: Object.keys(session.wordpress_payload || {}).length > 0 },
                { label: "Featured image assigned", ok: session.image_metadata.some((row) => row.image_usage === "featured") || !session.image_refs.length },
              ].map((item) => (
                <li key={item.label} className="flex items-center gap-2 text-muted-foreground">
                  <span
                    className={[
                      "flex size-4 items-center justify-center rounded-full",
                      item.ok ? "bg-confirm text-confirm-foreground" : "bg-muted text-muted-foreground",
                    ].join(" ")}
                  >
                    {item.ok && <Check className="size-2.5" aria-hidden="true" />}
                  </span>
                  {item.label}
                </li>
              ))}
            </ul>
          </section>

          <JsonPanel title="Current WordPress payload" data={currentPayload} />

          <section className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold text-foreground">
              <FileText className="size-4 text-muted-foreground" />
              About this version
            </h2>
            <p className="text-sm leading-relaxed text-muted-foreground">
              This screen uses the existing V2 publish job. Multiple WordPress targets per session are not represented
              yet because the backend stores one `wordpress_result`.
            </p>
          </section>
        </aside>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-3 sm:px-4">
          <button
            id="s2p-wordpress-back-to-content"
            type="button"
            onClick={onBackToContent}
            className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
            Back to Content
          </button>

          <div className="ml-auto flex items-center gap-4">
            <span className="hidden items-center gap-1.5 text-sm text-muted-foreground sm:inline-flex">
              <FileText className="size-4" aria-hidden="true" />
              {postId ? `Post #${postId}` : "No post yet"}
            </span>
            <span
              className={[
                "inline-flex items-center gap-1.5 text-sm font-medium",
                postId && noChange ? "text-confirm" : postId ? "text-warn-foreground" : "text-muted-foreground",
              ].join(" ")}
            >
              {postId && noChange ? <Check className="size-4" /> : <RefreshCw className="size-4" />}
              {postId ? (noChange ? "Synced" : "Pending changes") : "Ready"}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
