"use client"

import { useEffect, useRef, useState } from "react"
import { Bot, CircleDot, Loader2, Mic, Send, Square, Trash2 } from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  analyzeSessionInputs,
  regenerateSessionDraft,
  saveSessionTranscript,
  transcribeSessionRecording,
  waitForSessionJob,
  type ContentSession,
} from "@/lib/content-sessions"

type RecordingItem = {
  id: string
  name: string
  status: "transcribing" | "done" | "failed"
  text: string
  error?: string
  file: File
}

type ActiveScreen = "media" | "facts" | "content" | "wordpress"

const SCREEN_COPY: Record<ActiveScreen, { title: string; instruction: string; action: string; placeholder: string }> = {
  media: {
    title: "Media agent",
    instruction: "Describe the event through the selected images. Include concrete facts: place, date, people, service, atmosphere, highlights and challenges.",
    action: "Extract facts",
    placeholder: "Add general event details or instructions for fact extraction. Picture descriptions remain attached to their images.",
  },
  facts: {
    title: "Facts agent",
    instruction: "Empty facts are selected automatically. Adjust the checkboxes on the Facts screen if needed, then explain what should be corrected or completed.",
    action: "Update facts",
    placeholder: "Only checked facts will be reviewed. For example: Correct the venue, add the event date, or explain a missing fact.",
  },
  content: {
    title: "Content agent",
    instruction: "Describe what should change in the generated content. Mention exact fields or sections when you can. You can help in the process by selecting only a few fields by unchecking the others in the list",
    action: "Revise selected fields",
    placeholder: "For example: Make the introduction shorter and give the title a warmer tone.",
  },
  wordpress: {
    title: "WordPress agent",
    instruction: "Review publishing notes before sending content to WordPress. Agent actions for this screen are not connected yet.",
    action: "Not connected",
    placeholder: "WordPress agent actions are not connected yet. Review the publishing checklist on this screen.",
  },
}

function appendText(current: string, next: string) {
  const cleanCurrent = current.trim()
  const cleanNext = next.trim()
  if (!cleanCurrent) return cleanNext
  if (!cleanNext) return cleanCurrent
  return `${cleanCurrent}\n\n${cleanNext}`
}

function combinedPictureTranscripts(session: ContentSession) {
  const byMediaId = new Map(session.image_refs.map((image) => [image.media_id, image.filename]))
  return Object.entries(session.image_context_transcripts || {})
    .map(([mediaId, transcript]) => {
      const text = String(transcript || "").trim()
      if (!text) return ""
      const filename = byMediaId.get(mediaId) || mediaId || "image"
      return `[${filename}]\n${text}`
    })
    .filter(Boolean)
    .join("\n\n")
}

export function RecordingWidget({
  auth,
  session,
  activeScreen,
  open,
  onOpenChange,
  onSessionChange,
  onNavigateFacts,
  selectedFactKeys,
  availableFactKeys,
  onSelectedFactKeysChange,
  selectedPictureId,
  selectedContentFieldIds,
  selectedContentLinks,
  contentAiAssistedLinkPlacement,
  onPictureTranscriptAppend,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  activeScreen: ActiveScreen
  open: boolean
  onOpenChange: (open: boolean) => void
  onSessionChange: (session: ContentSession) => void
  onNavigateFacts: () => void
  selectedFactKeys: string[]
  availableFactKeys: string[]
  onSelectedFactKeysChange: (keys: string[] | null) => void
  selectedPictureId?: string
  selectedContentFieldIds: string[]
  selectedContentLinks: Record<string, string>[]
  contentAiAssistedLinkPlacement: boolean
  onPictureTranscriptAppend: (text: string) => Promise<void>
}) {
  const [recording, setRecording] = useState(false)
  const [items, setItems] = useState<RecordingItem[]>([])
  const [transcript, setTranscript] = useState("")
  const [status, setStatus] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const transcriptRef = useRef("")
  const recordingEpoch = useRef(0)
  const copy = SCREEN_COPY[activeScreen]
  const allFactsSelected = availableFactKeys.length > 0 && selectedFactKeys.length === availableFactKeys.length
  const hasContentInstruction = transcript.trim() || selectedContentLinks.some(
    (link) => link.revision_requested === "true",
  )

  function setSyncedTranscript(value: string) {
    transcriptRef.current = value
    setTranscript(value)
  }

  useEffect(() => {
    recordingEpoch.current += 1
    if (recorder.current?.state !== "inactive") recorder.current?.stop()
    recorder.current = null
    chunks.current = []
    setRecording(false)
    setSyncedTranscript("")
    setItems([])
    setStatus("")
  }, [activeScreen, session?.session_id])

  async function transcribe(file: File, id: string, requestSession = session, epoch = recordingEpoch.current) {
    if (!auth || !requestSession) return
    try {
      const data = await transcribeSessionRecording(auth, requestSession, file)
      if (epoch !== recordingEpoch.current) return
      const text = data.text || ""
      setItems((current) =>
        current.map((item) => (item.id === id ? { ...item, status: "done", text } : item)),
      )
      if (activeScreen === "media" && selectedPictureId) {
        try {
          const pictureIsUploading = selectedPictureId.startsWith("pending-")
          setStatus(pictureIsUploading ? "Adding transcript to the uploading picture..." : "Saving transcript to the active picture...")
          await onPictureTranscriptAppend(text)
          if (epoch !== recordingEpoch.current) return
          setItems((current) => current.filter((item) => item.id !== id))
          setSyncedTranscript("")
          setStatus(pictureIsUploading ? "Transcript queued for the uploading picture." : "Transcript saved to the active picture.")
        } catch (error) {
          setStatus(error instanceof Error ? error.message : "Picture transcript could not be saved.")
        }
      } else {
        const nextTranscript = appendText(transcriptRef.current, text)
        setSyncedTranscript(nextTranscript)
      }
      if (activeScreen !== "media" || !selectedPictureId) setStatus("Recording transcribed.")
    } catch (error) {
      if (epoch !== recordingEpoch.current) return
      setItems((current) =>
        current.map((item) =>
          item.id === id
            ? {
                ...item,
                status: "failed",
                error: error instanceof Error ? error.message : "Transcription failed.",
              }
            : item,
        ),
      )
      setStatus("Transcription failed.")
    }
  }

  async function startRecording() {
    if (!auth || !session) {
      setStatus("Create or load a session first.")
      return
    }
    if (!window.isSecureContext) {
      setStatus("Microphone access requires HTTPS or localhost. This page is using insecure HTTP.")
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setStatus("Recording is not supported by this browser.")
      return
    }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      setStatus(
        error instanceof DOMException && error.name === "NotAllowedError"
          ? "Microphone permission was denied. Allow microphone access in the browser's site settings."
          : error instanceof Error
            ? `Could not start recording: ${error.message}`
            : "Could not start recording.",
      )
      return
    }
    chunks.current = []
    const epoch = recordingEpoch.current
    const requestSession = session
    const nextRecorder = new MediaRecorder(stream)
    recorder.current = nextRecorder
    nextRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.current.push(event.data)
    })
    nextRecorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop())
      if (epoch !== recordingEpoch.current) return
      const blob = new Blob(chunks.current, { type: nextRecorder.mimeType || "audio/webm" })
      const id = crypto.randomUUID()
      const name = `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.webm`
      const file = new File([blob], name, { type: blob.type || "audio/webm" })
      setItems((current) => [
        ...current,
        {
          id,
          name,
          status: "transcribing",
          text: "",
          file,
        },
      ])
      setStatus("Recording stopped. Transcribing...")
      void transcribe(file, id, requestSession, epoch)
    })
    nextRecorder.start()
    setRecording(true)
    setStatus("Recording...")
  }

  function stopRecording() {
    if (recorder.current && recorder.current.state !== "inactive") {
      recorder.current.stop()
    }
    setRecording(false)
  }

  function deleteRecording(id: string) {
    setItems((current) => current.filter((item) => item.id !== id))
  }

  function retryRecording(item: RecordingItem) {
    setItems((current) =>
      current.map((candidate) =>
        candidate.id === item.id ? { ...candidate, status: "transcribing", error: undefined } : candidate,
      ),
    )
    void transcribe(item.file, item.id)
  }

  async function submitToAgent() {
    if (!auth || !session) return
    if (activeScreen === "wordpress") return
    if (items.some((item) => item.status === "transcribing")) {
      setStatus("Wait for all recordings to finish transcribing.")
      return
    }
    const pictureTranscripts = activeScreen === "media" ? combinedPictureTranscripts(session) : ""
    if (activeScreen !== "content" && !transcript.trim() && !pictureTranscripts) {
      setStatus("Add an instruction or describe at least one picture first.")
      return
    }
    if (activeScreen === "content" && !hasContentInstruction) {
      setStatus("Add an instruction or select an unused internal link first.")
      return
    }
    setSubmitting(true)
    setStatus(activeScreen === "content" ? "Regenerating content..." : "Updating facts...")
    try {
      if (activeScreen === "media") {
        let data = await saveSessionTranscript(auth, session, appendText(pictureTranscripts, transcript))
        onSessionChange(data.session)
        setStatus("Extracting facts...")
        data = await analyzeSessionInputs(auth, data.session)
        onSessionChange(data.session)
        onNavigateFacts()
        setStatus("Facts extracted. Review required fields.")
      } else if (activeScreen === "facts") {
        if (!selectedFactKeys.length) throw new Error("Select at least one fact for AI review.")
        let data = await saveSessionTranscript(auth, session, appendText(session.manual_text || "", transcript))
        onSessionChange(data.session)
        data = await analyzeSessionInputs(auth, data.session, selectedFactKeys)
        onSessionChange(data.session)
        setSyncedTranscript("")
        setItems([])
        setStatus("Facts updated.")
      } else if (activeScreen === "content") {
        const fieldIds = selectedContentFieldIds
        if (!fieldIds.length) throw new Error("Generate a draft before asking the content agent to revise it.")
        const job = await regenerateSessionDraft(
          auth,
          session,
          transcript,
          fieldIds,
          selectedContentLinks,
          contentAiAssistedLinkPlacement,
        )
        sessionStorage.setItem("speech2post_active_job", JSON.stringify({
          jobId: job.job_id,
          operation: "regenerate",
          sessionId: session.session_id,
          at: new Date().toISOString(),
        }))
        const nextSession = await waitForSessionJob(auth, job.job_id, {
          onConnectionIssue: () => setStatus("Connection interrupted. Regeneration continues; reconnecting..."),
          onConnectionRestored: () => setStatus("Connection restored. Regenerating selected fields..."),
        })
        sessionStorage.removeItem("speech2post_active_job")
        onSessionChange(nextSession)
        setSyncedTranscript("")
        setItems([])
        setStatus("Content regenerated.")
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent action failed.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed bottom-20 right-4 z-40 flex max-w-[calc(100vw-2rem)] flex-col items-end gap-2">
      {open && (
        <section className="w-[min(380px,calc(100vw-2rem))] rounded-lg border border-border bg-card p-3 shadow-xl">
          <div className="mb-3 flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-md bg-gold/15 text-gold">
                <Bot className="size-4" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-sm font-semibold text-foreground">{copy.title}</h2>
                <p className="text-xs text-muted-foreground">{copy.instruction}</p>
              </div>
            </div>
            <button
              id="s2p-recording-agent-close"
              type="button"
              onClick={() => onOpenChange(false)}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
              aria-label="Close agent widget"
            >
              x
            </button>
          </div>

          {activeScreen === "wordpress" ? (
            <p className="rounded-lg bg-muted px-3 py-4 text-sm text-muted-foreground">
              The agent is inactive on the WordPress screen.
            </p>
          ) : <>
          <div className="flex h-11 items-center justify-center gap-0.5 rounded-lg bg-muted px-3">
            {[6, 12, 20, 14, 26, 30, 18, 28, 10, 22, 30, 16, 24, 12, 20, 8, 18, 26, 14, 10].map((h, index) => (
              <span
                key={index}
                className={`w-1 rounded-full bg-gold/70 ${recording ? "animate-pulse" : ""}`}
                style={{ height: `${h}px` }}
                aria-hidden="true"
              />
            ))}
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              id="s2p-recording-agent-record"
              type="button"
              onClick={recording ? stopRecording : startRecording}
              disabled={!session}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:opacity-60"
            >
              {recording ? <Square className="size-4 text-destructive" /> : <Mic className="size-4 text-destructive" />}
              {recording ? "Stop" : "Record"}
            </button>
            <button
              id="s2p-recording-agent-submit"
              type="button"
              onClick={submitToAgent}
              disabled={submitting || !session || (activeScreen === "facts" && !selectedFactKeys.length) || (activeScreen === "content" && (!hasContentInstruction || !selectedContentFieldIds.length))}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-ai px-3 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
            >
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
              {copy.action}
            </button>
          </div>

          {activeScreen === "facts" && (
            <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-border bg-background px-3 py-2">
              <span className="text-xs text-muted-foreground">
                {selectedFactKeys.length} of {availableFactKeys.length} facts selected
              </span>
              <button
                id="s2p-recording-agent-toggle-all-facts"
                type="button"
                onClick={() => onSelectedFactKeysChange(allFactsSelected ? [] : null)}
                disabled={!availableFactKeys.length}
                className="shrink-0 rounded-md border border-border px-2.5 py-1.5 text-xs font-semibold text-foreground hover:bg-muted disabled:opacity-50"
              >
                {allFactsSelected ? "Uncheck all facts" : "Check all facts"}
              </button>
            </div>
          )}

          <textarea
            id="s2p-recording-agent-instruction"
            value={transcript}
            onChange={(event) => setSyncedTranscript(event.target.value)}
            rows={5}
            placeholder={copy.placeholder}
            className="mt-3 w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
          />

          {items.length > 0 && (
            <ul className="mt-3 space-y-2">
              {items.map((item) => (
                <li key={item.id} className="rounded-md border border-border bg-background px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium text-foreground">{item.name}</span>
                    <span className="inline-flex items-center gap-1 text-muted-foreground">
                      {item.status === "transcribing" && <Loader2 className="size-3 animate-spin" />}
                      {item.status}
                    </span>
                  </div>
                  {item.error && <p className="mt-1 text-destructive">{item.error}</p>}
                  <div className="mt-2 flex gap-2">
                    {item.status === "failed" && (
                      <button id={`s2p-recording-agent-retry-${item.id}`} type="button" onClick={() => retryRecording(item)} className="text-ai">
                        Retry
                      </button>
                    )}
                    <button id={`s2p-recording-agent-delete-${item.id}`} type="button" onClick={() => deleteRecording(item.id)} className="inline-flex items-center gap-1 text-destructive">
                      <Trash2 className="size-3" />
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {status && <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{status}</p>}
          </>}
        </section>
      )}

      <button
        id="s2p-recording-agent-toggle"
        type="button"
        onClick={() => onOpenChange(!open)}
        className="inline-flex h-14 items-center justify-center gap-2 rounded-full bg-gold px-5 text-sm font-bold text-gold-foreground shadow-xl ring-2 ring-background transition-transform hover:scale-105"
        aria-label="Open recording agent"
      >
        {recording ? <CircleDot className="size-5 animate-pulse text-destructive" /> : <Bot className="size-5" />}
        {open ? "Close agent" : "Ask agent"}
      </button>
    </div>
  )
}
