"use client"

import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Info,
  Loader2,
  Plus,
  Search,
  Star,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react"
import { ActionHint } from "@/components/action-hint"
import { useActionWarning } from "@/components/action-warning"
import type { ApiClientOptions } from "@/lib/api"
import {
  hasExtractedFacts,
  saveKeywordSelection,
  startKeywordProposal,
  waitForSessionJob,
  type ContentSession,
  type KeywordRow,
  type KeywordStatus,
} from "@/lib/content-sessions"
import { statusMessageClass } from "@/lib/status-style"

const ACTIVE_JOB_STORAGE = "speech2post_keywords_job"
const MAX_SELECTED = 12
const STAGES = ["Scanning WordPress", "Reading Search Console", "Analysing keywords"]

const STATUS_COPY: Record<KeywordStatus, { label: string; hint: string; className: string }> = {
  free: {
    label: "Free",
    hint: "No scanned page uses this as its focus keyphrase.",
    className: "bg-confirm/15 text-confirm",
  },
  focus_elsewhere: {
    label: "Taken",
    hint: "Another page already uses this as its focus keyphrase. Using it again risks competing with that page.",
    className: "bg-destructive/10 text-destructive",
  },
  mentioned_elsewhere: {
    label: "Mentioned",
    hint: "Another page mentions this term but does not use it as its focus keyphrase.",
    className: "bg-warn/30 text-warn-foreground",
  },
}

type Filter = "all" | "free" | "taken"
type Sort = "proposed" | "clicks"

const sameKeyword = (left: string, right: string) =>
  left.trim().toLowerCase() === right.trim().toLowerCase()

function pagePath(url: string) {
  try {
    return new URL(url).pathname
  } catch {
    return url
  }
}

function SearchNumbers({ row }: { row: KeywordRow }) {
  if (row.clicks == null && row.impressions == null) {
    return (
      <span
        className="text-xs text-muted-foreground"
        title="No Search Console measurement for this term. It can still be used."
      >
        No data
      </span>
    )
  }
  const delta = row.clicks_delta
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 text-xs" title={row.month ? `Month: ${row.month}` : undefined}>
      <span><strong className="text-sm">{row.clicks ?? 0}</strong> clicks</span>
      <span className="text-muted-foreground">{row.impressions ?? 0} views</span>
      {delta != null && delta !== 0 && (
        <span className={`inline-flex items-center gap-0.5 font-medium ${delta > 0 ? "text-confirm" : "text-destructive"}`} title="Change in clicks versus the previous month">
          {delta > 0 ? <TrendingUp className="size-3" aria-hidden="true" /> : <TrendingDown className="size-3" aria-hidden="true" />}
          {delta > 0 ? `+${delta}` : delta}
        </span>
      )}
    </span>
  )
}

export function KeywordsScreen({
  auth,
  session,
  onSessionChange,
  onBackToFacts,
  onContinueToContent,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  onSessionChange: (session: ContentSession) => void
  onBackToFacts: () => void
  onContinueToContent: () => void
}) {
  const { confirm, warningDialog } = useActionWarning()
  const sessionRef = useRef(session)
  const [draft, setDraft] = useState<string[] | null>(null) // unsaved selection; null = nothing pending
  const [operation, setOperation] = useState<"idle" | "loading" | "error">("idle")
  const [stage, setStage] = useState("")
  const [message, setMessage] = useState("")
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle")
  const [filter, setFilter] = useState<Filter>("all")
  const [sort, setSort] = useState<Sort>("proposed")
  const [openRelated, setOpenRelated] = useState<string | null>(null)
  const [customKeyword, setCustomKeyword] = useState("")

  useEffect(() => {
    sessionRef.current = session
  }, [session])

  const rows = useMemo(() => session?.keyword_proposal?.rows ?? [], [session?.keyword_proposal?.rows])
  const selected = draft ?? session?.selected_keywords ?? []
  const hasProposal = rows.length > 0
  const factsReady = hasExtractedFacts(session)
  const running = operation === "loading"
  const disabledReason = !factsReady
    ? "Extract facts first. Keywords are proposed from your facts."
    : draft !== null
      ? "Saving your selection..."
      : ""

  const counts = useMemo(() => ({
    all: rows.length,
    free: rows.filter((row) => row.status === "free").length,
    taken: rows.filter((row) => row.status !== "free").length,
  }), [rows])

  const visibleRows = useMemo(() => {
    const filtered = rows.filter((row) =>
      filter === "all" ? true : filter === "free" ? row.status === "free" : row.status !== "free")
    return sort === "clicks"
      ? [...filtered].sort((a, b) => (b.clicks ?? -1) - (a.clicks ?? -1) || (b.impressions ?? -1) - (a.impressions ?? -1))
      : filtered
  }, [rows, filter, sort])

  // Autosave the selection shortly after the last change.
  useEffect(() => {
    if (draft === null || !auth) return
    const timer = window.setTimeout(async () => {
      const current = sessionRef.current
      if (!current) return
      setSaveState("saving")
      try {
        const data = await saveKeywordSelection(auth, current, draft)
        sessionRef.current = data.session
        onSessionChange(data.session)
        setDraft((pending) => (pending === draft ? null : pending))
        setSaveState("saved")
      } catch (error) {
        setSaveState("error")
        setOperation("error")
        setMessage(error instanceof Error ? error.message : "Could not save the keyword selection.")
      }
    }, 600)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, auth])

  // Resume waiting for a proposal job that was running when the page was reloaded.
  useEffect(() => {
    if (!auth || !session) return
    let stored: { jobId?: string; sessionId?: string }
    try {
      stored = JSON.parse(sessionStorage.getItem(ACTIVE_JOB_STORAGE) || "null") ?? {}
    } catch {
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      return
    }
    if (!stored.jobId || stored.sessionId !== session.session_id) return
    const controller = new AbortController()
    setOperation("loading")
    void waitForSessionJob(auth, stored.jobId, { signal: controller.signal, onStage: setStage })
      .then((next) => {
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        sessionRef.current = next
        onSessionChange(next)
        setOperation("idle")
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return
        sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
        setOperation("error")
        setMessage(error instanceof Error ? error.message : "The keyword search failed.")
      })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth, session?.session_id])

  async function runProposal() {
    const current = sessionRef.current
    if (!auth || !current || running || disabledReason) return
    if (hasProposal) {
      const proceed = await confirm({
        message: "Searching again replaces the current proposal. Your selection keeps only keywords that are proposed again.",
        confirmLabel: "Search again",
      })
      if (!proceed) return
    }
    setOperation("loading")
    setMessage("")
    setStage(STAGES[0])
    try {
      const job = await startKeywordProposal(auth, current)
      sessionStorage.setItem(ACTIVE_JOB_STORAGE, JSON.stringify({ jobId: job.job_id, sessionId: current.session_id }))
      const next = await waitForSessionJob(auth, job.job_id, {
        onStage: setStage,
        onConnectionIssue: () => setMessage("Connection interrupted. The search is still running; reconnecting..."),
        onConnectionRestored: () => setMessage(""),
      })
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      sessionRef.current = next
      onSessionChange(next)
      setOperation("idle")
    } catch (error) {
      sessionStorage.removeItem(ACTIVE_JOB_STORAGE)
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "The keyword search failed.")
    }
  }

  function toggle(keyword: string) {
    if (selected.some((item) => sameKeyword(item, keyword))) {
      setDraft(selected.filter((item) => !sameKeyword(item, keyword)))
      return
    }
    if (selected.length >= MAX_SELECTED) {
      setOperation("error")
      setMessage(`Select at most ${MAX_SELECTED} keywords.`)
      return
    }
    setOperation("idle")
    setMessage("")
    setDraft([...selected, keyword])
  }

  function makeFocus(keyword: string) {
    setDraft([keyword, ...selected.filter((item) => !sameKeyword(item, keyword))])
  }

  function addCustom() {
    const keyword = customKeyword.split(/\s+/).filter(Boolean).join(" ")
    if (!keyword) return
    if (keyword.length > 80) {
      setOperation("error")
      setMessage("A keyword can have at most 80 characters.")
      return
    }
    setCustomKeyword("")
    if (!selected.some((item) => sameKeyword(item, keyword))) toggle(keyword)
  }

  if (!session) {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">Create or load a session first.</div>
  }

  const proposal = session.keyword_proposal
  const stageIndex = Math.max(0, STAGES.indexOf(stage))

  return (
    <div className="pb-24">
      {warningDialog}
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Keywords</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Pick the keywords this post should rank for. This step is optional: with no selection the AI chooses keywords itself.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-label="Keyword proposal" className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card p-3">
            <ActionHint reason={disabledReason}>
              <button
                id="s2p-keywords-run"
                type="button"
                onClick={() => void runProposal()}
                disabled={running || !!disabledReason}
                className="inline-flex items-center gap-2 rounded-md bg-ai px-3.5 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
              >
                {running ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <Search className="size-4" aria-hidden="true" />}
                {running ? "Searching..." : hasProposal ? "Search again" : "Find keywords"}
              </button>
            </ActionHint>
            <p className="min-w-0 flex-1 text-xs text-muted-foreground">
              Compares your facts with the pages already on the site and, if connected, with what people search for in Google.
            </p>
          </div>

          {running && (
            <ol className="flex flex-wrap gap-2 rounded-lg border border-border bg-card p-3 text-sm" aria-label="Search progress">
              {STAGES.map((name, index) => (
                <li
                  key={name}
                  aria-current={index === stageIndex ? "step" : undefined}
                  className={`inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 ${index === stageIndex ? "bg-ai/10 font-medium text-ai" : index < stageIndex ? "text-confirm" : "text-muted-foreground"}`}
                >
                  {index < stageIndex ? <Check className="size-4" aria-hidden="true" /> : index === stageIndex ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <span className="size-4 rounded-full border border-border" aria-hidden="true" />}
                  {name}
                </li>
              ))}
            </ol>
          )}

          {message && <p role="status" className={`rounded-md px-3 py-2 text-sm ${statusMessageClass(operation, message)}`}>{message}</p>}

          {proposal && hasProposal && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
              <span>Scanned {proposal.scanned_pages ?? 0} pages</span>
              <span>{proposal.sources?.includes("search_console") ? "Search Console data included" : "No Search Console data"}</span>
              {proposal.scanned_at && <span>{new Date(proposal.scanned_at).toLocaleString()}</span>}
            </div>
          )}
          {proposal?.notes?.map((note) => (
            <p key={note} className="flex items-start gap-2 rounded-md bg-warn/20 px-3 py-2 text-xs text-warn-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              {note}
            </p>
          ))}

          {!hasProposal ? (
            <div className="rounded-lg border border-dashed border-border bg-card p-8 text-center text-sm text-muted-foreground">
              {running ? "Looking for keywords..." : factsReady ? "No proposal yet. Use Find keywords, or add your own keywords on the right." : "Extract facts first, then come back to find keywords."}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div role="group" aria-label="Filter keywords" className="inline-flex overflow-hidden rounded-md border border-border text-sm">
                  {(["all", "free", "taken"] as const).map((name) => (
                    <button
                      key={name}
                      type="button"
                      aria-pressed={filter === name}
                      onClick={() => setFilter(name)}
                      className={`px-3 py-1.5 capitalize transition-colors ${filter === name ? "bg-gold/20 font-semibold" : "bg-card hover:bg-muted"}`}
                    >
                      {name} ({counts[name]})
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  Sort
                  <select value={sort} onChange={(event) => setSort(event.target.value as Sort)} className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground">
                    <option value="proposed">Proposed order</option>
                    <option value="clicks">Most clicks</option>
                  </select>
                </label>
              </div>

              <div className="overflow-x-auto rounded-lg border border-border bg-card">
                <table className="w-full min-w-[720px] text-left text-sm">
                  <thead className="bg-panel text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th scope="col" className="w-10 px-3 py-2"><span className="sr-only">Select</span></th>
                      <th scope="col" className="px-3 py-2">Keyword</th>
                      <th scope="col" className="px-3 py-2">Alternatives</th>
                      <th scope="col" className="px-3 py-2">Status</th>
                      <th scope="col" className="px-3 py-2">Google search</th>
                      <th scope="col" className="px-3 py-2">Related pages</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row) => {
                      const index = selected.findIndex((item) => sameKeyword(item, row.keyword))
                      const checked = index >= 0
                      const status = STATUS_COPY[row.status]
                      const expanded = openRelated === row.keyword
                      return (
                        <Fragment key={row.keyword}>
                          <tr className={`border-t border-border align-top transition-colors ${checked ? "bg-gold/10" : "hover:bg-muted/50"}`}>
                            <td className="px-3 py-3">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggle(row.keyword)}
                                aria-label={`Use keyword ${row.keyword}`}
                                className="size-4 cursor-pointer accent-gold"
                              />
                            </td>
                            <td className="px-3 py-3">
                              <span className="flex items-center gap-1.5 font-medium">
                                {row.keyword}
                                {index === 0 && <span className="rounded bg-gold px-1.5 py-0.5 text-[10px] font-semibold uppercase text-gold-foreground">Focus</span>}
                              </span>
                              {row.rationale && <span className="mt-0.5 block max-w-xs text-xs text-muted-foreground">{row.rationale}</span>}
                            </td>
                            <td className="px-3 py-3">
                              <span className="flex flex-wrap gap-1">
                                {row.alternatives.map((alternative) => (
                                  <span key={alternative} className="rounded-full bg-muted px-2 py-0.5 text-xs">{alternative}</span>
                                ))}
                              </span>
                            </td>
                            <td className="px-3 py-3">
                              <span title={status.hint} className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${status.className}`}>{status.label}</span>
                            </td>
                            <td className="px-3 py-3"><SearchNumbers row={row} /></td>
                            <td className="px-3 py-3">
                              {row.related_urls.length ? (
                                <button
                                  type="button"
                                  aria-expanded={expanded}
                                  onClick={() => setOpenRelated(expanded ? null : row.keyword)}
                                  className="inline-flex items-center gap-1 text-xs font-medium text-ai hover:underline"
                                >
                                  <ChevronRight className={`size-3.5 transition-transform ${expanded ? "rotate-90" : ""}`} aria-hidden="true" />
                                  {row.related_urls.length} {row.related_urls.length === 1 ? "page" : "pages"}
                                </button>
                              ) : <span className="text-xs text-muted-foreground">None</span>}
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="bg-panel">
                              <td />
                              <td colSpan={5} className="px-3 py-2">
                                <ul className="space-y-1 text-xs">
                                  {row.related_urls.map((url) => (
                                    <li key={url}>
                                      <a href={url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-ai hover:underline">
                                        {pagePath(url)}<ArrowUpRight className="size-3" aria-hidden="true" />
                                      </a>
                                    </li>
                                  ))}
                                </ul>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      )
                    })}
                    {!visibleRows.length && (
                      <tr><td colSpan={6} className="px-3 py-6 text-center text-sm text-muted-foreground">No keywords match this filter.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>

        <aside aria-label="Your selection" className="lg:sticky lg:top-36 lg:self-start">
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Your selection</h2>
              <span className="text-xs text-muted-foreground" aria-live="polite">
                {selected.length} of {MAX_SELECTED}
                {saveState === "saving" || draft !== null ? " · saving..." : saveState === "saved" ? " · saved" : ""}
              </span>
            </div>
            {selected.length ? (
              <ol className="mt-3 space-y-1.5">
                {selected.map((keyword, index) => (
                  <li key={keyword} className="flex items-center gap-2 rounded-md bg-muted px-2.5 py-1.5 text-sm">
                    <button
                      type="button"
                      onClick={() => makeFocus(keyword)}
                      disabled={index === 0}
                      aria-label={index === 0 ? `${keyword} is the focus keyword` : `Make ${keyword} the focus keyword`}
                      title={index === 0 ? "Focus keyword" : "Make this the focus keyword"}
                      className="shrink-0 disabled:cursor-default"
                    >
                      <Star className={`size-4 ${index === 0 ? "fill-gold text-gold" : "text-muted-foreground hover:text-gold"}`} aria-hidden="true" />
                    </button>
                    <span className="min-w-0 flex-1 break-words">{keyword}</span>
                    <button type="button" onClick={() => toggle(keyword)} aria-label={`Remove ${keyword}`} className="shrink-0 text-muted-foreground hover:text-destructive">
                      <X className="size-4" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">Nothing selected. The AI will choose keywords itself.</p>
            )}
            <p className="mt-3 text-xs text-muted-foreground">
              The first keyword (star) is the focus keyword. Use the star to change it.
            </p>
            <form
              className="mt-4 flex gap-2 border-t border-border pt-4"
              onSubmit={(event) => { event.preventDefault(); addCustom() }}
            >
              <input
                id="s2p-keywords-custom"
                value={customKeyword}
                onChange={(event) => setCustomKeyword(event.target.value)}
                maxLength={80}
                placeholder="Add your own keyword"
                aria-label="Add your own keyword"
                className="min-w-0 flex-1 rounded-md border border-border bg-background px-2.5 py-2 text-sm outline-none focus:ring-2 focus:ring-gold/40"
              />
              <button type="submit" disabled={!customKeyword.trim()} aria-label="Add keyword" className="inline-flex items-center justify-center rounded-md bg-gold px-3 text-gold-foreground disabled:opacity-50">
                <Plus className="size-4" aria-hidden="true" />
              </button>
            </form>
          </div>
        </aside>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-3 sm:px-4">
          <button
            id="s2p-keywords-back-to-facts"
            type="button"
            onClick={onBackToFacts}
            className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold transition-colors hover:bg-muted"
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
            Back to Facts
          </button>
          <div className="hidden flex-1 text-sm text-muted-foreground sm:block">
            {selected.length ? "Content will be written around your selected keywords." : "No keywords selected. The AI will choose."}
          </div>
          <button
            id="s2p-keywords-continue"
            type="button"
            onClick={onContinueToContent}
            disabled={running || draft !== null}
            className="ml-auto inline-flex items-center gap-2 rounded-md bg-confirm px-3.5 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:opacity-60"
          >
            {selected.length ? `Continue with ${selected.length} ${selected.length === 1 ? "keyword" : "keywords"}` : "Skip, let the AI choose"}
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  )
}
