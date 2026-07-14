"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Check,
  FilePlus2,
  Mic,
  Wifi,
  Image as ImageIcon,
  FileText,
  Newspaper,
  Wrench,
  SlidersHorizontal,
} from "lucide-react"
import { MediaScreen } from "@/components/media-screen"
import { FactsScreen } from "@/components/facts-screen"
import { ContentScreen } from "@/components/content-screen"
import { WordPressScreen } from "@/components/wordpress-screen"
import { AuthModal, type AuthResult } from "@/components/auth-modal"
import { SessionModal } from "@/components/session-modal"
import { RecordingWidget } from "@/components/recording-widget"
import { OtherFunctionsDrawer, type OperationLogEntry } from "@/components/other-functions-drawer"
import {
  createContentSession,
  loadContentSession,
  loadRecentContentSessions,
  loadWorkbook,
  saveSessionImageContextTranscript,
  uploadKnowledgeWorkbook,
  downloadKnowledgeWorkbook,
  validateImportKey,
  type ContentSession,
  type RecentSession,
  type SelectedMediaContext,
  type WorkbookStatus,
} from "@/lib/content-sessions"

type Screen = "media" | "facts" | "content" | "wordpress"

const STORAGE_API_KEY = "speech2post_import_key"
const STORAGE_USER_ID = "speech2post_user_id"
const STORAGE_SESSION_ID = "speech2post_session_id"
const STORAGE_SCREEN = "speech2post_active_screen"

const STEPS = [
  { id: "media" as const, label: "Media", icon: ImageIcon },
  { id: "facts" as const, label: "Facts", icon: FileText },
  { id: "content" as const, label: "Content", icon: Newspaper },
  { id: "wordpress" as const, label: "WordPress", icon: Wrench },
]

const ORDER: Screen[] = ["media", "facts", "content", "wordpress"]

function isScreen(value: string | null): value is Screen {
  return !!value && ORDER.includes(value as Screen)
}

function appendText(current: string, next: string) {
  const cleanCurrent = current.trim()
  const cleanNext = next.trim()
  if (!cleanCurrent) return cleanNext
  if (!cleanNext) return cleanCurrent
  return `${cleanCurrent}\n\n${cleanNext}`
}

function MetaChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-md bg-white/5 px-2.5 py-1 text-xs">
      <span className="text-topbar-foreground/55">{label}</span>
      <span className="font-medium text-topbar-foreground">{value}</span>
    </div>
  )
}

export default function Page() {
  const [screen, setScreen] = useState<Screen>("media")
  const [screenReady, setScreenReady] = useState(false)
  const [authReady, setAuthReady] = useState(false)
  const [auth, setAuth] = useState<AuthResult | null>(null)
  const [workbook, setWorkbook] = useState<WorkbookStatus | null>(null)
  const [session, setSession] = useState<ContentSession | null>(null)
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([])
  const [sessionModalOpen, setSessionModalOpen] = useState(false)
  const [otherFunctionsOpen, setOtherFunctionsOpen] = useState(false)
  const [agentOpen, setAgentOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [statusText, setStatusText] = useState("Starting")
  const [error, setError] = useState("")
  const [operationLog, setOperationLog] = useState<OperationLogEntry[]>([])
  const [selectedMedia, setSelectedMedia] = useState<SelectedMediaContext | null>(null)
  const [pictureTranscript, setPictureTranscript] = useState("")
  const [pictureTranscriptDrafts, setPictureTranscriptDrafts] = useState<Record<string, string>>({})
  const [pictureTranscriptSavingImmediately, setPictureTranscriptSavingImmediately] = useState(false)
  const sessionRef = useRef<ContentSession | null>(null)
  const pictureTranscriptRef = useRef("")
  const pictureSaveQueue = useRef<Promise<unknown>>(Promise.resolve())
  const immediatePictureSaves = useRef(0)

  const apiAuth = useMemo(
    () => (auth ? { apiKey: auth.apiKey, userId: auth.userId } : null),
    [auth],
  )

  const selectedPostType = session?.post_type_key || workbook?.selected_post_type_key || workbook?.post_types[0]?.post_type_key || ""
  const selectedPostTypeLabel =
    workbook?.post_types.find((item) => item.post_type_key === selectedPostType)?.display_name_de ||
    selectedPostType ||
    "-"

  const completedSteps = useMemo(
    () => ({
      media: (session?.image_refs?.length || 0) > 0,
      facts: !!session && ["ready_to_generate", "needs_review", "ready_to_publish", "published"].includes(session.state),
      content: !!session?.approval.approved,
      wordpress: false,
    }),
    [session],
  )

  const stepStatus = (id: Screen): "completed" | "active" | "inactive" => {
    if (id === screen) return "active"
    return completedSteps[id] ? "completed" : "inactive"
  }

  const navigable = (id: Screen) => !!session && ORDER.includes(id)

  function addOperation(label: string, detail: string, status: OperationLogEntry["status"] = "info") {
    setOperationLog((current) => [
      {
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        label,
        detail,
        status,
        at: new Date().toISOString(),
      },
      ...current,
    ].slice(0, 30))
  }

  function handleSessionChange(nextSession: ContentSession) {
    sessionRef.current = nextSession
    setSession(nextSession)
    sessionStorage.setItem(STORAGE_SESSION_ID, nextSession.session_id)
    setStatusText(`Session ${nextSession.state}`)
    addOperation("Session updated", `${nextSession.session_id.slice(0, 8)} · ${nextSession.state} · v${nextSession.version}`, "success")
  }

  async function refreshRecent(nextAuth = apiAuth) {
    if (!nextAuth) return
    const data = await loadRecentContentSessions(nextAuth)
    setRecentSessions(data.sessions || [])
  }

  async function bootstrap(result: AuthResult) {
    const nextAuth = { apiKey: result.apiKey, userId: result.userId }
    setLoading(true)
    setError("")
    try {
      const nextWorkbook = await loadWorkbook(nextAuth)
      setWorkbook(nextWorkbook)
      await refreshRecent(nextAuth)

      const storedSessionId = sessionStorage.getItem(STORAGE_SESSION_ID)
      if (storedSessionId) {
        try {
          const data = await loadContentSession(nextAuth, storedSessionId)
          handleSessionChange(data.session)
          setSessionModalOpen(false)
          setStatusText("Session restored")
          return
        } catch {
          sessionStorage.removeItem(STORAGE_SESSION_ID)
        }
      }
      setSessionModalOpen(true)
      setStatusText("Connected")
      addOperation("Workspace connected", result.userId, "success")
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not load workspace.")
      setSessionModalOpen(true)
      setStatusText("Connection issue")
      addOperation("Connection issue", error instanceof Error ? error.message : "Could not load workspace.", "error")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const storedScreen = sessionStorage.getItem(STORAGE_SCREEN)
    if (isScreen(storedScreen)) setScreen(storedScreen)
    setScreenReady(true)
  }, [])

  useEffect(() => {
    if (screenReady) sessionStorage.setItem(STORAGE_SCREEN, screen)
  }, [screen, screenReady])

  useEffect(() => {
    let active = true

    async function restoreAuth() {
      const apiKey = sessionStorage.getItem(STORAGE_API_KEY) || ""
      const userId = sessionStorage.getItem(STORAGE_USER_ID) || "flairlab"
      if (!apiKey) {
        if (active) {
          setAuthReady(true)
          setStatusText("No access key")
        }
        return
      }
      try {
        const data = await validateImportKey({ apiKey, userId })
        const client = data.clients.find((item) => item.client_id === userId) ?? data.clients[0]
        if (!client) throw new Error("No configured client was returned.")
        const result = { apiKey, userId: client.client_id, client }
        if (!active) return
        setAuth(result)
        setAuthReady(true)
        await bootstrap(result)
      } catch {
        sessionStorage.removeItem(STORAGE_API_KEY)
        sessionStorage.removeItem(STORAGE_SESSION_ID)
        if (active) {
          setAuthReady(true)
          setStatusText("Login required")
        }
      }
    }

    void restoreAuth()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!apiAuth || !session?.post_type_key) return
    const nextAuth = apiAuth
    const postTypeKey = session.post_type_key
    let active = true

    async function refreshWorkbookForSession() {
      try {
        const nextWorkbook = await loadWorkbook(nextAuth, postTypeKey)
        if (active) setWorkbook(nextWorkbook)
      } catch (error) {
        if (active) setError(error instanceof Error ? error.message : "Could not load post type schema.")
      }
    }

    void refreshWorkbookForSession()
    return () => {
      active = false
    }
  }, [apiAuth, session?.post_type_key])

  useEffect(() => {
    setSelectedMedia(null)
    pictureTranscriptRef.current = ""
    setPictureTranscript("")
    setPictureTranscriptDrafts({})
  }, [session?.session_id])

  async function handleAuthenticated(result: AuthResult) {
    sessionStorage.setItem(STORAGE_API_KEY, result.apiKey)
    sessionStorage.setItem(STORAGE_USER_ID, result.userId)
    setAuth(result)
    await bootstrap(result)
  }

  async function handleCreateSession(postTypeKey: string) {
    if (!apiAuth) return
    setLoading(true)
    setError("")
    try {
      const data = await createContentSession(apiAuth, postTypeKey)
      handleSessionChange(data.session)
      sessionStorage.setItem(STORAGE_SESSION_ID, data.session.session_id)
      setSessionModalOpen(false)
      setScreen("media")
      setStatusText("Session created")
      addOperation("Session created", `${data.session.session_id.slice(0, 8)} · ${postTypeKey}`, "success")
      await refreshRecent(apiAuth)
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create session.")
    } finally {
      setLoading(false)
    }
  }

  async function handleLoadSession(sessionId: string) {
    if (!apiAuth) return
    setLoading(true)
    setError("")
    try {
      const data = await loadContentSession(apiAuth, sessionId)
      handleSessionChange(data.session)
      sessionStorage.setItem(STORAGE_SESSION_ID, data.session.session_id)
      setSessionModalOpen(false)
      setScreen("media")
      setStatusText("Session loaded")
      addOperation("Session loaded", sessionId.slice(0, 8), "success")
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not load session.")
    } finally {
      setLoading(false)
    }
  }

  async function handleReloadSession() {
    if (!apiAuth || !session) return
    setLoading(true)
    setError("")
    try {
      const data = await loadContentSession(apiAuth, session.session_id)
      handleSessionChange(data.session)
      addOperation("Session reloaded", data.session.session_id.slice(0, 8), "success")
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not reload session."
      setError(message)
      addOperation("Session reload failed", message, "error")
    } finally {
      setLoading(false)
    }
  }

  const handlePictureTranscriptChange = useCallback((value: string) => {
    pictureTranscriptRef.current = value
    setPictureTranscript(value)
    setPictureTranscriptDrafts((current) => {
      if (!selectedMedia?.mediaId) return current
      return { ...current, [selectedMedia.mediaId]: value }
    })
  }, [selectedMedia?.mediaId])

  const handlePictureTranscriptAppend = useCallback((text: string) => {
    if (!apiAuth || !selectedMedia?.mediaId || selectedMedia.mediaId.startsWith("pending-")) {
      return Promise.reject(new Error("Wait until the active picture has finished uploading."))
    }

    const media = selectedMedia
    const next = appendText(pictureTranscriptRef.current, text)
    pictureTranscriptRef.current = next
    setPictureTranscript(next)
    setPictureTranscriptDrafts((drafts) => ({ ...drafts, [media.mediaId]: next }))
    immediatePictureSaves.current += 1
    setPictureTranscriptSavingImmediately(true)

    const save = pictureSaveQueue.current.then(async () => {
      const currentSession = sessionRef.current
      if (!currentSession) throw new Error("The active session is no longer available.")
      const data = await saveSessionImageContextTranscript(apiAuth, currentSession, media.filename, next)
      handleSessionChange(data.session)
    })
    pictureSaveQueue.current = save.catch(() => undefined)

    return save.finally(() => {
      immediatePictureSaves.current -= 1
      if (!immediatePictureSaves.current) setPictureTranscriptSavingImmediately(false)
    })
  }, [apiAuth, selectedMedia])

  function handleSelectedMediaChange(media: SelectedMediaContext | null) {
    setSelectedMedia(media)
    if (!media || !session) {
      pictureTranscriptRef.current = ""
      setPictureTranscript("")
      return
    }
    const nextTranscript =
      Object.prototype.hasOwnProperty.call(pictureTranscriptDrafts, media.mediaId)
        ? pictureTranscriptDrafts[media.mediaId]
        : String((session.image_context_transcripts || {})[media.mediaId] || "")
    pictureTranscriptRef.current = nextTranscript
    setPictureTranscript(nextTranscript)
  }

  return (
    <div className="min-h-dvh w-full overflow-x-hidden bg-background text-foreground">
      {authReady && !auth && <AuthModal initialUserId="flairlab" onAuthenticated={handleAuthenticated} />}
      {auth && sessionModalOpen && (
        <SessionModal
          postTypes={workbook?.post_types || []}
          selectedPostType={selectedPostType}
          recentSessions={recentSessions}
          loading={loading}
          error={error}
          onCreate={handleCreateSession}
          onLoad={handleLoadSession}
          onRefresh={() => void refreshRecent()}
          onClose={() => setSessionModalOpen(false)}
        />
      )}
      {/* ===================== TOP BAR ===================== */}
      <header className="sticky top-0 z-20 bg-topbar text-topbar-foreground">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-3 py-2.5 sm:px-4">
          <div className="flex items-center gap-2">
            <div className="flex size-7 items-center justify-center rounded-md bg-gold text-gold-foreground">
              <Mic className="size-4" aria-hidden="true" />
            </div>
            <span className="text-sm font-semibold tracking-tight sm:text-base">SPEECH2POST</span>
          </div>

          <div className="ml-1 hidden flex-wrap items-center gap-1.5 lg:flex">
            <MetaChip label="Client:" value={auth?.client.client_id || "-"} />
            <MetaChip label="Session:" value={session ? session.session_id.slice(0, 8) : "-"} />
            <MetaChip label="Post type:" value={selectedPostTypeLabel} />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-md bg-confirm/15 px-2 py-1 text-xs font-medium text-topbar-foreground sm:inline-flex">
              <Check className="size-3.5 text-confirm" aria-hidden="true" />
              {loading ? "Loading" : statusText}
            </span>
            <span
              className="flex size-8 items-center justify-center rounded-md bg-white/5"
              title={session ? "Session connected" : "No session"}
            >
              <Wifi className={`size-4 ${session ? "text-confirm" : "text-muted-foreground"}`} aria-hidden="true" />
            </span>
            <button
              type="button"
              onClick={() => auth && setSessionModalOpen(true)}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-white/5 px-2.5 text-xs font-semibold transition-colors hover:bg-white/10"
            >
              <FilePlus2 className="size-4" aria-hidden="true" />
              New session
            </button>
            <button
              type="button"
              onClick={() => setOtherFunctionsOpen(true)}
              className="flex size-8 items-center justify-center rounded-md bg-white/5 transition-colors hover:bg-white/10"
              aria-label="Open other functions"
            >
              <SlidersHorizontal className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* meta chips on mobile */}
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2.5 lg:hidden">
          <MetaChip label="Client:" value={auth?.client.client_id || "-"} />
          <MetaChip label="Session:" value={session ? session.session_id.slice(0, 8) : "-"} />
          <MetaChip label="Post type:" value={selectedPostTypeLabel} />
        </div>
      </header>

      {/* ===================== WORKFLOW STEPS ===================== */}
      <nav aria-label="Workflow steps" className="sticky top-[49px] z-10 border-b border-border bg-panel sm:top-[53px]">
        <div className="mx-auto flex max-w-7xl items-center gap-2 overflow-x-auto px-3 py-2.5 sm:px-4">
          {STEPS.map((step, i) => {
            const status = stepStatus(step.id)
            const canNavigate = navigable(step.id)
            return (
              <div key={step.id} className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => canNavigate && setScreen(step.id)}
                  disabled={!canNavigate}
                  aria-current={status === "active" ? "step" : undefined}
                  className={[
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm whitespace-nowrap transition-colors",
                    status === "active"
                      ? "bg-gold/15 font-semibold text-foreground ring-1 ring-gold/40"
                      : status === "completed"
                        ? "text-foreground hover:bg-muted"
                        : "text-muted-foreground",
                    !canNavigate ? "cursor-not-allowed" : "cursor-pointer",
                  ].join(" ")}
                >
                  <span
                    className={[
                      "flex size-5 items-center justify-center rounded-full text-[11px] font-semibold",
                      status === "active"
                        ? "bg-gold text-gold-foreground"
                        : status === "completed"
                          ? "bg-confirm text-confirm-foreground"
                          : "bg-muted text-muted-foreground",
                    ].join(" ")}
                  >
                    {status === "completed" ? <Check className="size-3" aria-hidden="true" /> : i + 1}
                  </span>
                  <step.icon className="size-4" aria-hidden="true" />
                  {step.label}
                </button>
                {i < STEPS.length - 1 && <span className="h-px w-4 shrink-0 bg-border" aria-hidden="true" />}
              </div>
            )
          })}
        </div>
      </nav>

      {/* ===================== MAIN WORKSPACE ===================== */}
      <main className="mx-auto max-w-7xl px-3 py-4 sm:px-4">
        {!authReady ? (
          <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">Loading workspace…</div>
        ) : screen === "media" ? (
          <MediaScreen
            auth={apiAuth}
            session={session}
            onSessionChange={handleSessionChange}
            pictureTranscript={pictureTranscript}
            onPictureTranscriptChange={handlePictureTranscriptChange}
            onSelectedMediaChange={handleSelectedMediaChange}
            onOpenAgent={() => setAgentOpen(true)}
            pictureTranscriptSavingImmediately={pictureTranscriptSavingImmediately}
          />
        ) : screen === "facts" ? (
          <FactsScreen
            auth={apiAuth}
            session={session}
            workbook={workbook}
            onSessionChange={handleSessionChange}
            onBackToMedia={() => setScreen("media")}
            onContinueToContent={() => setScreen("content")}
          />
        ) : screen === "wordpress" ? (
          <WordPressScreen
            auth={apiAuth}
            session={session}
            onSessionChange={handleSessionChange}
            onBackToContent={() => setScreen("content")}
          />
        ) : (
          <ContentScreen
            auth={apiAuth}
            session={session}
            workbook={workbook}
            onSessionChange={handleSessionChange}
            onBackToFacts={() => setScreen("facts")}
            onContinueToWordPress={() => setScreen("wordpress")}
          />
        )}
      </main>
      {auth && screen !== "wordpress" && (
        <RecordingWidget
          auth={apiAuth}
          session={session}
          activeScreen={screen}
          open={agentOpen}
          onOpenChange={setAgentOpen}
          onSessionChange={handleSessionChange}
          onNavigateFacts={() => setScreen("facts")}
          selectedPictureId={selectedMedia?.mediaId}
          onPictureTranscriptAppend={handlePictureTranscriptAppend}
        />
      )}
      <OtherFunctionsDrawer
        open={otherFunctionsOpen}
        auth={auth}
        workbook={workbook}
        session={session}
        recentSessions={recentSessions}
        loading={loading}
        statusText={statusText}
        error={error}
        operationLog={operationLog}
        onClose={() => setOtherFunctionsOpen(false)}
        onRefreshRecent={() => void refreshRecent()}
        onReloadSession={() => void handleReloadSession()}
        onOpenSessionMenu={() => {
          setOtherFunctionsOpen(false)
          setSessionModalOpen(true)
        }}
        onLoadSession={(sessionId) => {
          setOtherFunctionsOpen(false)
          void handleLoadSession(sessionId)
        }}
        onSessionChange={handleSessionChange}
        onUploadWorkbook={async (file) => {
          if (!apiAuth) return
          await uploadKnowledgeWorkbook(apiAuth, file, selectedPostType)
          setWorkbook(await loadWorkbook(apiAuth, selectedPostType))
          addOperation("Workbook updated", file.name, "success")
        }}
        onDownloadWorkbook={async () => {
          if (!apiAuth) return
          await downloadKnowledgeWorkbook(apiAuth)
          addOperation("Workbook downloaded", workbook?.filename || "database-datei.xlsm", "success")
        }}
      />
    </div>
  )
}
