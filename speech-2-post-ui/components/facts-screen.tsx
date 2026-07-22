"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  CircleHelp,
  Loader2,
  Sparkles,
} from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  saveSessionFactCorrections,
  type ContentSession,
  type FactSchemaField,
  type FactValue,
  type WorkbookStatus,
} from "@/lib/content-sessions"
import { statusMessageClass } from "@/lib/status-style"

type SectionId = "required" | "optional" | "ai"
type OperationState = "idle" | "loading" | "success" | "error"

type FactRowModel = {
  key: string
  label: string
  required: boolean
  value: string
  source: string
  confidence: "High" | "Medium" | "Low"
  section: SectionId
  enumOptions: { value: string; label: string }[]
}

const TONE = {
  required: {
    border: "border-destructive/30",
    header: "bg-destructive/5",
    icon: "text-destructive",
    Icon: CircleAlert,
  },
  optional: {
    border: "border-warn/40",
    header: "bg-warn/10",
    icon: "text-warn-foreground",
    Icon: CircleHelp,
  },
  ai: {
    border: "border-confirm/30",
    header: "bg-confirm/5",
    icon: "text-confirm",
    Icon: Sparkles,
  },
} as const

function displayValue(value: unknown) {
  if (value == null) return ""
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ")
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

function confidenceLabel(fact?: FactValue): "High" | "Medium" | "Low" {
  const confidence = Number(fact?.confidence ?? 0)
  if (confidence >= 0.8) return "High"
  if (confidence >= 0.5) return "Medium"
  return "Low"
}

function sourceLabel(fact?: FactValue) {
  if (!fact) return "Not detected"
  if (fact.confirmed) return fact.source === "user_correction" ? "User" : "Confirmed"
  return fact.source || "AI"
}

function hasValue(value: string) {
  return value.trim() !== ""
}

function ConfidenceBadge({ level }: { level: FactRowModel["confidence"] }) {
  const map = {
    High: "bg-confirm/15 text-confirm",
    Medium: "bg-warn/25 text-warn-foreground",
    Low: "bg-destructive/15 text-destructive",
  } as const
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold ${map[level]}`}>
      {level}
    </span>
  )
}

function FactRow({
  fact,
  value,
  changed,
  selectedForReview,
  onChange,
  onBlur,
  onReviewSelectionChange,
}: {
  fact: FactRowModel
  value: string
  changed: boolean
  selectedForReview: boolean
  onChange: (value: string) => void
  onBlur: (nextTarget: EventTarget | null) => void
  onReviewSelectionChange: () => void
}) {
  const missingRequired = fact.required && !hasValue(value)

  return (
    <div className="rounded-lg border border-border bg-card p-3 lg:grid lg:grid-cols-[minmax(170px,210px)_minmax(0,1fr)_max-content_92px] lg:items-start lg:gap-3 lg:rounded-none lg:border-0 lg:border-b lg:border-border lg:bg-transparent lg:p-2.5">
      <label className="flex min-w-0 cursor-pointer items-start gap-2">
        <input
          id={`s2p-facts-review-${fact.key}`}
          type="checkbox"
          checked={selectedForReview}
          onChange={onReviewSelectionChange}
          aria-label={`Include ${fact.label} in AI review`}
          className="mt-0.5 size-4 shrink-0 accent-ai"
        />
        <span className="min-w-0">
          <span className="block text-sm font-medium text-foreground">{fact.label}</span>
          <span className="block font-mono text-[11px] text-muted-foreground">{fact.key}</span>
        </span>
      </label>

      <div className="mt-2 lg:mt-0">
        {fact.enumOptions.length ? (
          <select
            id={`s2p-facts-value-${fact.key}`}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onBlur={(event) => onBlur(event.relatedTarget)}
            aria-label={fact.label}
            aria-invalid={missingRequired}
            className={[
              "w-full rounded-md border bg-background px-2.5 py-1.5 text-sm text-foreground outline-none transition-colors focus:ring-2 focus:ring-gold/40",
              missingRequired ? "border-destructive/50" : "border-border",
            ].join(" ")}
          >
            <option value="">{fact.required ? "Select a value" : "Not specified"}</option>
            {value && !fact.enumOptions.some((option) => option.value === value) && (
              <option value={value}>{value}</option>
            )}
            {fact.enumOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        ) : (
          <input
            id={`s2p-facts-value-${fact.key}`}
            type="text"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onBlur={(event) => onBlur(event.relatedTarget)}
            aria-label={fact.label}
            aria-invalid={missingRequired}
            placeholder={fact.required ? "Required" : "Optional"}
            className={[
              "w-full rounded-md border bg-background px-2.5 py-1.5 text-sm text-foreground outline-none transition-colors focus:ring-2 focus:ring-gold/40",
              missingRequired ? "border-destructive/50" : "border-border",
            ].join(" ")}
          />
        )}
        {missingRequired && (
          <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
            <CircleAlert className="size-3.5" aria-hidden="true" />
            This field is required
          </p>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 lg:mt-0">
        <span
          className={[
            "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold",
            fact.required ? "bg-destructive/15 text-destructive" : "bg-muted text-muted-foreground",
          ].join(" ")}
        >
          {fact.required ? "Required" : "Optional"}
        </span>
        <span className="inline-flex items-center rounded bg-secondary px-1.5 py-0.5 text-[10px] font-semibold text-secondary-foreground">
          {fact.source}
        </span>
        <ConfidenceBadge level={fact.confidence} />
      </div>

      <div className="mt-2 flex items-center gap-1.5 lg:mt-0 lg:justify-end">
        {changed ? (
          <span className="inline-flex items-center rounded bg-ai/10 px-1.5 py-0.5 text-[10px] font-semibold text-ai">
            Edited
          </span>
        ) : hasValue(value) ? (
          <span className="inline-flex items-center gap-1 text-xs text-confirm">
            <Check className="size-3.5" aria-hidden="true" />
            Saved
          </span>
        ) : null}
      </div>
    </div>
  )
}

function Section({
  id,
  title,
  count,
  open,
  onToggle,
  children,
}: {
  id: SectionId
  title: string
  count: number
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  const tone = TONE[id]
  return (
    <div className={`overflow-hidden rounded-xl border ${tone.border} bg-card`}>
      <button
        id={`s2p-facts-section-${id}`}
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className={`flex w-full items-center justify-between gap-2 px-4 py-3.5 text-left ${tone.header}`}
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <tone.Icon className={`size-4 ${tone.icon}`} aria-hidden="true" />
          {title}
          <span className="rounded-full bg-background px-2 py-0.5 text-xs font-medium text-muted-foreground">
            {count}
          </span>
        </span>
        <ChevronDown
          className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div className="border-t border-border p-3 lg:p-0">
          <div className="hidden border-b border-border px-2.5 py-2 text-[11px] font-semibold uppercase text-muted-foreground lg:grid lg:grid-cols-[minmax(170px,210px)_minmax(0,1fr)_max-content_92px] lg:gap-3">
            <span>Field</span>
            <span>Value</span>
            <span>Details</span>
            <span className="text-right">Status</span>
          </div>
          <div className="flex flex-col gap-3 lg:gap-0">{children}</div>
        </div>
      )}
    </div>
  )
}

function buildRows(schema: FactSchemaField[], session: ContentSession | null): FactRowModel[] {
  if (!session) return []
  return schema.map((field) => {
    const confirmed = session.confirmed_facts[field.field_key]
    const extracted = session.extracted_facts[field.field_key]
    const fact = confirmed || extracted
    const value = displayValue(fact?.value)
    const section: SectionId = hasValue(value) ? "ai" : field.required ? "required" : "optional"
    return {
      key: field.field_key,
      label: field.label || field.field_key,
      required: field.required,
      value,
      source: sourceLabel(fact),
      confidence: confidenceLabel(fact),
      section,
      enumOptions: field.enum_options || [],
    }
  })
}

export function FactsScreen({
  auth,
  session,
  workbook,
  onBackToMedia,
  onSessionChange,
  onContinueToContent,
  selectedFactKeys,
  onSelectedFactKeysChange,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  workbook: WorkbookStatus | null
  onBackToMedia: () => void
  onSessionChange: (session: ContentSession) => void
  onContinueToContent: () => void
  selectedFactKeys: string[]
  onSelectedFactKeysChange: (keys: string[]) => void
}) {
  const rows = useMemo(() => buildRows(workbook?.fact_schema || [], session), [session, workbook])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [openSection, setOpenSection] = useState<SectionId | null>(null)
  const [operation, setOperation] = useState<OperationState>("idle")
  const [message, setMessage] = useState("")

  useEffect(() => {
    setDrafts(Object.fromEntries(rows.map((row) => [row.key, row.value])))
  }, [session?.session_id, session?.version, workbook?.selected_post_type_key])

  const changed = rows.filter((row) => (drafts[row.key] ?? row.value) !== row.value)
  const missingRequired = rows.filter((row) => row.section === "required").length
  const missingOptional = rows.filter((row) => row.section === "optional").length
  const requiredTotal = rows.filter((row) => row.required).length
  const requiredComplete = Math.max(0, requiredTotal - missingRequired)
  const aiRows = rows.filter((row) => row.section === "ai")
  const progress = requiredTotal ? Math.round((requiredComplete / requiredTotal) * 100) : 100
  const allRequiredDone = missingRequired === 0
  const selectedFacts = new Set(selectedFactKeys)
  const allFactsSelected = rows.length > 0 && selectedFactKeys.length === rows.length

  const grouped = {
    required: rows.filter((row) => row.section === "required"),
    optional: rows.filter((row) => row.section === "optional"),
    ai: rows.filter((row) => row.section === "ai"),
  }

  useEffect(() => {
    setOpenSection((current) => {
      if (current && grouped[current].length) return current
      return (["required", "optional", "ai"] as SectionId[]).find((id) => grouped[id].length) || null
    })
  }, [grouped.required.length, grouped.optional.length, grouped.ai.length])

  function toggleSection(id: SectionId) {
    setOpenSection((current) => current === id ? null : id)
  }

  function toggleFactSelection(key: string) {
    const next = new Set(selectedFactKeys)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onSelectedFactKeysChange([...next])
  }

  function correctionPayload(includeAllValues: boolean) {
    const entries = rows
      .map((row) => [row.key, (drafts[row.key] ?? row.value).trim()] as const)
      .filter(([key, value]) => value && (includeAllValues || value !== rows.find((row) => row.key === key)?.value))
    return Object.fromEntries(entries)
  }

  async function saveCorrections(includeAllValues = false) {
    if (!auth || !session) return null
    const corrections = correctionPayload(includeAllValues)
    if (!Object.keys(corrections).length) return session
    const data = await saveSessionFactCorrections(auth, session, corrections)
    onSessionChange(data.session)
    return data.session
  }

  async function handleSave() {
    if (operation === "loading" || !changed.length) return
    setOperation("loading")
    setMessage("Saving corrections...")
    try {
      await saveCorrections(false)
      setOperation("success")
      setMessage("Corrections saved.")
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not save corrections.")
    }
  }

  async function handleConfirm() {
    if (!auth || !session || !allRequiredDone) return
    setOperation("loading")
    setMessage("Confirming facts...")
    try {
      await saveCorrections(true)
      setOperation("success")
      setMessage("Facts confirmed.")
      onContinueToContent()
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Could not confirm facts.")
    }
  }

  const renderRows = (facts: FactRowModel[]) =>
    facts.length ? (
      facts.map((fact) => (
        <FactRow
          key={fact.key}
          fact={fact}
          value={drafts[fact.key] ?? fact.value}
          changed={(drafts[fact.key] ?? fact.value) !== fact.value}
          selectedForReview={selectedFacts.has(fact.key)}
          onChange={(value) => setDrafts((current) => ({ ...current, [fact.key]: value }))}
          onBlur={(nextTarget) => {
            if (nextTarget instanceof Element && nextTarget.closest("[data-facts-action]")) return
            void handleSave()
          }}
          onReviewSelectionChange={() => toggleFactSelection(fact.key)}
        />
      ))
    ) : (
      <p className="px-3 py-4 text-sm text-muted-foreground">Nothing to review in this section.</p>
    )

  if (!session) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
        Create or load a session before reviewing facts.
      </div>
    )
  }

  return (
    <>
      <div className="pb-28">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-foreground sm:text-xl">Review event facts</h1>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Check the information extracted from your media and voice descriptions. Complete required fields before
              continuing. Use the field checkboxes to choose which facts the AI reviews next; unchecked facts remain
              unchanged.
            </p>
          </div>

        </div>

        <div className="mt-4 rounded-xl border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground">
            {selectedFactKeys.length} of {rows.length} facts selected for AI review.
          </p>
          <button
            id="s2p-facts-toggle-all"
            type="button"
            onClick={() => onSelectedFactKeysChange(allFactsSelected ? [] : rows.map((row) => row.key))}
            title={allFactsSelected ? "Exclude every fact from the next AI review" : "Include every fact in the next AI review"}
            className="mt-2 inline-flex items-center rounded-md border border-border bg-card px-3 py-2 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
          >
            {allFactsSelected ? "Unselect all facts for revision" : "Select all facts for revision"}
          </button>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <button id="s2p-facts-summary-required" type="button" onClick={() => toggleSection("required")} aria-pressed={openSection === "required"} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors ${openSection === "required" ? "bg-destructive/15 ring-1 ring-destructive/30" : "bg-destructive/5 hover:bg-destructive/10"}`}>
              <CircleAlert className="size-4 shrink-0 text-destructive" aria-hidden="true" />
              <span className="text-sm text-foreground">
                <span className="font-semibold">{missingRequired}</span> required facts missing
              </span>
            </button>
            <button id="s2p-facts-summary-optional" type="button" onClick={() => toggleSection("optional")} aria-pressed={openSection === "optional"} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors ${openSection === "optional" ? "bg-warn/25 ring-1 ring-warn/40" : "bg-warn/10 hover:bg-warn/20"}`}>
              <CircleHelp className="size-4 shrink-0 text-warn-foreground" aria-hidden="true" />
              <span className="text-sm text-foreground">
                <span className="font-semibold">{missingOptional}</span> optional facts missing
              </span>
            </button>
            <button id="s2p-facts-summary-ai" type="button" onClick={() => toggleSection("ai")} aria-pressed={openSection === "ai"} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors ${openSection === "ai" ? "bg-confirm/15 ring-1 ring-confirm/30" : "bg-confirm/5 hover:bg-confirm/10"}`}>
              <Sparkles className="size-4 shrink-0 text-confirm" aria-hidden="true" />
              <span className="text-sm text-foreground">
                <span className="font-semibold">{aiRows.length}</span> populated facts
              </span>
            </button>
          </div>

          <div className="mt-4">
            <div className="mb-1.5 flex items-center justify-between text-xs font-medium text-muted-foreground">
              <span>Required completeness</span>
              <span>
                {requiredComplete}/{requiredTotal || 0} - {progress}%
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
              <div
                className={`h-full rounded-full transition-all ${allRequiredDone ? "bg-confirm" : "bg-gold"}`}
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          {message && (
            <p className={`mt-3 rounded-md px-3 py-2 text-xs ${statusMessageClass(operation, message)}`}>
              {message}
            </p>
          )}
        </div>

        <div className="mt-4 flex min-w-0 flex-col gap-4">
          <Section
            id="required"
            title="Missing required facts"
            count={grouped.required.length}
            open={openSection === "required"}
            onToggle={() => toggleSection("required")}
          >
            {renderRows(grouped.required)}
          </Section>

          <Section
            id="optional"
            title="Missing optional facts"
            count={grouped.optional.length}
            open={openSection === "optional"}
            onToggle={() => toggleSection("optional")}
          >
            {renderRows(grouped.optional)}
          </Section>

          <Section
            id="ai"
            title="AI-populated facts"
            count={grouped.ai.length}
            open={openSection === "ai"}
            onToggle={() => toggleSection("ai")}
          >
            {renderRows(grouped.ai)}
          </Section>
        </div>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 backdrop-blur">
        <div className="mx-auto max-w-7xl px-3 py-3 sm:px-4">
          <div className="mb-2 sm:hidden">
            {!allRequiredDone ? (
              <span className="inline-flex items-center gap-1.5 text-sm text-destructive">
                <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
                {missingRequired} required {missingRequired === 1 ? "fact" : "facts"} still missing
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Check className="size-4 shrink-0 text-confirm" aria-hidden="true" />
                All required facts complete
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <button
              id="s2p-facts-back-to-media"
              type="button"
              data-facts-action
              onClick={onBackToMedia}
              className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
            >
              <ChevronLeft className="size-4" aria-hidden="true" />
              Back to Media
            </button>

            <div className="hidden min-w-0 flex-1 sm:block">
              {!allRequiredDone ? (
                <span className="inline-flex items-center gap-1.5 text-sm text-destructive">
                  <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
                  {missingRequired} required {missingRequired === 1 ? "fact" : "facts"} still missing
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                  <Check className="size-4 shrink-0 text-confirm" aria-hidden="true" />
                  All required facts complete
                </span>
              )}
            </div>

            <button
              id="s2p-facts-confirm"
              type="button"
              data-facts-action
              onClick={handleConfirm}
              disabled={!allRequiredDone || operation === "loading"}
              className="ml-auto inline-flex items-center gap-2 rounded-md bg-confirm px-4 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 sm:ml-0"
            >
              {operation === "loading" ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
              Confirm facts
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
