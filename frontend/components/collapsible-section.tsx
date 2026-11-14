"use client"

import { useId, useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"

// The body is hidden, not unmounted, so results and form state survive a collapse.
// `actions` stay visible while collapsed (buttons, status badges).
export function CollapsibleSection({
  title,
  actions,
  children,
  defaultOpen = true,
}: {
  title: string
  actions?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  return (
    <div className="p-4">
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((value) => !value)}
          className="flex items-center gap-1 rounded text-xs font-semibold uppercase tracking-wide text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronDown className={`size-4 transition-transform ${open ? "" : "-rotate-90"}`} aria-hidden="true" />
          {title}
        </button>
        <div className="flex items-center gap-2">{actions}</div>
      </div>
      <div id={bodyId} hidden={!open}>{children}</div>
    </div>
  )
}
