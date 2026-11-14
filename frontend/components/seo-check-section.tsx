"use client"

import { useState } from "react"
import { Check, Loader2, Search, X } from "lucide-react"
import { CollapsibleSection } from "@/components/collapsible-section"
import type { ApiClientOptions } from "@/lib/api"
import { loadSeoCheck, type ContentSession, type SeoCheckReport, type SeoFinding } from "@/lib/content-sessions"

const SEVERITY_CLASS: Record<SeoFinding["severity"], string> = {
  high: "bg-destructive/10 text-destructive",
  medium: "bg-warn/25 text-warn-foreground",
  low: "bg-muted text-muted-foreground",
}

function scoreLabel(score: number | null) {
  if (score == null) return "not calculated yet"
  return `${score}${score >= 71 ? " (good)" : score >= 41 ? " (okay)" : " (needs work)"}`
}

export function SeoCheckSection({
  auth,
  session,
  onRevise,
}: {
  auth: ApiClientOptions | null
  session: ContentSession
  onRevise: (fieldIds: string[], instruction: string) => void
}) {
  const [report, setReport] = useState<SeoCheckReport | null>(null)
  const [checkedVersion, setCheckedVersion] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  async function run() {
    if (!auth || loading) return
    setLoading(true)
    setError("")
    try {
      setReport(await loadSeoCheck(auth, session))
      setCheckedVersion(session.version)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not run the SEO check.")
    } finally {
      setLoading(false)
    }
  }

  const failed = report?.findings.filter((finding) => finding.status === "fail") ?? []
  const passed = report?.findings.filter((finding) => finding.status === "pass") ?? []
  const skipped = report?.findings.filter((finding) => finding.status === "skipped") ?? []
  const stale = report !== null && checkedVersion !== session.version

  return (
    <CollapsibleSection
      title="SEO check"
      actions={
        <>
          {report && !stale && (
            <span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${failed.length ? "bg-destructive/10 text-destructive" : "bg-confirm/12 text-confirm"}`}>
              {failed.length ? `${failed.length} to fix` : "all pass"}
            </span>
          )}
          <button
            id="s2p-content-seo-check"
            type="button"
            onClick={() => void run()}
            disabled={!auth || loading}
            title="Checks the draft against the focus keyphrase and the SEO rules of your workbook. No AI is used."
            className="inline-flex items-center gap-1.5 rounded-md border border-ai/40 bg-card px-2.5 py-1.5 text-xs font-semibold text-foreground transition-colors hover:bg-ai/10 disabled:opacity-60"
          >
            {loading ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : <Search className="size-3.5 text-ai" aria-hidden="true" />}
            {report ? "Check again" : "Check SEO"}
          </button>
        </>
      }
    >
      {error && <p role="status" className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{error}</p>}
      {!report && !error && (
        <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
          Not run yet. Checks the focus keyphrase in title, slug, meta description and introduction, plus the limits set in your workbook.
        </p>
      )}

      {report && (
        <div className="mt-3 space-y-3">
          {stale && <p className="rounded-md bg-warn/20 px-3 py-2 text-xs text-warn-foreground">The draft changed since this check. Check again for current results.</p>}
          <p className="flex flex-wrap gap-2 text-[11px] font-semibold" aria-live="polite">
            <span className="rounded-full bg-destructive/10 px-2 py-1 text-destructive">{report.counts.fail} to fix</span>
            <span className="rounded-full bg-confirm/12 px-2 py-1 text-confirm">{report.counts.pass} passed</span>
            {report.counts.skipped > 0 && <span className="rounded-full bg-muted px-2 py-1 text-muted-foreground">{report.counts.skipped} not applicable</span>}
          </p>

          {failed.map((finding) => (
            <div key={finding.check_id} className="rounded-md border border-border bg-background p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="flex items-start gap-1.5 text-xs font-semibold"><X className="mt-0.5 size-3.5 shrink-0 text-destructive" aria-hidden="true" />{finding.label}</p>
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${SEVERITY_CLASS[finding.severity]}`}>{finding.severity}</span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{finding.message}</p>
              {finding.field_ids.length > 0 && (
                <p className="mt-1.5 truncate font-mono text-[10px] text-ai">{finding.field_ids.join(", ")}</p>
              )}
            </div>
          ))}
          {!failed.length && <p className="rounded-md bg-confirm/10 px-3 py-2 text-xs">All applicable SEO checks pass.</p>}

          {report.revision_field_ids.length > 0 && (
            <button
              id="s2p-content-seo-revise"
              type="button"
              onClick={() => onRevise(report.revision_field_ids, report.revision_instruction)}
              className="w-full rounded-md bg-ai px-3 py-2 text-xs font-semibold text-ai-foreground transition-colors hover:opacity-90"
            >
              Revise {report.revision_field_ids.length} {report.revision_field_ids.length === 1 ? "field" : "fields"} to fix these
            </button>
          )}

          {passed.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground">Passed checks ({passed.length})</summary>
              <ul className="mt-2 space-y-1">
                {passed.map((finding) => (
                  <li key={finding.check_id} className="flex items-start gap-1.5"><Check className="mt-0.5 size-3.5 shrink-0 text-confirm" aria-hidden="true" />{finding.label}</li>
                ))}
              </ul>
            </details>
          )}
          {skipped.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground">Not applicable ({skipped.length})</summary>
              <ul className="mt-2 space-y-1 text-muted-foreground">
                {skipped.map((finding) => <li key={finding.check_id}>{finding.label}</li>)}
              </ul>
            </details>
          )}

          {report.yoast_reference && (
            <p className="rounded-md bg-muted px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              Stored by Yoast on WordPress: SEO {scoreLabel(report.yoast_reference.seo)}, readability {scoreLabel(report.yoast_reference.readability)}.
              Yoast only updates these when the post is opened in the WordPress editor, so they can be out of date.
            </p>
          )}
        </div>
      )}
    </CollapsibleSection>
  )
}
