"use client"

import { FormEvent, useMemo, useState } from "react"
import { FilePlus2, FolderOpen, Loader2, RefreshCw, X } from "lucide-react"
import type { PostTypeOption, RecentSession } from "@/lib/content-sessions"
import { formatTimestamp } from "@/lib/utils"

export function SessionModal({
  postTypes,
  selectedPostType,
  recentSessions,
  loading,
  error,
  onCreate,
  onLoad,
  onRefresh,
  onClose,
}: {
  postTypes: PostTypeOption[]
  selectedPostType: string
  recentSessions: RecentSession[]
  loading: boolean
  error: string
  onCreate: (postTypeKey: string) => void
  onLoad: (sessionId: string) => void
  onRefresh: () => void
  onClose: () => void
}) {
  const [postType, setPostType] = useState(selectedPostType)

  const effectivePostType = postType || selectedPostType || postTypes[0]?.post_type_key || ""
  const selected = useMemo(
    () => postTypes.find((item) => item.post_type_key === effectivePostType),
    [effectivePostType, postTypes],
  )

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (effectivePostType) onCreate(effectivePostType)
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-topbar/60 px-4 backdrop-blur-sm">
      <div className="w-full max-w-3xl rounded-lg border border-border bg-card shadow-xl">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h1 className="text-base font-semibold text-foreground">Session</h1>
            <p className="text-xs text-muted-foreground">Create a workspace or load a recent session.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
            aria-label="Close sessions menu"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <form onSubmit={submit} className="rounded-lg border border-border bg-panel p-3">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
              <FilePlus2 className="size-4 text-gold" aria-hidden="true" />
              New session
            </h2>
            <label htmlFor="post-type" className="mb-1.5 block text-xs font-medium text-muted-foreground">
              Post type
            </label>
            <select
              id="post-type"
              value={effectivePostType}
              onChange={(event) => setPostType(event.target.value)}
              className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
            >
              {postTypes.map((item) => (
                <option key={item.post_type_key} value={item.post_type_key}>
                  {item.display_name_de || item.post_type_key}
                </option>
              ))}
            </select>
            <div className="mt-3 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
              {selected?.wp_category_name || "No category configured"}
            </div>
            <button
              type="submit"
              disabled={!effectivePostType || loading}
              className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-confirm px-3.5 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <FilePlus2 className="size-4" />}
              Create session
            </button>
          </form>

          <section className="rounded-lg border border-border bg-panel p-3">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <FolderOpen className="size-4 text-gold" aria-hidden="true" />
                Recent sessions
              </h2>
              <button
                type="button"
                onClick={onRefresh}
                disabled={loading}
                className="flex size-8 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted disabled:opacity-60"
                aria-label="Refresh sessions"
              >
                <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
              </button>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-md border border-border bg-card">
              {recentSessions.length ? (
                recentSessions.map((session) => (
                  <button
                    type="button"
                    key={session.session_id}
                    onClick={() => onLoad(session.session_id)}
                    className="block w-full border-b border-border px-3 py-2 text-left transition-colors last:border-b-0 hover:bg-muted"
                  >
                    <span className="block text-sm font-medium text-foreground">{session.session_id}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {formatTimestamp(session.created_at)} - {session.post_type_key || session.post_type || "-"} - {session.state || session.status || "-"}
                    </span>
                  </button>
                ))
              ) : (
                <div className="px-3 py-6 text-center text-sm text-muted-foreground">No recent V2 sessions found.</div>
              )}
            </div>
          </section>
        </div>

        {error && <p className="mx-4 mb-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      </div>
    </div>
  )
}
