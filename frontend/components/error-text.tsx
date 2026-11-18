"use client"

import { useState } from "react"

// Shows an API/status message: the plain sentence first, "(Technical details: ...)" folded away
// behind a toggle (kept for debugging), and links made clickable. Use it wherever a message is shown.
const DETAILS = /^([\s\S]*?)\s*\(Technical details: ([\s\S]*)\)\s*$/

function withLinks(text: string) {
  return text.split(/(https?:\/\/[^\s)]+)/).map((part, index) =>
    index % 2 === 1 ? (
      <a key={index} href={part} target="_blank" rel="noopener noreferrer" className="underline">
        {part}
      </a>
    ) : (
      part
    ),
  )
}

export function ErrorText({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const match = DETAILS.exec(text)
  if (!match) return <>{withLinks(text)}</>
  return (
    <>
      {withLinks(match[1])}{" "}
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="whitespace-nowrap underline opacity-80">
        {open ? "Hide technical details" : "Show technical details"}
      </button>
      {open && <span className="mt-1 block select-all break-words font-mono text-[0.85em] opacity-80">{match[2]}</span>}
    </>
  )
}
