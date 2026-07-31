"use client"

import { FormEvent, useState } from "react"
import { Check, KeyRound, Loader2, X } from "lucide-react"
import { ApiError } from "@/lib/api"
import { validateImportKey, type AuthClient } from "@/lib/content-sessions"

export type AuthResult = {
  apiKey: string
  userId: string
  client: AuthClient
}

export function AuthModal({
  onAuthenticated,
}: {
  onAuthenticated: (result: AuthResult) => void
}) {
  const [apiKey, setApiKey] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const cleanedKey = apiKey.trim()
    if (!cleanedKey) {
      setError("Access key is required.")
      return
    }
    setLoading(true)
    setError("")
    setSuccess("")
    try {
      const data = await validateImportKey({ apiKey: cleanedKey, userId: "" })
      const client = data.clients[0]
      if (!client) throw new Error("No configured client was returned.")
      setSuccess(`Welcome, ${client.client_id}.`)
      onAuthenticated({ apiKey: cleanedKey, userId: client.client_id, client })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setError("Invalid access key.")
      } else {
        setError(error instanceof Error ? error.message : "Could not connect.")
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-topbar/70 px-4 backdrop-blur-sm">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg border border-border bg-card p-4 shadow-xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="flex size-9 items-center justify-center rounded-md bg-gold/15 text-gold">
              <KeyRound className="size-4" aria-hidden="true" />
            </span>
            <div>
              <h1 className="text-base font-semibold text-foreground">Client access</h1>
              <p className="text-xs text-muted-foreground">SPEECH2POST</p>
            </div>
          </div>
          <span className="flex size-8 items-center justify-center rounded-md text-muted-foreground">
            <X className="size-4" aria-hidden="true" />
          </span>
        </div>

        <label htmlFor="s2p-auth-import-key" className="mb-1.5 block text-xs font-medium text-muted-foreground">
          Access key
        </label>
        <input
          id="s2p-auth-import-key"
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(event) => setApiKey(event.target.value)}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
        />

        {error && <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
        {success && (
          <p className="mt-3 flex items-center gap-1.5 rounded-md bg-confirm/10 px-3 py-2 text-sm text-confirm">
            <Check className="size-4" aria-hidden="true" />
            {success}
          </p>
        )}

        <button
          id="s2p-auth-connect"
          type="submit"
          disabled={loading}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-md bg-confirm px-3.5 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
          Connect
        </button>
      </form>
    </div>
  )
}
