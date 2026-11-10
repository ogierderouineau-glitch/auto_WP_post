"use client"

import { useState } from "react"

export function SessionName({ name, sessionId, onSave }: {
  name?: string
  sessionId: string
  onSave: (name: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError("")
    try {
      await onSave(value)
      setEditing(false)
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not rename session.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-md bg-white/5 px-2.5 py-1 text-xs">
      {editing ? (
        <form onSubmit={save}>
          <input autoFocus aria-label="Session name" maxLength={80} required value={value}
            onChange={(event) => setValue(event.target.value)} disabled={saving}
            onKeyDown={(event) => { if (event.key === "Escape" && !saving) setEditing(false) }}
            className="rounded border border-border bg-card px-2 py-1 text-foreground" />
          <button type="submit" disabled={saving || !value.trim()} className="ml-2 disabled:opacity-50">
            {saving ? "Saving…" : "Save"}
          </button>
          <button type="button" disabled={saving} onClick={() => setEditing(false)} className="ml-2">Cancel</button>
          {error && <p role="alert" className="mt-1 text-red-300">{error}</p>}
        </form>
      ) : (
        <button type="button" title={`Rename session · ${sessionId}`}
          onClick={() => { setValue(name || ""); setEditing(true); setError("") }}>
          <span className="text-topbar-foreground/55">Session: </span>
          <span className="font-medium text-topbar-foreground">{name || "Untitled session"}</span>
        </button>
      )}
    </div>
  )
}
