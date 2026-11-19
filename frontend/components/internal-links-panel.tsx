"use client"

import { useState } from "react"
import { Check, ChevronDown, RefreshCw, Trash2 } from "lucide-react"
import type { ContentSession, SessionLinkOptions } from "@/lib/content-sessions"

export function InternalLinksPanel({ session, options, queued, busy, onDestination, onToggle, onAction }: {
  session: ContentSession
  options: SessionLinkOptions | null
  queued: Record<string, string>
  busy: boolean
  onDestination: (id: string, destination: string) => void
  onToggle: (id: string) => void
  onAction: (action: "add" | "remove" | "refresh", id?: string) => void
}) {
  const [search, setSearch] = useState("")
  const selected = new Set(session.selected_links.map((link) => link.link_id))
  const candidates = (options?.links || []).filter((link) => selected.has(link.link_id))
  const placed = new Set(options?.placed_link_ids || [])
  const available = (options?.links || []).filter((link) => !selected.has(link.link_id)
    && `${link.anchor_text} ${link.target_url} ${link.usage_context}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const atLimit = options?.maximum != null && candidates.length >= options.maximum

  return (
    <details open id="s2p-content-internal-links" className="group order-1 scroll-mt-28 rounded-xl border border-border bg-card">
      <summary className="flex cursor-pointer list-none items-center gap-2 p-4">
        <h2 className="text-sm font-semibold">Internal links</h2>
        <span className="text-xs text-muted-foreground">({candidates.length}{options?.maximum != null ? `/${options.maximum}` : ""})</span>
        <ChevronDown className="ml-auto size-4 text-muted-foreground" />
      </summary>
      <div className="space-y-3 border-t border-border p-4">
        <button id="s2p-content-refresh-link-candidates" type="button" disabled={busy || !options}
          onClick={() => onAction("refresh")}
          className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs font-semibold disabled:opacity-50">
          <RefreshCw className="size-3.5" />Refresh unplaced candidates
        </button>
        <details className="rounded-md border border-border bg-background">
          <summary className="cursor-pointer px-3 py-2 text-xs font-semibold">Add candidate…</summary>
          <div className="space-y-2 p-2">
            <input type="search" aria-label="Search all eligible internal links" placeholder="Search anchor, URL or description…"
              value={search} onChange={(event) => setSearch(event.target.value)}
              className="w-full rounded-md border border-border bg-card px-2 py-2 text-xs" />
            {atLimit && <p className="text-xs text-muted-foreground">Candidate limit reached. Remove a candidate first.</p>}
            <ul className="max-h-56 overflow-auto">
              {available.map((link) => <li key={link.link_id}>
                <button type="button" disabled={busy || atLimit} onClick={() => onAction("add", link.link_id)}
                  className="w-full rounded px-2 py-2 text-left text-xs hover:bg-muted disabled:opacity-50">
                  <span className="block font-semibold">{link.anchor_text}</span>
                  <span className="block break-all text-muted-foreground">{link.target_url}</span>
                </button>
              </li>)}
            </ul>
            {!available.length && <p className="text-xs text-muted-foreground">No matching links available.</p>}
          </div>
        </details>
        {candidates.map((candidate) => {
          const used = placed.has(candidate.link_id)
          const checked = Object.hasOwn(queued, candidate.link_id)
          const suggested = options?.fields.find((field) => field.field_key === candidate.suggested_field_key)
          return <div key={candidate.link_id} className="rounded-md border border-border bg-background p-2.5">
            <div className="flex items-start gap-2">
              <label className="flex min-w-0 flex-1 items-start gap-2">
                {used ? <Check className="mt-0.5 size-4 shrink-0 text-confirm" aria-label="Placed" /> : (
                  <input id={`s2p-content-link-${candidate.link_id}`} type="checkbox" checked={checked}
                    onChange={() => onToggle(candidate.link_id)} disabled={busy || !options?.fields.length}
                    className="mt-0.5 size-4 accent-gold" />
                )}
                <span className="min-w-0 text-xs">
                  <span className="block font-medium">{candidate.anchor_text}</span>
                  <span className="block break-all text-muted-foreground">{candidate.target_url}</span>
                </span>
              </label>
              <button type="button" id={`s2p-content-remove-link-${candidate.link_id}`} disabled={busy}
                onClick={() => onAction("remove", candidate.link_id)} aria-label={`Remove ${candidate.anchor_text}`}
                title={used ? "Remove the link and candidate; keep its text." : "Remove this candidate."}
                className="rounded p-1 text-destructive hover:bg-muted disabled:opacity-50"><Trash2 className="size-4" /></button>
            </div>
            {used && <p className="mt-2 text-[11px] text-muted-foreground">Placed in: {(options?.placed_field_keys[candidate.link_id] || []).map((key) => options?.fields.find((field) => field.field_key === key)?.label || key).join(", ") || "draft"}</p>}
            {!used && checked && <>
              <select id={`s2p-content-link-destination-${candidate.link_id}`} aria-label={`Destination for ${candidate.anchor_text}`}
                value={queued[candidate.link_id]} onChange={(event) => onDestination(candidate.link_id, event.target.value)} disabled={busy}
                className="mt-2 w-full rounded-md border border-border bg-card px-2 py-1.5 text-xs">
                <option value="">- choose for me -</option>
                {options?.fields.map((field) => <option key={field.field_key} value={field.acf_field_name}>{field.label}</option>)}
              </select>
              <p className="mt-2 text-[11px] text-muted-foreground">
                {queued[candidate.link_id] ? "Preferred destination; another eligible field may be used if needed."
                  : suggested ? `Suggested destination: ${suggested.label}. Chosen locally without AI tokens.` : "No eligible destination currently has room for this link."}
              </p>
            </>}
          </div>
        })}
        {!candidates.length && <p className="text-xs text-muted-foreground">No candidates selected. Search to add one or refresh suggestions.</p>}
        <p className="text-xs text-muted-foreground">Select free candidates, then use Revise selected fields. Placement tries existing text first and uses AI only if needed.</p>
      </div>
    </details>
  )
}
