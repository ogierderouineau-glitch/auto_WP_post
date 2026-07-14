"use client"

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  Image as ImageIcon,
  ImagePlus,
  Loader2,
  RotateCcw,
  Save,
  Sparkles,
  Star,
  Trash2,
  UploadCloud,
  Video,
  X,
} from "lucide-react"
import type { ApiClientOptions } from "@/lib/api"
import { ApiError } from "@/lib/api"
import {
  imageUrl,
  loadContentSession,
  optimizeSessionImage,
  removeSessionImage,
  restoreSessionImageOriginal,
  saveSessionImageMetadata,
  saveSessionImageContextTranscript,
  sessionImages,
  setSessionFeaturedImage,
  uploadSessionImage,
  type ContentSession,
  type SelectedMediaContext,
  type SessionImage,
} from "@/lib/content-sessions"

type OperationState = "idle" | "loading" | "success" | "error"

type PendingImage = {
  id: string
  filename: string
  url: string
}

type MetadataForm = {
  image_alt: string
  image_title: string
  image_caption: string
  image_description: string
  image_usage: string
}

function metadataValue(metadata: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = metadata[key]
    if (value != null && String(value).trim()) return String(value)
  }
  return ""
}

function metadataFromImage(image: SessionImage | null): MetadataForm {
  const metadata = image?.metadata || {}
  return {
    image_alt: metadataValue(metadata, "image_alt", "alt_text"),
    image_title: metadataValue(metadata, "image_title", "title"),
    image_caption: metadataValue(metadata, "image_caption", "caption"),
    image_description: metadataValue(metadata, "image_description", "description", "image_description_wp"),
    image_usage: metadataValue(metadata, "image_usage") || (image?.is_featured ? "featured" : "gallery"),
  }
}

function ImagePreview({
  auth,
  session,
  filename,
  original,
  label,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  filename: string
  original?: boolean
  label: string
}) {
  const [url, setUrl] = useState("")
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!auth || !session || !filename) return
    const requestAuth = auth
    const requestSession = session
    let active = true
    let objectUrl = ""

    async function load() {
      setFailed(false)
      const response = await fetch(imageUrl(requestSession, filename, original), {
        headers: {
          "X-API-Key": requestAuth.apiKey,
          "X-User-ID": requestAuth.userId,
        },
      })
      if (!response.ok) throw new Error(`Image request failed: ${response.status}`)
      const blob = await response.blob()
      objectUrl = URL.createObjectURL(blob)
      if (active) setUrl(objectUrl)
      else URL.revokeObjectURL(objectUrl)
    }

    load().catch(() => {
      if (active) {
        setUrl("")
        setFailed(true)
      }
    })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [auth, filename, original, session])

  if (url) {
    return (
      <img
        src={url}
        alt={label}
        className="aspect-[4/3] w-full rounded-lg border border-border bg-muted object-contain"
      />
    )
  }

  return (
    <div className="flex aspect-[4/3] w-full items-center justify-center rounded-lg border border-border bg-muted">
      <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
        {failed ? <AlertTriangle className="size-7 text-destructive" /> : <ImageIcon className="size-7" />}
        <span className="text-xs font-medium">{failed ? "Could not load image" : label}</span>
      </div>
    </div>
  )
}

function ImageThumbnail({
  auth,
  session,
  filename,
  localUrl,
  label,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  filename: string
  localUrl?: string
  label: string
}) {
  const [url, setUrl] = useState(localUrl || "")

  useEffect(() => {
    if (localUrl) {
      setUrl(localUrl)
      return
    }
    if (!auth || !session || !filename) return
    const requestAuth = auth
    const requestSession = session
    let active = true
    let objectUrl = ""

    async function load() {
      const response = await fetch(imageUrl(requestSession, filename), {
        headers: {
          "X-API-Key": requestAuth.apiKey,
          "X-User-ID": requestAuth.userId,
        },
      })
      if (!response.ok) throw new Error(`Image request failed: ${response.status}`)
      const blob = await response.blob()
      objectUrl = URL.createObjectURL(blob)
      if (active) setUrl(objectUrl)
      else URL.revokeObjectURL(objectUrl)
    }

    setUrl("")
    load().catch(() => {
      if (active) setUrl("")
    })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [auth, filename, localUrl, session])

  return url ? (
    <img src={url} alt={label} className="h-full w-full rounded-[inherit] object-cover" />
  ) : (
    <ImageIcon className="size-5" aria-hidden="true" />
  )
}

function MetadataInput({
  label,
  value,
  rows,
  onChange,
}: {
  label: string
  value: string
  rows?: number
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</span>
      {rows ? (
        <textarea
          value={value}
          rows={rows}
          onChange={(event) => onChange(event.target.value)}
          className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
        />
      ) : (
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
        />
      )}
    </label>
  )
}

export function MediaScreen({
  auth,
  session,
  onSessionChange,
  pictureTranscript,
  onPictureTranscriptChange,
  onSelectedMediaChange,
  onOpenAgent,
  pictureTranscriptSavingImmediately,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  onSessionChange: (session: ContentSession) => void
  pictureTranscript: string
  onPictureTranscriptChange: (value: string) => void
  onSelectedMediaChange: (media: SelectedMediaContext | null) => void
  onOpenAgent: () => void
  pictureTranscriptSavingImmediately: boolean
}) {
  const images = useMemo(() => (session ? sessionImages(session) : []), [session])
  const [selectedMediaId, setSelectedMediaId] = useState("")
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([])
  const [metadata, setMetadata] = useState<MetadataForm>(() => metadataFromImage(null))
  const [useFocalPointVision, setUseFocalPointVision] = useState(true)
  const [useMetadataVision, setUseMetadataVision] = useState(false)
  const [operation, setOperation] = useState<OperationState>("idle")
  const [transcriptSaving, setTranscriptSaving] = useState(false)
  const [message, setMessage] = useState("")
  const [unsupportedVideo, setUnsupportedVideo] = useState("")
  const [mobilePreviewOriginal, setMobilePreviewOriginal] = useState(false)
  const [editPromptOpen, setEditPromptOpen] = useState(false)
  const [editPrompt, setEditPrompt] = useState("")
  const pendingTranscripts = useRef<Record<string, string>>({})
  const selectedMediaIdRef = useRef("")
  const sessionRef = useRef<ContentSession | null>(session)

  const selectedIndex = images.findIndex((image) => image.media_id === selectedMediaId)
  const selectedImage = selectedIndex >= 0 ? images[selectedIndex] : null
  const selectedPendingImage = pendingImages.find((image) => image.id === selectedMediaId) || null
  const selectedFilename = selectedImage?.processed_filename || selectedImage?.filename || ""
  const selectedOriginalFilename = selectedImage?.filename || ""

  useEffect(() => {
    setMobilePreviewOriginal(false)
  }, [selectedImage?.media_id])

  useEffect(() => {
    sessionRef.current = session
  }, [session])

  useEffect(() => {
    selectedMediaIdRef.current = selectedMediaId
  }, [selectedMediaId])

  useEffect(() => {
    if (!images.length && !pendingImages.length) {
      setSelectedMediaId("")
      return
    }
    if (
      !selectedMediaId ||
      (!images.some((image) => image.media_id === selectedMediaId) &&
        !pendingImages.some((image) => image.id === selectedMediaId))
    ) {
      if (pendingImages.length) {
        setSelectedMediaId(pendingImages[0].id)
        return
      }
      setSelectedMediaId(images[0].media_id)
    }
  }, [images, pendingImages, selectedMediaId])

  useEffect(() => {
    const nextMetadata = metadataFromImage(selectedImage)
    setMetadata(nextMetadata)
    setUseMetadataVision(selectedImage?.use_vision_for_metadata === true)
    onSelectedMediaChange(
      selectedImage
        ? {
            mediaId: selectedImage.media_id,
            filename: selectedFilename,
            displayName: selectedImage.filename,
          }
        : selectedPendingImage
          ? {
              mediaId: selectedPendingImage.id,
              filename: selectedPendingImage.filename,
              displayName: selectedPendingImage.filename,
            }
        : null,
    )
  }, [selectedImage?.media_id, selectedPendingImage?.id, session?.version])

  useEffect(() => {
    if (!auth || !session || !selectedImage || !selectedOriginalFilename || operation === "loading" || pictureTranscriptSavingImmediately) return
    const savedTranscript = selectedImage.context_transcript || ""
    if (pictureTranscript === savedTranscript) return

    let cancelled = false
    const timeout = window.setTimeout(() => {
      setTranscriptSaving(true)
      saveSessionImageContextTranscript(auth, session, selectedOriginalFilename, pictureTranscript)
        .then((data) => {
          if (!cancelled) {
            sessionRef.current = data.session
            onSessionChange(data.session)
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setOperation("error")
            setMessage(error instanceof Error ? error.message : "Picture transcript autosave failed.")
          }
        })
        .finally(() => {
          if (!cancelled) setTranscriptSaving(false)
        })
    }, 800)

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
    }
  }, [auth, onSessionChange, operation, pictureTranscript, pictureTranscriptSavingImmediately, selectedOriginalFilename, selectedImage?.media_id, session])

  useEffect(() => {
    if (!selectedPendingImage) return
    pendingTranscripts.current[selectedPendingImage.id] = pictureTranscript
  }, [pictureTranscript, selectedPendingImage?.id])

  async function runAction(action: (currentSession: ContentSession) => Promise<ContentSession>, success: string) {
    const currentSession = sessionRef.current
    if (!auth || !currentSession) return
    const requestAuth = auth

    async function preserveSelectedTranscript(nextSession: ContentSession) {
      if (!selectedOriginalFilename) return nextSession
      const savedTranscript = nextSession.image_context_transcripts?.[selectedMediaIdRef.current] || ""
      if (pictureTranscript === savedTranscript) return nextSession
      const data = await saveSessionImageContextTranscript(
        requestAuth,
        nextSession,
        selectedOriginalFilename,
        pictureTranscript,
      )
      return data.session
    }

    setOperation("loading")
    setMessage("")
    try {
      let nextSession: ContentSession
      try {
        nextSession = await action(await preserveSelectedTranscript(currentSession))
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error
        const latest = await loadContentSession(requestAuth, currentSession.session_id)
        sessionRef.current = latest.session
        onSessionChange(latest.session)
        nextSession = await action(await preserveSelectedTranscript(latest.session))
      }
      onSessionChange(nextSession)
      sessionRef.current = nextSession
      setOperation("success")
      setMessage(success)
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Media action failed.")
    }
  }

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    if (!auth || !session) return
    const files = [...(event.target.files || [])]
    event.target.value = ""
    const imageFiles = files.filter((file) => file.type.startsWith("image/"))
    const videoFiles = files.filter((file) => file.type.startsWith("video/"))
    if (videoFiles.length) {
      setUnsupportedVideo("Video upload is visible in the interface but not supported by the current V2 endpoint.")
    }
    if (!imageFiles.length) return

    const pending = imageFiles.map((file) => ({
      id: `pending-${crypto.randomUUID()}`,
      filename: file.name,
      url: URL.createObjectURL(file),
    }))
    setPendingImages((current) => [...current, ...pending])
    setSelectedMediaId(pending[0].id)
    setOperation("loading")
    setMessage("Uploading selected pictures...")

    try {
      let nextSession = session
      for (const [index, file] of imageFiles.entries()) {
        const pendingImage = pending[index]
        const transcript = pendingTranscripts.current[pendingImage.id] || ""
        const beforeIds = new Set(nextSession.image_refs.map((image) => image.media_id))
        const data = await uploadSessionImage(auth, nextSession, file, useFocalPointVision)
        nextSession = data.session
        const uploadedImage = sessionImages(nextSession).find((image) => !beforeIds.has(image.media_id))
        const currentImages = sessionImages(nextSession)
        if (!currentImages.some((image) => image.is_featured) && currentImages[0]) {
          const featuredData = await setSessionFeaturedImage(
            auth,
            nextSession,
            currentImages[0].processed_filename || currentImages[0].filename,
          )
          nextSession = featuredData.session
        }
        if (uploadedImage && transcript.trim()) {
          const transcriptData = await saveSessionImageContextTranscript(
            auth,
            nextSession,
            uploadedImage.processed_filename || uploadedImage.filename,
            transcript,
          )
          nextSession = transcriptData.session
        }
        if (uploadedImage && selectedMediaIdRef.current === pendingImage.id) setSelectedMediaId(uploadedImage.media_id)
        delete pendingTranscripts.current[pendingImage.id]
      }
      onSessionChange(nextSession)
      setOperation("success")
      setMessage(`${imageFiles.length} image(s) uploaded.`)
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Image upload failed.")
    } finally {
      setPendingImages((current) => current.filter((image) => !pending.some((candidate) => candidate.id === image.id)))
      pending.forEach((image) => URL.revokeObjectURL(image.url))
    }
  }

  function selectOffset(offset: number) {
    const mediaIds = [...pendingImages.map((image) => image.id), ...images.map((image) => image.media_id)]
    if (!mediaIds.length) return
    const currentIndex = Math.max(0, mediaIds.indexOf(selectedMediaId))
    const nextIndex = (currentIndex + offset + mediaIds.length) % mediaIds.length
    setSelectedMediaId(mediaIds[nextIndex])
  }

  function savePictureData() {
    if (!auth || !session || !selectedImage) return
    void runAction(async (currentSession) => {
      const metadataData = await saveSessionImageMetadata(
        auth,
        currentSession,
        selectedOriginalFilename,
        { ...metadata },
        useMetadataVision,
      )
      return metadataData.session
    }, "Picture data saved.")
  }

  function changeMetadataVision(enabled: boolean) {
    setUseMetadataVision(enabled)
    if (!auth || !session || !selectedImage) return
    void runAction(async (currentSession) => {
      const data = await saveSessionImageMetadata(
        auth,
        currentSession,
        selectedOriginalFilename,
        { ...metadata },
        enabled,
      )
      return data.session
    }, enabled ? "Metadata Vision enabled." : "Metadata Vision disabled.")
  }

  function setFeatured() {
    if (!auth || !session || !selectedImage) return
    void runAction(async (currentSession) => {
      const data = await setSessionFeaturedImage(auth, currentSession, selectedOriginalFilename)
      return data.session
    }, "Featured image saved.")
  }

  function optimizeImage() {
    if (!auth || !session || !selectedImage) return
    setEditPrompt("")
    setEditPromptOpen(true)
  }

  function submitImageOptimization() {
    if (!auth || !session || !selectedImage || !editPrompt.trim()) return
    const prompt = editPrompt.trim()
    setEditPromptOpen(false)
    void runAction(async (currentSession) => {
      const data = await optimizeSessionImage(auth, currentSession, selectedOriginalFilename, prompt)
      return data.session
    }, "Image edit requested.")
  }

  function restoreOriginal() {
    if (!auth || !session || !selectedImage) return
    void runAction(async (currentSession) => {
      const data = await restoreSessionImageOriginal(auth, currentSession, selectedOriginalFilename)
      return data.session
    }, "Original restored.")
  }

  function removeImage() {
    if (!auth || !session || !selectedImage) return
    void runAction(async (currentSession) => {
      const data = await removeSessionImage(auth, currentSession, selectedOriginalFilename)
      return data.session
    }, "Image removed.")
  }

  const statusItems = [
    {
      label: operation === "loading" || transcriptSaving ? "Media operation running" : "Media ready",
      state: operation === "loading" || transcriptSaving ? "active" : "done",
    },
    {
      label: `${images.length} image(s) in this session`,
      state: "done",
    },
  ] as const

  return (
    <>
      {editPromptOpen && selectedImage && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/45 px-4">
          <section className="w-full max-w-lg rounded-lg border border-border bg-card p-4 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-foreground">Edit image with AI</h2>
                <p className="mt-1 text-xs text-muted-foreground">{selectedImage.filename}</p>
              </div>
              <button
                type="button"
                onClick={() => setEditPromptOpen(false)}
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                aria-label="Close image edit dialog"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </div>
            <textarea
              value={editPrompt}
              onChange={(event) => setEditPrompt(event.target.value)}
              rows={5}
              autoFocus
              className="mt-4 w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditPromptOpen(false)}
                className="inline-flex items-center justify-center rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitImageOptimization}
                disabled={!editPrompt.trim() || operation === "loading"}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-ai px-3.5 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
              >
                <Sparkles className="size-4" aria-hidden="true" />
                Apply edit
              </button>
            </div>
          </section>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)_320px]">
        <section aria-label="Media library" className="min-w-0">
          <label className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border bg-card px-3 py-3 text-left text-sm transition-colors hover:border-gold hover:bg-gold/5">
            <input type="file" multiple accept="image/*,video/*" onChange={uploadFiles} className="sr-only" />
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-gold/15 text-gold">
              <ImagePlus className="size-5" aria-hidden="true" />
            </span>
            <span>
              <span className="block font-medium text-foreground">Add pictures</span>
              <span className="block text-xs text-muted-foreground">Videos are not supported yet</span>
            </span>
          </label>
          <button
            type="button"
            onClick={onOpenAgent}
            className="mt-2 flex w-full items-center gap-2 rounded-lg border border-dashed border-ai/50 bg-ai/10 px-3 py-3 text-left text-sm transition-colors hover:border-ai hover:bg-ai/15"
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-ai text-ai-foreground">
              <Bot className="size-5" aria-hidden="true" />
            </span>
            <span>
              <span className="block font-medium text-ai">Tell your story</span>
              <span className="block text-xs text-muted-foreground">
                Speak to the agent and/or write some text in the Picture transcript directly
              </span>
            </span>
          </button>
          <label className="mt-2 flex cursor-pointer items-start gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={useFocalPointVision}
              onChange={(event) => setUseFocalPointVision(event.target.checked)}
              disabled={operation === "loading"}
              className="mt-0.5 size-4 accent-gold"
            />
            <span>
              <span className="block font-medium text-foreground">Find focal points with Vision</span>
              Applied to newly uploaded pictures.
            </span>
          </label>

          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={() => selectOffset(-1)}
              disabled={!images.length && !pendingImages.length}
              className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50 lg:size-8"
              aria-label="Previous media"
            >
              <ChevronLeft className="size-4" aria-hidden="true" />
            </button>

            <div className="flex flex-1 gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
              {pendingImages.length || images.length ? (
                <>
                  {pendingImages.map((image, index) => {
                    const active = image.id === selectedMediaId
                    return (
                      <button
                        key={image.id}
                        type="button"
                        onClick={() => setSelectedMediaId(image.id)}
                        className={[
                          "group relative flex aspect-square w-16 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted text-muted-foreground transition-all lg:aspect-[4/3] lg:w-full",
                          active ? "border-gold ring-2 ring-gold/40" : "border-border hover:border-foreground/30",
                        ].join(" ")}
                        aria-label={image.filename}
                        aria-current={active ? "true" : undefined}
                      >
                        <ImageThumbnail auth={null} session={null} filename="" localUrl={image.url} label={image.filename} />
                        <span className="absolute left-1 top-1 rounded bg-topbar/80 px-1 text-[10px] font-medium text-topbar-foreground">
                          {index + 1}
                        </span>
                        <span className="absolute bottom-1 right-1 rounded bg-warn/90 px-1 text-[10px] font-medium text-warn-foreground">
                          Uploading
                        </span>
                      </button>
                    )
                  })}
                  {images.map((image, index) => {
                    const active = image.media_id === selectedImage?.media_id
                    return (
                      <button
                        key={image.media_id}
                        type="button"
                        onClick={() => setSelectedMediaId(image.media_id)}
                        className={[
                          "group relative flex aspect-square w-16 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted text-muted-foreground transition-all lg:aspect-[4/3] lg:w-full",
                          active ? "border-gold ring-2 ring-gold/40" : "border-border hover:border-foreground/30",
                        ].join(" ")}
                        aria-label={image.filename}
                        aria-current={active ? "true" : undefined}
                      >
                        <ImageThumbnail
                          auth={auth}
                          session={session}
                          filename={image.processed_filename || image.filename}
                          label={image.filename}
                        />
                        <span className="absolute left-1 top-1 rounded bg-topbar/80 px-1 text-[10px] font-medium text-topbar-foreground">
                          {pendingImages.length + index + 1}
                        </span>
                        {image.is_featured && (
                          <span
                            className="absolute right-1 top-1 flex size-5 items-center justify-center rounded-full bg-gold text-gold-foreground shadow"
                            title="Featured image"
                          >
                            <Star className="size-3 fill-current" aria-hidden="true" />
                          </span>
                        )}
                      </button>
                    )
                  })}
                </>
              ) : (
                <div className="rounded-md border border-border bg-card px-3 py-6 text-center text-xs text-muted-foreground">
                  No images yet
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={() => selectOffset(1)}
              disabled={!images.length && !pendingImages.length}
              className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50 lg:size-8"
              aria-label="Next media"
            >
              <ChevronRight className="size-4" aria-hidden="true" />
            </button>
          </div>

          {unsupportedVideo && (
            <div className="mt-3 flex gap-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn-foreground">
              <Video className="size-4 shrink-0" aria-hidden="true" />
              {unsupportedVideo}
            </div>
          )}
        </section>

        <section aria-label="Image workspace" className="min-w-0">
          <div className="rounded-xl border border-border bg-card p-3 sm:p-4">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="truncate text-sm font-semibold">
                {selectedImage
                  ? `${selectedImage.filename} - image ${selectedIndex + 1}`
                  : selectedPendingImage
                    ? `${selectedPendingImage.filename} - uploading`
                    : "No image selected"}
              </h2>
              {operation === "loading" ? (
                <span className="inline-flex items-center gap-1.5 rounded-md bg-warn/20 px-2 py-1 text-xs font-medium text-warn-foreground">
                  <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                  Uploading
                </span>
              ) : selectedImage?.processed_filename ? (
                <span className="inline-flex items-center gap-1.5 rounded-md bg-confirm/15 px-2 py-1 text-xs font-medium text-confirm">
                  <Check className="size-3.5" aria-hidden="true" />
                  Processed
                </span>
              ) : null}
            </div>

            {selectedPendingImage ? (
              <img
                src={selectedPendingImage.url}
                alt={selectedPendingImage.filename}
                className="aspect-[4/3] w-full rounded-lg border border-border bg-muted object-contain"
              />
            ) : selectedImage && session ? (
              <>
                <div className="hidden gap-3 lg:grid lg:grid-cols-2">
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">Original</p>
                    <ImagePreview auth={auth} session={session} filename={selectedImage.filename} original label="Original" />
                  </div>
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">Processed</p>
                    <ImagePreview auth={auth} session={session} filename={selectedFilename} label="Processed" />
                  </div>
                </div>

                <div className="lg:hidden">
                  {selectedImage.processed_filename ? (
                    <div className="mb-2 flex items-center gap-2" aria-label="Choose image version">
                      <button
                        type="button"
                        onClick={() => setMobilePreviewOriginal(false)}
                        className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                          mobilePreviewOriginal ? "bg-muted text-muted-foreground" : "bg-confirm/15 text-confirm ring-1 ring-confirm/30"
                        }`}
                      >
                        Processed
                      </button>
                      <button
                        type="button"
                        onClick={() => setMobilePreviewOriginal(true)}
                        className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                          mobilePreviewOriginal ? "bg-gold/15 text-foreground ring-1 ring-gold/40" : "bg-muted text-muted-foreground"
                        }`}
                      >
                        Original
                      </button>
                    </div>
                  ) : (
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">Original · no processed version</p>
                  )}
                  <ImagePreview
                    auth={auth}
                    session={session}
                    filename={mobilePreviewOriginal ? selectedImage.filename : selectedFilename}
                    original={mobilePreviewOriginal}
                    label={mobilePreviewOriginal ? "Original" : selectedImage.processed_filename ? "Processed" : "Original"}
                  />
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={setFeatured}
                    disabled={operation === "loading"}
                    className="inline-flex items-center gap-2 rounded-md bg-confirm px-3.5 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:opacity-60"
                  >
                    <Star className="size-4" aria-hidden="true" />
                    Featured
                  </button>
                  <button
                    type="button"
                    onClick={optimizeImage}
                    disabled={operation === "loading" || !selectedImage.processed_filename}
                    className="inline-flex items-center gap-2 rounded-md bg-ai px-3.5 py-2.5 text-sm font-semibold text-ai-foreground transition-colors hover:opacity-90 disabled:opacity-60"
                  >
                    <Sparkles className="size-4" aria-hidden="true" />
                    Edit with AI
                  </button>
                  <button
                    type="button"
                    onClick={restoreOriginal}
                    disabled={operation === "loading" || !selectedImage.processed_filename}
                    className="inline-flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3.5 py-2.5 text-sm font-semibold text-destructive transition-colors hover:bg-destructive/15 disabled:opacity-60"
                  >
                    <RotateCcw className="size-4" aria-hidden="true" />
                    Restore original
                  </button>
                  <button
                    type="button"
                    onClick={removeImage}
                    disabled={operation === "loading"}
                    className="inline-flex items-center gap-2 rounded-md border border-destructive/40 bg-card px-3.5 py-2.5 text-sm font-semibold text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-60"
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                    Remove
                  </button>
                </div>
              </>
            ) : (
              <div className="flex aspect-[4/3] w-full items-center justify-center rounded-lg border border-dashed border-border bg-muted">
                <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                  <ImageIcon className="size-7" aria-hidden="true" />
                  <span className="text-xs font-medium">Upload an image to begin</span>
                </div>
              </div>
            )}
          </div>
        </section>

        <section aria-label="Voice description and image metadata" className="min-w-0 lg:contents">
          <div className="space-y-4 lg:col-start-3 lg:row-span-2 lg:row-start-1">
          <div className="rounded-xl border border-border bg-card p-3 sm:p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="flex size-8 items-center justify-center rounded-md bg-gold/15 text-gold">
                <FileText className="size-4" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">Picture transcript</h2>
                {transcriptSaving && <p className="text-xs text-muted-foreground">Saving...</p>}
              </div>
            </div>
            <textarea
              value={pictureTranscript}
              onChange={(event) => {
                if (selectedPendingImage) pendingTranscripts.current[selectedPendingImage.id] = event.target.value
                onPictureTranscriptChange(event.target.value)
              }}
              rows={10}
              disabled={!selectedImage && !selectedPendingImage}
              placeholder={
                selectedImage || selectedPendingImage
                  ? "Record with the floating mic or type notes for this picture."
                  : "Select an image to add picture notes."
              }
              className="w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40 disabled:text-muted-foreground"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              The floating mic saves these notes per picture and sends all picture transcripts to fact extraction.
            </p>
          </div>

          <aside aria-label="Processing status" className="rounded-xl border border-border bg-card p-4">
            <h2 className="mb-3 text-sm font-semibold">Status</h2>
            <ul className="space-y-2.5">
              {statusItems.map((status) => (
                <li key={status.label} className="flex items-center gap-2.5 text-sm">
                  {status.state === "done" ? (
                    <span className="flex size-5 items-center justify-center rounded-full bg-confirm/15 text-confirm">
                      <Check className="size-3.5" aria-hidden="true" />
                    </span>
                  ) : (
                    <span className="flex size-5 items-center justify-center rounded-full bg-warn/20 text-warn-foreground">
                      <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                    </span>
                  )}
                  <span className={status.state === "done" ? "text-muted-foreground" : "text-foreground"}>
                    {status.label}
                  </span>
                </li>
              ))}
            </ul>
            {message && (
              <div
                className={[
                  "mt-4 rounded-lg px-3 py-2 text-xs",
                  operation === "error" ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground",
                ].join(" ")}
              >
                {message}
              </div>
            )}
            <div className="mt-4 flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
              <UploadCloud className="size-4" aria-hidden="true" />
              Backend session version {session?.version ?? "-"}
            </div>
          </aside>
          </div>

          <div className="mt-4 self-start rounded-xl border border-border bg-card p-4 lg:col-start-2 lg:row-start-2 lg:mt-0">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
              Image metadata - Will be generated with the content draft
            </h2>
            {selectedImage ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex cursor-pointer items-start gap-2 sm:col-span-2">
                  <input
                    type="checkbox"
                    checked={useMetadataVision}
                    onChange={(event) => changeMetadataVision(event.target.checked)}
                    disabled={operation === "loading"}
                    className="mt-0.5 size-4 accent-gold"
                  />
                  <span>
                    <span className="block text-xs font-medium text-foreground">Improve metadata with Vision</span>
                    <span className="block text-xs text-muted-foreground">
                      Uses visual details from this picture in addition to its transcript and rules.
                    </span>
                  </span>
                </label>
                <MetadataInput
                  label="Alt text"
                  value={metadata.image_alt}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_alt: value }))}
                />
                <MetadataInput
                  label="Title"
                  value={metadata.image_title}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_title: value }))}
                />
                <MetadataInput
                  label="Caption"
                  value={metadata.image_caption}
                  rows={2}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_caption: value }))}
                />
                <MetadataInput
                  label="Description"
                  value={metadata.image_description}
                  rows={2}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_description: value }))}
                />
                <button
                  type="button"
                  onClick={savePictureData}
                  disabled={operation === "loading" || transcriptSaving}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-confirm px-3.5 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:opacity-60 sm:col-span-2"
                >
                  <Save className="size-4" aria-hidden="true" />
                  Save picture data
                </button>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No image selected.</p>
            )}
          </div>
        </section>
      </div>
    </>
  )
}
