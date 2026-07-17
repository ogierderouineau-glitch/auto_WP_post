"use client"

import { Mic, Bot, CornerDownLeft } from "lucide-react"

export function AgentWidget({
  instruction,
  exampleTranscript,
  actionLabel,
  onAction,
}: {
  instruction: string
  exampleTranscript: string
  actionLabel: string
  onAction: () => void
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-3 sm:p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex size-8 items-center justify-center rounded-md bg-gold/15 text-gold">
          <Bot className="size-4" aria-hidden="true" />
        </span>
        <h2 className="text-sm font-semibold">Agent</h2>
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">{instruction}</p>

      {/* static waveform */}
      <div className="mt-3 flex h-11 items-center justify-center gap-0.5 rounded-lg bg-muted px-3">
        {[6, 12, 20, 14, 26, 30, 18, 28, 10, 22, 30, 16, 24, 12, 20, 8, 18, 26, 14, 10].map((h, i) => (
          <span key={i} className="w-1 rounded-full bg-gold/70" style={{ height: `${h}px` }} aria-hidden="true" />
        ))}
      </div>

      <button
        id="s2p-agent-start-recording"
        type="button"
        className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
      >
        <Mic className="size-4 text-destructive" aria-hidden="true" />
        Start recording
      </button>

      <div className="mt-3">
        <p className="mb-1.5 text-xs font-medium text-muted-foreground">Example transcript</p>
        <div className="rounded-lg border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground">
          {exampleTranscript}
        </div>
      </div>

      <button
        id="s2p-agent-submit"
        type="button"
        onClick={onAction}
        className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-ai px-3.5 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90"
      >
        <CornerDownLeft className="size-4" aria-hidden="true" />
        {actionLabel}
      </button>
    </div>
  )
}
