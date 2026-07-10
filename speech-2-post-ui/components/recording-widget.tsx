"use client"

import { useEffect, useRef, useState } from "react"
import { Bot, CircleDot, Loader2, Mic, Send, Square, Trash2 } from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import {
  analyzeSessionInputs,
  saveSessionImageContextTranscript,
  saveSessionTranscript,
  transcribeSessionRecording,
  type ContentSession,
  type SelectedMediaContext,
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

const SCREEN_COPY: Record<ActiveScreen, { title: string; instruction: string; action: string }> = {
  media: {
    title: "Media agent",
    instruction: "Describe the event through the selected images. Include concrete facts: place, date, people, service, atmosphere, highlights and challenges.",
    action: "Extract facts",
  },
  facts: {
    title: "Facts agent",
    instruction: "Explain which facts should be corrected or completed. Be specific and name the fields when possible.",
    action: "Update facts",
  },
  content: {
    title: "Content agent",
    instruction: "Describe what should change in the generated content. Mention exact fields or sections when you can.",
    action: "Regenerate content",
  },
  wordpress: {
    title: "WordPress agent",
    instruction: "Review publishing notes before sending content to WordPress. Agent actions for this screen are not connected yet.",
    action: "Not connected",
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
  selectedMedia,
  pictureTranscript,
  onPictureTranscriptChange,
  onSessionChange,
  onNavigateFacts,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  activeScreen: ActiveScreen
  selectedMedia: SelectedMediaContext | null
  pictureTranscript: string
  onPictureTranscriptChange: (value: string) => void
  onSessionChange: (session: ContentSession) => void
  onNavigateFacts: () => void
}) {
  const [open, setOpen] = useState(false)
  const [recording, setRecording] = useState(false)
  const [items, setItems] = useState<RecordingItem[]>([])
  const [transcript, setTranscript] = useState("")
  const [status, setStatus] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const chunks = useRef<Blob[]>([])
  const transcriptRef = useRef("")
  const copy = SCREEN_COPY[activeScreen]
  const selectedMediaId = selectedMedia?.mediaId || ""

  function setSyncedTranscript(value: string) {
    transcriptRef.current = value
    setTranscript(value)
  }

  useEffect(() => {
    if (activeScreen !== "media" || !session || !selectedMediaId) return
    if (selectedMediaId.startsWith("pending-")) {
      setSyncedTranscript(pictureTranscript)
      setItems([])
      setStatus(selectedMedia ? `Ready for ${selectedMedia.displayName}.` : "")
      return
    }
    const nextTranscript = String((session.image_context_transcripts || {})[selectedMediaId] || "")
    setSyncedTranscript(nextTranscript)
    onPictureTranscriptChange(nextTranscript)
    setItems([])
    setStatus(selectedMedia ? `Ready for ${selectedMedia.displayName}.` : "")
  }, [activeScreen, selectedMediaId, session?.version])

  useEffect(() => {
    if (activeScreen === "media" && transcript !== pictureTranscript) {
      setSyncedTranscript(pictureTranscript)
    }
  }, [activeScreen, pictureTranscript])

  async function transcribe(file: File, id: string) {
    if (!auth || !session) return
    try {
      const data = await transcribeSessionRecording(auth, session, file)
      const text = data.text || ""
      setItems((current) =>
        current.map((item) => (item.id === id ? { ...item, status: "done", text } : item)),
      )
      const nextTranscript = appendText(transcriptRef.current, text)
      setSyncedTranscript(nextTranscript)
      if (activeScreen === "media") onPictureTranscriptChange(nextTranscript)
      setStatus("Recording transcribed.")
    } catch (error) {
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
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setStatus("Recording is not supported by this browser.")
      return
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    chunks.current = []
    const nextRecorder = new MediaRecorder(stream)
    recorder.current = nextRecorder
    nextRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.current.push(event.data)
    })
    nextRecorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop())
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
      void transcribe(file, id)
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
    if (!transcript.trim()) {
      setStatus("Transcript is empty.")
      return
    }
    setSubmitting(true)
    setStatus("Saving transcript...")
    try {
      let currentSession = session
      if (activeScreen === "media" && selectedMedia && !selectedMedia.mediaId.startsWith("pending-")) {
        const savedImage = await saveSessionImageContextTranscript(
          auth,
          currentSession,
          selectedMedia.filename,
          transcript,
        )
        currentSession = savedImage.session
        onSessionChange(currentSession)
      }
      const transcriptForAnalysis =
        activeScreen === "media"
          ? combinedPictureTranscripts(currentSession) || transcript
          : transcript
      let data = await saveSessionTranscript(auth, currentSession, transcriptForAnalysis)
      onSessionChange(data.session)
      if (activeScreen === "media") {
        setStatus("Extracting facts...")
        data = await analyzeSessionInputs(auth, data.session)
        onSessionChange(data.session)
        onNavigateFacts()
        setStatus("Facts extracted. Review required fields.")
      } else {
        setStatus("Transcript saved. Screen-specific agent action is coming in a later phase.")
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent action failed.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed bottom-4 right-4 z-30 flex max-w-[calc(100vw-2rem)] flex-col items-end gap-2">
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
              type="button"
              onClick={() => setOpen(false)}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
              aria-label="Close agent widget"
            >
              x
            </button>
          </div>

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
              type="button"
              onClick={recording ? stopRecording : startRecording}
              disabled={!session}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-border bg-card px-3 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:opacity-60"
            >
              {recording ? <Square className="size-4 text-destructive" /> : <Mic className="size-4 text-destructive" />}
              {recording ? "Stop" : "Record"}
            </button>
            <button
              type="button"
              onClick={submitToAgent}
              disabled={submitting || !session}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-ai px-3 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
            >
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
              {copy.action}
            </button>
          </div>

          <textarea
            value={transcript}
            onChange={(event) => {
              setSyncedTranscript(event.target.value)
              if (activeScreen === "media") onPictureTranscriptChange(event.target.value)
            }}
            rows={5}
            placeholder="Transcribed recordings will appear here. You can edit before sending."
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
                      <button type="button" onClick={() => retryRecording(item)} className="text-ai">
                        Retry
                      </button>
                    )}
                    <button type="button" onClick={() => deleteRecording(item.id)} className="inline-flex items-center gap-1 text-destructive">
                      <Trash2 className="size-3" />
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {status && <p className="mt-3 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{status}</p>}
        </section>
      )}

      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex size-12 items-center justify-center rounded-full bg-gold text-gold-foreground shadow-lg transition-transform hover:scale-105"
        aria-label="Open recording agent"
      >
        {recording ? <CircleDot className="size-5 animate-pulse text-destructive" /> : <Mic className="size-5" />}
      </button>
    </div>
  )
}
