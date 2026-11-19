"use client"

import { useId, type ReactNode } from "react"

// Disabled buttons cannot receive keyboard focus; their wrapper exposes the reason.
export function ActionHint({ reason, children, className = "" }: { reason: string; children: ReactNode; className?: string }) {
  const id = useId()
  return (
    <span className={`group/action relative inline-flex ${className}`} tabIndex={reason ? 0 : undefined}
      aria-describedby={reason ? id : undefined}>
      {children}
      {reason && <span id={id} role="tooltip"
        className="pointer-events-none absolute bottom-full left-0 z-50 mb-2 hidden w-64 rounded-md bg-topbar px-3 py-2 text-xs font-normal text-topbar-foreground shadow-lg group-hover/action:block group-focus/action:block">
        {reason}
      </span>}
    </span>
  )
}
