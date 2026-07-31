"use client"

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronLeft,
  ChevronRight,
  Crop,
  FileText,
  Image as ImageIcon,
  ImagePlus,
  Loader2,
  RotateCcw,
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
  recropSessionImageWithAi,
  removeSessionImage,
  removeSessionVideo,
  restoreSessionImageOriginal,
  saveSessionImageMetadata,
  saveSessionImageContextTranscript,
  saveSessionVideoMetadata,
  sessionImages,
  sessionVideos,
  setSessionFeaturedImage,
  uploadSessionImage,
  uploadSessionVideo,
  videoUrl,
  type ContentSession,
  type SelectedMediaContext,
  type SessionImage,
} from "@/lib/content-sessions"
import { statusMessageClass } from "@/lib/status-style"

type OperationState = "idle" | "loading" | "success" | "error"

type PendingMedia = {
  id: string
  filename: string
  url: string
  kind: "image" | "video"
}

function cropSkipWarning(image: SessionImage | null | undefined) {
  return image?.operations.find((operation) =>
    operation.toLowerCase().includes("crop.aspect_ratio skipped"),
  ) || ""
}

type MetadataForm = {
  image_alt: string
  image_title: string
  image_caption: string
  image_description: string
  image_usage: string
  visible_taxonomy_terms: Record<string, string[]>
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
  const visibleTaxonomies = metadata.visible_taxonomy_terms
  return {
    image_alt: metadataValue(metadata, "image_alt", "alt_text"),
    image_title: metadataValue(metadata, "image_title", "title"),
    image_caption: metadataValue(metadata, "image_caption", "caption"),
    image_description: metadataValue(metadata, "image_description", "description", "image_description_wp"),
    image_usage: metadataValue(metadata, "image_usage") || (image?.is_featured ? "featured" : "gallery"),
    visible_taxonomy_terms: (
      visibleTaxonomies && typeof visibleTaxonomies === "object" && !Array.isArray(visibleTaxonomies)
        ? Object.fromEntries(
            Object.entries(visibleTaxonomies as Record<string, unknown>)
              .map(([taxonomy, terms]) => [
                taxonomy,
                Array.isArray(terms) ? terms.map(String) : [],
              ]),
          )
        : {}
    ),
  }
}

function metadataFormsEqual(left: MetadataForm, right: MetadataForm) {
  return JSON.stringify(left) === JSON.stringify(right)
}

function taxonomyCandidatesFromSession(session: ContentSession | null) {
  const taxonomies = session?.wordpress_payload?.taxonomies
  const enabled = new Set(
    Array.isArray(session?.wordpress_payload?.media_taxonomies)
      ? session.wordpress_payload.media_taxonomies.map(String)
      : [],
  )
  if (!taxonomies || typeof taxonomies !== "object" || Array.isArray(taxonomies)) return {}
  const candidates: Record<string, string[]> = {}
  for (const [taxonomy, terms] of Object.entries(taxonomies as Record<string, unknown>)) {
    const values = Array.isArray(terms) ? terms.map(String) : []
    if (enabled.has(taxonomy) && values.length) candidates[taxonomy] = values
  }
  return candidates
}

function isSessionVersionConflict(error: unknown) {
  if (!(error instanceof ApiError) || error.status !== 409) return false
  if (/changed from version/i.test(error.message)) return true
  const payload = error.payload as { error_code?: unknown; detail?: { error_code?: unknown } | unknown } | null
  const code = typeof payload?.error_code === "string"
    ? payload.error_code
    : (typeof payload?.detail === "object" && payload?.detail && "error_code" in payload.detail && typeof (payload.detail as { error_code?: unknown }).error_code === "string")
      ? (payload.detail as { error_code: string }).error_code
      : ""
  return code === "session_version_conflict"
}

function waitForMs(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function metadataFieldTrace(
  session: ContentSession | null,
  mediaId: string | undefined,
  ...fieldKeys: string[]
) {
  if (!session || !mediaId) return null
  const metadataTrace = session.generation_trace?.image_metadata as
    | Record<string, {
        fields?: Record<string, unknown>
        instructions?: Record<string, unknown>[]
        vision_used?: boolean
      }>
    | undefined
  const imageTrace = metadataTrace?.[mediaId]
  const fields = imageTrace?.fields
  for (const key of fieldKeys) {
    const trace = fields?.[key]
    if (trace && typeof trace === "object" && !Array.isArray(trace)) {
      return {
        ...(trace as Record<string, unknown>),
        instructions: imageTrace?.instructions || [],
        vision_used: imageTrace?.vision_used === true,
      }
    }
  }
  return null
}

function ImagePreview({
  auth,
  session,
  filename,
  original,
  label,
  revision = "",
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  filename: string
  original?: boolean
  label: string
  revision?: string
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
      // A session update can replace this preview immediately after React has
      // mounted the <img>. Give the browser time to consume the old blob URL
      // before releasing it, otherwise it can fail with ERR_FILE_NOT_FOUND.
      if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    }
  }, [auth?.apiKey, auth?.userId, filename, original, revision, session?.session_id])

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
  revision = "",
  mediaKind = "image",
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  filename: string
  localUrl?: string
  label: string
  revision?: string
  mediaKind?: "image" | "video"
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
      const response = await fetch(
        mediaKind === "video"
          ? videoUrl(requestSession, filename)
          : imageUrl(requestSession, filename),
        {
        headers: {
          "X-API-Key": requestAuth.apiKey,
        },
        },
      )
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
      if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    }
  }, [auth?.apiKey, auth?.userId, filename, localUrl, mediaKind, revision, session?.session_id])

  return url ? (
    <img src={url} alt={label} className="h-full w-full rounded-[inherit] object-cover" />
  ) : (
    <ImageIcon className="size-5" aria-hidden="true" />
  )
}

function VideoPreview({
  auth,
  session,
  filename,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  filename: string
}) {
  const [url, setUrl] = useState("")
  useEffect(() => {
    if (!auth || !session || !filename) return
    let active = true
    let objectUrl = ""
    fetch(videoUrl(session, filename), {
      headers: { "X-API-Key": auth.apiKey },
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Video request failed: ${response.status}`)
        return response.blob()
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        if (active) setUrl(objectUrl)
      })
      .catch(() => {
        if (active) setUrl("")
      })
    return () => {
      active = false
      if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
    }
  }, [auth, filename, session?.session_id, session?.version])
  return url ? (
    <video src={url} controls preload="metadata" className="aspect-video w-full rounded-lg border border-border bg-black object-contain" />
  ) : (
    <div className="flex aspect-video items-center justify-center rounded-lg border border-border bg-muted">
      <Video className="size-9 text-muted-foreground" aria-hidden="true" />
    </div>
  )
}

function MetadataInput({
  label,
  value,
  rows,
  trace,
  onChange,
  onBlur,
}: {
  label: string
  value: string
  rows?: number
  trace?: Record<string, unknown> | null
  onChange: (value: string) => void
  onBlur?: () => void
}) {
  const [traceOpen, setTraceOpen] = useState(false)
  return (
    <div className="block">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <button
          id={`s2p-media-metadata-trace-${label.toLowerCase().replaceAll(" ", "-")}`}
          type="button"
          onClick={() => setTraceOpen((open) => !open)}
          disabled={!trace}
          aria-expanded={traceOpen}
          className="rounded-full border border-border px-2 py-0.5 text-[10px] font-semibold text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
        >
          Rules trace
        </button>
      </div>
      {rows ? (
        <textarea
          id={`s2p-media-metadata-${label.toLowerCase().replaceAll(" ", "-")}`}
          value={value}
          rows={rows}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
        />
      ) : (
        <input
          id={`s2p-media-metadata-${label.toLowerCase().replaceAll(" ", "-")}`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-gold/40"
        />
      )}
      {traceOpen && trace && (
        <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-border bg-background p-3 text-xs leading-relaxed text-muted-foreground">
          {JSON.stringify(trace, null, 2)}
        </pre>
      )}
    </div>
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
  onExtractFacts,
  extractFactsLoading,
  pictureTranscriptSavingImmediately,
}: {
  auth: ApiClientOptions | null
  session: ContentSession | null
  onSessionChange: (session: ContentSession) => void
  pictureTranscript: string
  onPictureTranscriptChange: (value: string) => void
  onSelectedMediaChange: (media: SelectedMediaContext | null) => void
  onOpenAgent: () => void
  onExtractFacts: () => void
  extractFactsLoading: boolean
  pictureTranscriptSavingImmediately: boolean
}) {
  const images = useMemo(() => (session ? sessionImages(session) : []), [session])
  const videos = useMemo(() => (session ? sessionVideos(session) : []), [session])
  const [selectedMediaId, setSelectedMediaId] = useState("")
  const [pendingImages, setPendingImages] = useState<PendingMedia[]>([])
  const [metadata, setMetadata] = useState<MetadataForm>(() => metadataFromImage(null))
  const [videoMetadata, setVideoMetadata] = useState({
    video_title: "",
    video_caption: "",
    video_description: "",
  })
  const [uploadAspectRatio, setUploadAspectRatio] = useState("4:5")
  const [useMetadataVision, setUseMetadataVision] = useState(false)
  const [operation, setOperation] = useState<OperationState>("idle")
  const [transcriptSaving, setTranscriptSaving] = useState(false)
  const [message, setMessage] = useState("")
  const [mobilePreviewOriginal, setMobilePreviewOriginal] = useState(false)
  const [editPromptOpen, setEditPromptOpen] = useState(false)
  const [editPrompt, setEditPrompt] = useState("")
  const pendingTranscripts = useRef<Record<string, string>>({})
  const selectedMediaIdRef = useRef("")
  const sessionRef = useRef<ContentSession | null>(session)
  const transcriptSaveTimerRef = useRef<number | null>(null)
  const transcriptSavePromiseRef = useRef<Promise<void> | null>(null)

  const selectedIndex = images.findIndex((image) => image.media_id === selectedMediaId)
  const selectedImage = selectedIndex >= 0 ? images[selectedIndex] : null
  const selectedVideo = videos.find((video) => video.media_id === selectedMediaId) || null
  const selectedPendingImage = pendingImages.find((image) => image.id === selectedMediaId) || null
  const selectedFilename = selectedImage?.processed_filename || selectedImage?.filename || ""
  const selectedOriginalFilename = selectedImage?.filename || ""
  const taxonomyCandidates = taxonomyCandidatesFromSession(session)

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
    if (!images.length && !videos.length && !pendingImages.length) {
      setSelectedMediaId("")
      return
    }
    if (
      !selectedMediaId ||
      (!images.some((image) => image.media_id === selectedMediaId) &&
        !videos.some((video) => video.media_id === selectedMediaId) &&
        !pendingImages.some((image) => image.id === selectedMediaId))
    ) {
      if (pendingImages.length) {
        setSelectedMediaId(pendingImages[0].id)
        return
      }
      setSelectedMediaId((images.find((image) => image.is_featured) || images[0] || videos[0]).media_id)
    }
  }, [images, videos, pendingImages, selectedMediaId])

  useEffect(() => {
    const nextMetadata = metadataFromImage(selectedImage)
    setMetadata((current) => metadataFormsEqual(current, nextMetadata) ? current : nextMetadata)
    setUseMetadataVision(selectedImage?.use_vision_for_metadata === true)
  }, [selectedImage?.media_id, selectedImage?.metadata, selectedImage?.is_featured, selectedImage?.use_vision_for_metadata])

  useEffect(() => {
    setVideoMetadata({
      video_title: String(selectedVideo?.metadata.video_title || ""),
      video_caption: String(selectedVideo?.metadata.video_caption || ""),
      video_description: String(selectedVideo?.metadata.video_description || ""),
    })
  }, [selectedVideo?.media_id, selectedVideo?.metadata])

  useEffect(() => {
    onSelectedMediaChange(
      selectedImage
        ? {
            mediaId: selectedImage.media_id,
            filename: selectedFilename,
            displayName: selectedImage.filename,
            kind: "image",
          }
        : selectedVideo
          ? {
              mediaId: selectedVideo.media_id,
              filename: selectedVideo.filename,
              displayName: selectedVideo.filename,
              kind: "video",
            }
        : selectedPendingImage
          ? {
              mediaId: selectedPendingImage.id,
              filename: selectedPendingImage.filename,
              displayName: selectedPendingImage.filename,
              kind: selectedPendingImage.kind,
            }
        : null,
    )
  }, [selectedFilename, selectedImage?.filename, selectedImage?.media_id, selectedPendingImage?.filename, selectedPendingImage?.id, selectedPendingImage?.kind, selectedVideo?.filename, selectedVideo?.media_id])

  useEffect(() => {
    if (!auth || !session || !selectedImage || !selectedOriginalFilename || pictureTranscriptSavingImmediately || transcriptSaving) return
    const transcriptToSave = pictureTranscript.trim()
    const savedTranscript = (selectedImage.context_transcript || "").trim()
    if (transcriptToSave === savedTranscript) return

    let cancelled = false
    const timeout = window.setTimeout(() => {
      transcriptSaveTimerRef.current = null
      setTranscriptSaving(true)
      const saveTranscript = async () => {
        let requestSession = session
        for (let attempt = 0; attempt < 5 && !cancelled; attempt += 1) {
          try {
            const data = await saveSessionImageContextTranscript(
              auth,
              requestSession,
              selectedOriginalFilename,
              transcriptToSave,
            )
            if (cancelled) return
            sessionRef.current = data.session
            onSessionChange(data.session)
            return
          } catch (error) {
            if (cancelled) return
            if (!isSessionVersionConflict(error) || attempt === 4) {
              setOperation("error")
              setMessage(error instanceof Error ? error.message : "Picture transcript autosave failed.")
              return
            }

            try {
              const latest = await loadContentSession(auth, requestSession.session_id)
              if (cancelled) return
              sessionRef.current = latest.session
              onSessionChange(latest.session)
              requestSession = latest.session
              await waitForMs(250 * (attempt + 1))
            } catch (reloadError) {
              if (cancelled) return
              setOperation("error")
              setMessage(reloadError instanceof Error ? reloadError.message : "Picture transcript autosave failed.")
              return
            }
          }
        }
      }

      const promise = saveTranscript()
        .finally(() => {
          if (transcriptSavePromiseRef.current === promise) {
            transcriptSavePromiseRef.current = null
            setTranscriptSaving(false)
          }
        })
      transcriptSavePromiseRef.current = promise
    }, 800)
    transcriptSaveTimerRef.current = timeout

    return () => {
      cancelled = true
      window.clearTimeout(timeout)
      if (transcriptSaveTimerRef.current === timeout) transcriptSaveTimerRef.current = null
    }
  }, [auth, onSessionChange, pictureTranscript, pictureTranscriptSavingImmediately, selectedOriginalFilename, selectedImage?.media_id, session])

  useEffect(() => {
    if (!auth || !session || !selectedVideo || pictureTranscriptSavingImmediately || transcriptSaving) return
    if (pictureTranscript.trim() === selectedVideo.context_transcript.trim()) return
    const timeout = window.setTimeout(() => {
      setTranscriptSaving(true)
      saveSessionVideoMetadata(auth, session, selectedVideo.filename, videoMetadata, pictureTranscript.trim())
        .then((data) => {
          sessionRef.current = data.session
          onSessionChange(data.session)
        })
        .catch((error) => {
          setOperation("error")
          setMessage(error instanceof Error ? error.message : "Video transcript autosave failed.")
        })
        .finally(() => setTranscriptSaving(false))
    }, 800)
    return () => window.clearTimeout(timeout)
  }, [auth, onSessionChange, pictureTranscript, pictureTranscriptSavingImmediately, selectedVideo?.media_id, session])

  useEffect(() => {
    if (!selectedPendingImage) return
    pendingTranscripts.current[selectedPendingImage.id] = pictureTranscript
  }, [pictureTranscript, selectedPendingImage?.id])

  async function runAction(action: (currentSession: ContentSession) => Promise<ContentSession>, success: string) {
    if (!auth || !sessionRef.current) return
    const requestAuth = auth

    async function preserveSelectedTranscript(nextSession: ContentSession) {
      if (!selectedOriginalFilename) return nextSession
      const transcriptToSave = pictureTranscript.trim()
      const savedTranscript = (nextSession.image_context_transcripts?.[selectedMediaIdRef.current] || "").trim()
      if (transcriptToSave === savedTranscript) return nextSession
      const data = await saveSessionImageContextTranscript(
        requestAuth,
        nextSession,
        selectedOriginalFilename,
        transcriptToSave,
      )
      return data.session
    }

    setOperation("loading")
    setMessage("")
    try {
      if (transcriptSaveTimerRef.current !== null) {
        window.clearTimeout(transcriptSaveTimerRef.current)
        transcriptSaveTimerRef.current = null
      }
      await transcriptSavePromiseRef.current
      const currentSession = sessionRef.current
      if (!currentSession) return
      let requestSession = currentSession
      let nextSession: ContentSession | null = null
      for (let attempt = 0; attempt < 5; attempt += 1) {
        try {
          nextSession = await action(await preserveSelectedTranscript(requestSession))
          break
        } catch (error) {
          if (!isSessionVersionConflict(error) || attempt === 4) throw error
          const latest = await loadContentSession(requestAuth, requestSession.session_id)
          sessionRef.current = latest.session
          onSessionChange(latest.session)
          requestSession = latest.session
          await waitForMs(250 * (attempt + 1))
        }
      }
      if (!nextSession) throw new Error("Media action retry loop exited unexpectedly.")
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
    const requestAuth = auth
    const files = [...(event.target.files || [])]
    event.target.value = ""
    const mediaFiles = files.filter(
      (file) => file.type.startsWith("image/") || file.type === "video/mp4" || file.name.toLowerCase().endsWith(".mp4"),
    )
    if (!mediaFiles.length) return

    const pending = mediaFiles.map((file) => ({
      id: `pending-${crypto.randomUUID()}`,
      filename: file.name,
      url: URL.createObjectURL(file),
      kind: file.type.startsWith("image/") ? "image" as const : "video" as const,
    }))
    setPendingImages((current) => [...current, ...pending])
    setSelectedMediaId(pending[0].id)
    setOperation("loading")
    setMessage("Uploading selected pictures and videos...")
    const completedPendingIds = new Set<string>()

    try {
      let nextSession = sessionRef.current || session

      async function reloadLatestSession(currentSession: ContentSession) {
        const latest = await loadContentSession(requestAuth, currentSession.session_id)
        sessionRef.current = latest.session
        onSessionChange(latest.session)
        return latest.session
      }

      async function withConflictRetry<T>(
        currentSession: ContentSession,
        action: (requestSession: ContentSession) => Promise<T>,
      ) {
        let requestSession = currentSession
        for (let attempt = 0; attempt < 5; attempt += 1) {
          try {
            return await action(requestSession)
          } catch (error) {
            if (!isSessionVersionConflict(error) || attempt === 4) throw error
            requestSession = await reloadLatestSession(requestSession)
            await waitForMs(250 * (attempt + 1))
          }
        }
        throw new Error("Upload retry loop exited unexpectedly.")
      }

      for (const [index, file] of mediaFiles.entries()) {
        const pendingImage = pending[index]
        const isVideo = pendingImage.kind === "video"
        let beforeIds = new Set(
          (isVideo ? (sessionRef.current || nextSession).video_refs : (sessionRef.current || nextSession).image_refs)
            .map((media) => media.media_id),
        )
        const data = await withConflictRetry(sessionRef.current || nextSession, async (requestSession) => {
          beforeIds = new Set(
            (isVideo ? requestSession.video_refs : requestSession.image_refs).map((media) => media.media_id),
          )
          return isVideo
            ? uploadSessionVideo(requestAuth, requestSession, file)
            : uploadSessionImage(requestAuth, requestSession, file, false, uploadAspectRatio)
        })
        nextSession = data.session
        sessionRef.current = nextSession
        // Read this after the upload so notes recorded while it was processing
        // are included in the newly created backend image record.
        const transcript = pendingTranscripts.current[pendingImage.id] || ""
        const uploadedImage = isVideo
          ? sessionVideos(nextSession).find((video) => !beforeIds.has(video.media_id))
          : sessionImages(nextSession).find((image) => !beforeIds.has(image.media_id))
        const currentImages = sessionImages(nextSession)
        if (uploadedImage) {
          completedPendingIds.add(pendingImage.id)
          if (selectedMediaIdRef.current === pendingImage.id) {
            selectedMediaIdRef.current = uploadedImage.media_id
            setSelectedMediaId(uploadedImage.media_id)
          }
          setPendingImages((current) => current.filter((image) => image.id !== pendingImage.id))
          window.setTimeout(() => URL.revokeObjectURL(pendingImage.url), 1000)
        }
        // Publish the backend image in the same React update as removing its
        // optimistic preview, so the gallery never renders both copies.
        onSessionChange(nextSession)
        if (!isVideo && !currentImages.some((image) => image.is_featured) && currentImages[0]) {
          const featuredData = await withConflictRetry(nextSession, (requestSession) =>
            setSessionFeaturedImage(
              requestAuth,
              requestSession,
              currentImages[0].processed_filename || currentImages[0].filename,
            ),
          )
          nextSession = featuredData.session
          sessionRef.current = nextSession
          onSessionChange(nextSession)
        }
        if (uploadedImage && transcript.trim() && isVideo) {
          const video = sessionVideos(nextSession).find((item) => item.media_id === uploadedImage.media_id)
          if (video) {
            const transcriptData = await withConflictRetry(nextSession, (requestSession) =>
              saveSessionVideoMetadata(requestAuth, requestSession, video.filename, video.metadata, transcript),
            )
            nextSession = transcriptData.session
            sessionRef.current = nextSession
            onSessionChange(nextSession)
          }
        } else if (uploadedImage && transcript.trim()) {
          const image = sessionImages(nextSession).find((item) => item.media_id === uploadedImage.media_id)
          if (!image) continue
          const transcriptData = await withConflictRetry(nextSession, (requestSession) =>
            saveSessionImageContextTranscript(
              requestAuth,
              requestSession,
              image.processed_filename || image.filename,
              transcript,
            ),
          )
          nextSession = transcriptData.session
          sessionRef.current = nextSession
          onSessionChange(nextSession)
        }
        delete pendingTranscripts.current[pendingImage.id]
      }
      setOperation("success")
      setMessage(`${mediaFiles.length} media file(s) uploaded and processed.`)
    } catch (error) {
      setOperation("error")
      setMessage(error instanceof Error ? error.message : "Media upload failed.")
    } finally {
      setPendingImages((current) => current.filter((image) => !pending.some((candidate) => candidate.id === image.id)))
      pending
        .filter((image) => !completedPendingIds.has(image.id))
        .forEach((image) => URL.revokeObjectURL(image.url))
    }
  }

  function selectOffset(offset: number) {
    const mediaIds = [
      ...pendingImages.map((image) => image.id),
      ...images.map((image) => image.media_id),
      ...videos.map((video) => video.media_id),
    ]
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

  function toggleVisibleTaxonomyTerm(taxonomy: string, term: string, checked: boolean) {
    if (!auth || !session || !selectedImage) return
    const currentTerms = metadata.visible_taxonomy_terms[taxonomy] || []
    const nextTerms = checked
      ? Array.from(new Set([...currentTerms, term]))
      : currentTerms.filter((candidate) => candidate !== term)
    const nextMetadata = {
      ...metadata,
      visible_taxonomy_terms: {
        ...metadata.visible_taxonomy_terms,
        [taxonomy]: nextTerms,
      },
    }
    setMetadata(nextMetadata)
    void runAction(async (currentSession) => {
      const metadataData = await saveSessionImageMetadata(
        auth,
        currentSession,
        selectedOriginalFilename,
        nextMetadata,
        useMetadataVision,
      )
      return metadataData.session
    }, "Picture taxonomy selection saved.")
  }

  function saveVideoData() {
    if (!auth || !session || !selectedVideo) return
    void runAction(async (currentSession) => {
      const data = await saveSessionVideoMetadata(
        auth,
        currentSession,
        selectedVideo.filename,
        videoMetadata,
        pictureTranscript,
      )
      return data.session
    }, "Video data saved.")
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

  function recropWithAi() {
    if (!auth || !session || !selectedImage) return
    void runAction(async (currentSession) => {
      setMessage("Analyzing the original image and finding a new focal point...")
      const data = await recropSessionImageWithAi(auth, currentSession, selectedOriginalFilename)
      return data.session
    }, "Original image reanalyzed and recropped around the AI focal point.")
  }

  function submitImageOptimization() {
    if (!auth || !session || !selectedImage || !editPrompt.trim()) return
    const prompt = editPrompt.trim()
    setEditPromptOpen(false)
    void runAction(async (currentSession) => {
      setMessage("Optimizing image with OpenAI...")
      const data = await optimizeSessionImage(auth, currentSession, selectedOriginalFilename, prompt)
      return data.session
    }, "Image optimized.")
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

  function removeVideo() {
    if (!auth || !session || !selectedVideo) return
    void runAction(async (currentSession) => {
      const data = await removeSessionVideo(auth, currentSession, selectedVideo.filename)
      return data.session
    }, "Video removed.")
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
                id="s2p-media-edit-dialog-close"
                type="button"
                onClick={() => setEditPromptOpen(false)}
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                aria-label="Close image edit dialog"
              >
                <X className="size-4" aria-hidden="true" />
              </button>
            </div>
            <textarea
              id="s2p-media-edit-prompt"
              value={editPrompt}
              onChange={(event) => setEditPrompt(event.target.value)}
              rows={5}
              autoFocus
              className="mt-4 w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                id="s2p-media-edit-cancel"
                type="button"
                onClick={() => setEditPromptOpen(false)}
                className="inline-flex items-center justify-center rounded-md border border-border bg-card px-3.5 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
              >
                Cancel
              </button>
              <button
                id="s2p-media-edit-apply"
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
      <div className="grid gap-4 lg:grid-cols-[200px_minmax(0,1fr)_320px] lg:grid-rows-[auto_1fr]">
        <section aria-label="Media library" className="min-w-0 lg:row-span-2">
          <div className="overflow-hidden rounded-lg border border-dashed border-gold/50 bg-gold/10 text-foreground transition-colors hover:border-gold hover:bg-gold/15">
            <label className="flex w-full cursor-pointer items-center gap-2 px-3 py-3 text-left text-sm">
              <input id="s2p-media-upload" type="file" multiple accept="image/*,video/mp4,.mp4" onChange={uploadFiles} className="sr-only" />
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-gold text-gold-foreground">
                <ImagePlus className="size-5" aria-hidden="true" />
              </span>
              <span>
                <span className="block font-semibold text-gold">Add pictures &amp; videos</span>
                <span className="block text-xs text-muted-foreground">Pictures and MP4 videos</span>
              </span>
            </label>
            <div className="flex border-t border-gold/20 px-3 py-2.5 text-xs">
              <select
                id="s2p-media-upload-aspect-ratio"
                aria-label="Picture format"
                value={uploadAspectRatio}
                onChange={(event) => setUploadAspectRatio(event.target.value)}
                disabled={operation === "loading"}
                className="w-full rounded-md border border-gold/30 bg-background px-2.5 py-1.5 font-semibold text-foreground outline-none focus:ring-2 focus:ring-gold/40 disabled:opacity-60"
              >
                <option value="4:5">Portrait 4:5 (e.g. 768 × 960)</option>
                <option value="4:3">Landscape 4:3</option>
                <option value="1:1">Square 1:1</option>
                <option value="16:9">Widescreen 16:9</option>
              </select>
            </div>
          </div>
          <button
            id="s2p-media-open-agent"
            type="button"
            onClick={onOpenAgent}
            className="mt-2 flex cursor-pointer w-full items-center gap-2 rounded-lg border border-dashed border-ai/50 bg-ai/10 px-3 py-3 text-left text-sm transition-colors hover:border-ai hover:bg-ai/15"
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
          <button
            id="s2p-media-extract-facts"
            type="button"
            onClick={onExtractFacts}
            disabled={!session || extractFactsLoading}
            className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-confirm px-3 py-2.5 text-sm font-semibold text-confirm-foreground transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {extractFactsLoading ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <FileText className="size-4" aria-hidden="true" />}
            {extractFactsLoading ? "Extracting facts..." : "Extract facts"}
          </button>

          <div className="mt-3 flex items-center gap-2">
            <button
              id="s2p-media-previous"
              type="button"
              onClick={() => selectOffset(-1)}
              disabled={!images.length && !videos.length && !pendingImages.length}
              className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50 lg:size-8"
              aria-label="Previous media"
            >
              <ChevronLeft className="size-4" aria-hidden="true" />
            </button>

            <div className="flex flex-1 gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
              {pendingImages.length || images.length || videos.length ? (
                <>
                  {pendingImages.map((image, index) => {
                    const active = image.id === selectedMediaId
                    return (
                      <button
                        id={`s2p-media-pending-${image.id}`}
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
                        {image.kind === "video"
                          ? <Video className="size-7" aria-hidden="true" />
                          : <ImageThumbnail auth={null} session={null} filename="" localUrl={image.url} label={image.filename} />}
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
                    const cropWarning = cropSkipWarning(image)
                    return (
                      <button
                        id={`s2p-media-select-${image.media_id}`}
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
                          revision={`${image.processed_revision || ""}|${image.operations.join("|")}`}
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
                        {cropWarning && (
                          <span
                            className="absolute bottom-1 right-1 flex size-5 items-center justify-center rounded-full bg-warn text-warn-foreground shadow"
                            title="The requested aspect ratio could not be applied safely. Recrop with AI is recommended."
                            aria-label="Crop warning"
                          >
                            <AlertTriangle className="size-3" aria-hidden="true" />
                          </span>
                        )}
                      </button>
                    )
                  })}
                  {videos.map((video, index) => {
                    const active = video.media_id === selectedVideo?.media_id
                    return (
                      <button
                        id={`s2p-media-select-${video.media_id}`}
                        key={video.media_id}
                        type="button"
                        onClick={() => setSelectedMediaId(video.media_id)}
                        className={[
                          "group relative flex aspect-square w-16 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted text-muted-foreground transition-all lg:aspect-[4/3] lg:w-full",
                          active ? "border-gold ring-2 ring-gold/40" : "border-border hover:border-foreground/30",
                        ].join(" ")}
                        aria-label={video.filename}
                        aria-current={active ? "true" : undefined}
                      >
                        {video.poster_filename
                          ? <ImageThumbnail
                              auth={auth}
                              session={session}
                              filename={video.poster_filename}
                              label={video.filename}
                              revision={video.processed_revision}
                              mediaKind="video"
                            />
                          : <Video className="size-7" aria-hidden="true" />}
                        <span className="absolute left-1 top-1 rounded bg-topbar/80 px-1 text-[10px] font-medium text-topbar-foreground">
                          {pendingImages.length + images.length + index + 1}
                        </span>
                        <span className="absolute bottom-1 right-1 flex size-6 items-center justify-center rounded-full bg-ai text-ai-foreground shadow" title="Video">
                          <Video className="size-3.5" aria-hidden="true" />
                        </span>
                      </button>
                    )
                  })}
                </>
              ) : (
                <div className="rounded-md border border-border bg-card px-3 py-6 text-center text-xs text-muted-foreground">
                  No media yet
                </div>
              )}
            </div>

            <button
              id="s2p-media-next"
              type="button"
              onClick={() => selectOffset(1)}
              disabled={!images.length && !videos.length && !pendingImages.length}
              className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50 lg:size-8"
              aria-label="Next media"
            >
              <ChevronRight className="size-4" aria-hidden="true" />
            </button>
          </div>

        </section>

        <section aria-label="Image workspace" className="min-w-0">
          <div className="rounded-xl border border-border bg-card p-3 sm:p-4">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-semibold">
                  {selectedImage
                    ? `${selectedImage.filename} - image ${selectedIndex + 1}`
                    : selectedVideo
                      ? `${selectedVideo.filename} - video ${videos.findIndex((video) => video.media_id === selectedVideo.media_id) + 1}`
                    : selectedPendingImage
                      ? `${selectedPendingImage.filename} - uploading`
                      : "No image selected"}
                </h2>
                {selectedImage && (
                  <button
                    id="s2p-media-set-featured"
                    type="button"
                    onClick={setFeatured}
                    disabled={operation === "loading" || selectedImage.is_featured}
                    aria-pressed={selectedImage.is_featured}
                    title={selectedImage.is_featured ? "This is the featured image" : "Set as featured image"}
                    className={`mt-1 inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-semibold transition-colors disabled:cursor-default ${
                      selectedImage.is_featured
                        ? "bg-gold/20 text-gold ring-1 ring-gold/40"
                        : "text-muted-foreground hover:bg-gold/10 hover:text-gold"
                    }`}
                  >
                    <Star className={`size-3.5 ${selectedImage.is_featured ? "fill-current" : ""}`} aria-hidden="true" />
                    Featured
                  </button>
                )}
              </div>
              {operation === "loading" ? (
                <span className="inline-flex items-center gap-1.5 rounded-md bg-warn/20 px-2 py-1 text-xs font-medium text-warn-foreground">
                  <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                  Processing
                </span>
              ) : selectedImage?.processed_filename ? (
                <span className="inline-flex items-center gap-1.5 rounded-md bg-confirm/15 px-2 py-1 text-xs font-medium text-confirm">
                  <Check className="size-3.5" aria-hidden="true" />
                  Processed
                </span>
              ) : null}
            </div>

            {selectedPendingImage ? (
              selectedPendingImage.kind === "video" ? (
                <video src={selectedPendingImage.url} controls className="aspect-video w-full rounded-lg border border-border bg-black object-contain" />
              ) : (
                <img
                  src={selectedPendingImage.url}
                  alt={selectedPendingImage.filename}
                  className="aspect-[4/3] w-full rounded-lg border border-border bg-muted object-contain"
                />
              )
            ) : selectedVideo && session ? (
              <>
                <VideoPreview auth={auth} session={session} filename={selectedVideo.filename} />
                <div className="mt-4 flex justify-end border-t border-destructive/20 pt-3">
                  <button
                    id="s2p-media-remove-video"
                    type="button"
                    onClick={removeVideo}
                    disabled={operation === "loading"}
                    className="inline-flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3.5 py-2.5 text-sm font-semibold text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-60"
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                    Remove video
                  </button>
                </div>
              </>
            ) : selectedImage && session ? (
              <>
                <div className="hidden gap-3 lg:grid lg:grid-cols-2">
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">Original</p>
                    <ImagePreview auth={auth} session={session} filename={selectedImage.filename} original label="Original" />
                  </div>
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">Processed</p>
                    <ImagePreview
                      auth={auth}
                      session={session}
                      filename={selectedFilename}
                      label="Processed"
                      revision={`${selectedImage.processed_revision || ""}|${selectedImage.operations.join("|")}`}
                    />
                  </div>
                </div>

                <div className="lg:hidden">
                  {selectedImage.processed_filename ? (
                    <div className="mb-2 flex items-center gap-2" aria-label="Choose image version">
                      <button
                        id="s2p-media-preview-processed"
                        type="button"
                        onClick={() => setMobilePreviewOriginal(false)}
                        className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                          mobilePreviewOriginal ? "bg-muted text-muted-foreground" : "bg-confirm/15 text-confirm ring-1 ring-confirm/30"
                        }`}
                      >
                        Processed
                      </button>
                      <button
                        id="s2p-media-preview-original"
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
                    revision={mobilePreviewOriginal ? "" : `${selectedImage.processed_revision || ""}|${selectedImage.operations.join("|")}`}
                  />
                </div>

                {cropSkipWarning(selectedImage) && (
                  <div className="mt-4 flex flex-col gap-3 rounded-lg border border-warn/50 bg-warn/10 p-3 sm:flex-row sm:items-center">
                    <AlertTriangle className="size-5 shrink-0 text-warn-foreground" aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-foreground">
                        The requested crop could not be applied safely
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                        {cropSkipWarning(selectedImage)}. Use Recrop with AI to identify the important subject and retry the crop with a focal point.
                      </p>
                    </div>
                    <button
                      id="s2p-media-crop-warning-recrop"
                      type="button"
                      onClick={recropWithAi}
                      disabled={operation === "loading" || !selectedImage.processed_filename}
                      className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md border border-gold/40 bg-gold/15 px-3 py-2 text-sm font-semibold text-gold transition-colors hover:bg-gold/25 disabled:opacity-60"
                    >
                      <Crop className="size-4" aria-hidden="true" />
                      Recrop with AI ($)
                    </button>
                  </div>
                )}

                <div className="mt-4 space-y-3">
                  <div className="rounded-lg border border-border bg-muted/30 p-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Edit picture</p>
                    <div className="flex flex-wrap gap-2">
                      <button
                        id="s2p-media-recrop-with-ai"
                        type="button"
                        onClick={recropWithAi}
                        disabled={operation === "loading" || !selectedImage.processed_filename}
                        title="Analyze the immutable original upload with AI Vision, then replace the processed image with a fresh focal-point crop."
                        className="inline-flex items-center gap-2 rounded-md border border-gold/40 bg-gold/15 px-3.5 py-2.5 text-sm font-semibold text-gold transition-colors hover:bg-gold/25 disabled:opacity-60"
                      >
                        <Crop className="size-4" aria-hidden="true" />
                        Recrop with AI ($)
                      </button>
                      <button
                        id="s2p-media-edit-with-ai"
                        type="button"
                        onClick={optimizeImage}
                        disabled={operation === "loading" || !selectedImage.processed_filename}
                        className="inline-flex items-center gap-2 rounded-md bg-ai px-3.5 py-2.5 text-sm font-semibold text-ai-foreground shadow-sm transition hover:brightness-105 disabled:opacity-60"
                      >
                        <Sparkles className="size-4" aria-hidden="true" />
                        Edit with AI ($)
                      </button>
                    </div>
                  </div>
                  <div className="flex flex-wrap justify-end gap-2 border-t border-destructive/20 pt-3">
                    <button
                      id="s2p-media-restore-original"
                      type="button"
                      onClick={restoreOriginal}
                      disabled={operation === "loading" || !selectedImage.processed_filename}
                      className="inline-flex items-center gap-2 rounded-md border border-destructive/35 bg-destructive/5 px-3.5 py-2.5 text-sm font-semibold text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-60"
                    >
                      <RotateCcw className="size-4" aria-hidden="true" />
                      Restore original
                    </button>
                    <button
                      id="s2p-media-remove"
                      type="button"
                      onClick={removeImage}
                      disabled={operation === "loading"}
                      className="inline-flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3.5 py-2.5 text-sm font-semibold text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-60"
                    >
                      <Trash2 className="size-4" aria-hidden="true" />
                      Remove picture
                    </button>
                  </div>
                </div>
              </>
            ) : (
              <div className="flex aspect-[4/3] w-full items-center justify-center rounded-lg border border-dashed border-border bg-muted">
                <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                  <ImageIcon className="size-7" aria-hidden="true" />
                  <span className="text-xs font-medium">Upload a picture or MP4 video to begin</span>
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
                <h2 className="text-sm font-semibold">{selectedVideo ? "Video transcript" : "Picture transcript"}</h2>
                {transcriptSaving && <p className="text-xs text-muted-foreground">Saving...</p>}
              </div>
            </div>
            <textarea
              id="s2p-media-picture-transcript"
              value={pictureTranscript}
              onChange={(event) => {
                if (selectedPendingImage) pendingTranscripts.current[selectedPendingImage.id] = event.target.value
                onPictureTranscriptChange(event.target.value)
              }}
              rows={10}
              disabled={!selectedImage && !selectedVideo && !selectedPendingImage}
              placeholder={
                selectedImage || selectedVideo || selectedPendingImage
                  ? `Record with the floating mic or type notes for this ${selectedVideo || selectedPendingImage?.kind === "video" ? "video" : "picture"}.`
                  : "Select media to add notes."
              }
              className="w-full resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-gold/40 disabled:text-muted-foreground"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              The floating mic saves these notes per media item for fact extraction.
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
                  statusMessageClass(operation, message),
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
              {selectedVideo ? "Video metadata" : "Image metadata - Will be generated with the content draft"}
            </h2>
            {selectedVideo ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <MetadataInput
                  label="Title"
                  value={videoMetadata.video_title}
                  onChange={(value) => setVideoMetadata((current) => ({ ...current, video_title: value }))}
                  onBlur={saveVideoData}
                />
                <MetadataInput
                  label="Caption"
                  value={videoMetadata.video_caption}
                  rows={2}
                  onChange={(value) => setVideoMetadata((current) => ({ ...current, video_caption: value }))}
                  onBlur={saveVideoData}
                />
                <div className="sm:col-span-2">
                  <MetadataInput
                    label="Description"
                    value={videoMetadata.video_description}
                    rows={2}
                    onChange={(value) => setVideoMetadata((current) => ({ ...current, video_description: value }))}
                    onBlur={saveVideoData}
                  />
                </div>
              </div>
            ) : selectedImage ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="flex cursor-pointer items-start gap-2 sm:col-span-2">
                  <input
                    id="s2p-media-use-metadata-vision"
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
                {Object.keys(taxonomyCandidates).length ? (
                  <details className="group rounded-lg border border-border p-3 sm:col-span-2">
                    <summary className="cursor-pointer select-none text-xs font-medium text-foreground">
                      Visible taxonomy terms
                      <span className="ml-2 text-muted-foreground group-open:hidden">Show</span>
                      <span className="ml-2 text-muted-foreground hidden group-open:inline">Hide</span>
                    </summary>
                    <div className="mt-3 space-y-3">
                      <p className="text-xs text-muted-foreground">
                        Only checked subjects will be assigned to this WordPress attachment.
                      </p>
                      {Object.entries(taxonomyCandidates).map(([taxonomy, terms]) => (
                        <fieldset key={taxonomy} className="space-y-1.5">
                          <legend className="text-xs font-semibold capitalize">{taxonomy}</legend>
                          <div className="grid gap-1.5 sm:grid-cols-2">
                            {terms.map((term) => (
                              <label key={term} className="flex cursor-pointer items-start gap-2 text-xs">
                                <input
                                  type="checkbox"
                                  checked={(metadata.visible_taxonomy_terms[taxonomy] || []).includes(term)}
                                  onChange={(event) =>
                                    toggleVisibleTaxonomyTerm(taxonomy, term, event.target.checked)
                                  }
                                  disabled={operation === "loading"}
                                  className="mt-0.5 size-4 accent-gold"
                                />
                                <span>{term}</span>
                              </label>
                            ))}
                          </div>
                        </fieldset>
                      ))}
                    </div>
                  </details>
                ) : null}
                <MetadataInput
                  label="Alt text"
                  value={metadata.image_alt}
                  trace={metadataFieldTrace(session, selectedImage.media_id, "image_alt")}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_alt: value }))}
                  onBlur={savePictureData}
                />
                <MetadataInput
                  label="Title"
                  value={metadata.image_title}
                  trace={metadataFieldTrace(session, selectedImage.media_id, "image_title")}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_title: value }))}
                  onBlur={savePictureData}
                />
                <MetadataInput
                  label="Caption"
                  value={metadata.image_caption}
                  rows={2}
                  trace={metadataFieldTrace(session, selectedImage.media_id, "image_caption")}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_caption: value }))}
                  onBlur={savePictureData}
                />
                <MetadataInput
                  label="Description"
                  value={metadata.image_description}
                  rows={2}
                  trace={metadataFieldTrace(session, selectedImage.media_id, "image_description", "image_description_wp")}
                  onChange={(value) => setMetadata((current) => ({ ...current, image_description: value }))}
                  onBlur={savePictureData}
                />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No media selected.</p>
            )}
          </div>
        </section>
      </div>
    </>
  )
}
