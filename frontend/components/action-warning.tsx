"use client"

import { useEffect, useRef, useState } from "react"

type Warning = { message: string; confirmLabel?: string; alternative?: { label: string; action: () => void } }

export function useActionWarning() {
  const [warning, setWarning] = useState<Warning | null>(null)
  const resolve = useRef<((proceed: boolean) => void) | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  function close(proceed: boolean) {
    resolve.current?.(proceed)
    resolve.current = null
    setWarning(null)
  }
  useEffect(() => {
    if (warning) dialog.current?.showModal()
  }, [warning])
  useEffect(() => () => { resolve.current?.(false) }, [])
  function confirm(options: Warning) {
    return new Promise<boolean>((done) => {
      resolve.current?.(false)
      resolve.current = done
      setWarning(options)
    })
  }
  const warningDialog = warning && (
    <dialog ref={dialog} aria-label="Confirm action" onCancel={(event) => { event.preventDefault(); close(false) }}
      className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-xl border border-border bg-card p-5 text-foreground shadow-xl backdrop:bg-black/50">
      <h2 className="text-lg font-semibold">Continue with this action?</h2>
      <p className="mt-3 text-sm leading-relaxed">{warning.message}</p>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <button autoFocus type="button" onClick={() => close(false)} className="rounded-md border border-border px-3 py-2 text-sm">Cancel</button>
        <button type="button" onClick={() => close(true)} className="rounded-md bg-destructive px-3 py-2 text-sm font-semibold text-white">{warning.confirmLabel || "Continue anyway"}</button>
        {warning.alternative && <button type="button" onClick={() => { const action = warning.alternative!.action; close(false); action() }} className="rounded-md bg-ai px-3 py-2 text-sm font-semibold text-ai-foreground">{warning.alternative.label}</button>}
      </div>
    </dialog>
  )
  return { confirm, warningDialog }
}
