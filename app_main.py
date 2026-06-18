import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field as PydanticField

from action_api_event_import import (
    EventPostActionRequest,
    app as action_app,
    import_event_post_from_zip,
)
from app_transcription import DEFAULT_TRANSCRIPTION_MODEL, transcribe_audio_file
from config import get_client_config


APP_SESSION_ROOT = Path("data/app_sessions")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".webm", ".mp4"}

app = FastAPI(
    title="FLAIRLAB Event Post Generator",
    version="0.1.0",
    description="Mobile workflow for voice, media, AI draft review, and WordPress event post creation.",
)


def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    from action_api_event_import import IMPORT_API_KEY as configured_key

    if configured_key and x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


class SessionCreateRequest(BaseModel):
    client_id: str = "flairlab"
    post_type: str = "Event"


class SessionCreateResponse(BaseModel):
    session_id: str
    client_id: str
    post_type: str
    status: str
    next_step: str


class SessionStateResponse(BaseModel):
    session_id: str
    client_id: str
    post_type: str
    status: str
    steps: dict[str, str]
    files: dict[str, Any] = PydanticField(default_factory=dict)
    transcript: dict[str, Any] = PydanticField(default_factory=dict)


class TranscriptUpdateRequest(BaseModel):
    text: str


def write_session_state(session_id: str, state: dict[str, Any]) -> None:
    session_dir = APP_SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "state.json").write_text(
        __import__("json").dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_session_state(session_id: str) -> dict[str, Any]:
    path = APP_SESSION_ROOT / session_id / "state.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    return __import__("json").loads(path.read_text(encoding="utf-8"))


def safe_upload_name(filename: str | None, fallback: str) -> str:
    raw_name = Path(filename or fallback).name
    cleaned = "".join(char if char.isalnum() or char in "._- " else "_" for char in raw_name).strip()
    return cleaned or fallback


def save_upload_file(upload: UploadFile, target_dir: Path, fallback: str) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_upload_name(upload.filename, fallback)
    destination = target_dir / filename
    counter = 2
    while destination.exists():
        destination = target_dir / f"{destination.stem}-{counter}{destination.suffix}"
        counter += 1

    with destination.open("wb") as output:
        while chunk := upload.file.read(1024 * 1024):
            output.write(chunk)

    return {
        "filename": destination.name,
        "path": str(destination),
        "size": destination.stat().st_size,
        "content_type": upload.content_type,
    }


def validate_extension(file_info: dict[str, Any], allowed: set[str], label: str) -> None:
    suffix = Path(file_info["filename"]).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {label} file extension: {file_info['filename']}",
        )


APP_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FLAIRLAB Event Post Generator</title>
  <style>
    :root { color-scheme: light; --ink:#1f2933; --muted:#627386; --line:#d8e0e8; --brand:#0f766e; --soft:#f5f7fa; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:#ffffff; }
    main { width:min(920px, 100%); margin:0 auto; padding:22px 16px 56px; }
    header { padding:12px 0 20px; border-bottom:1px solid var(--line); margin-bottom:20px; }
    h1 { font-size:clamp(24px, 6vw, 38px); line-height:1.05; margin:0 0 8px; letter-spacing:0; }
    h2 { font-size:18px; margin:0 0 14px; }
    p { color:var(--muted); line-height:1.45; margin:0; }
    section { padding:18px 0; border-bottom:1px solid var(--line); }
    label { display:block; font-weight:650; font-size:14px; margin:14px 0 7px; }
    input, select, textarea, button { width:100%; font:inherit; border-radius:8px; }
    input, select, textarea { border:1px solid var(--line); padding:11px 12px; background:#fff; }
    textarea { min-height:220px; resize:vertical; line-height:1.45; }
    button { border:0; padding:12px 14px; background:var(--brand); color:white; font-weight:750; cursor:pointer; margin-top:14px; }
    button.secondary { background:#314352; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); }
    .status { background:var(--soft); border:1px solid var(--line); padding:12px; border-radius:8px; white-space:pre-wrap; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; overflow:auto; }
    .image-choice { display:flex; gap:8px; align-items:center; padding:8px 0; border-bottom:1px solid #eef2f6; }
    .image-choice input { width:auto; }
    .image-choice span { overflow-wrap:anywhere; }
  </style>
</head>
<body>
<main>
  <header>
    <h1>FLAIRLAB Event Post Generator</h1>
    <p>Create a session, upload voice and media, transcribe, then refine the event notes.</p>
  </header>

  <section>
    <h2>Access</h2>
    <label for="apiKey">API key</label>
    <input id="apiKey" type="password" autocomplete="off" placeholder="X-API-Key">
    <button class="secondary" onclick="saveKey()">Save key</button>
  </section>

  <section>
    <h2>1. Session</h2>
    <div class="grid">
      <div>
        <label for="clientId">Client</label>
        <input id="clientId" value="flairlab">
      </div>
      <div>
        <label for="postType">Post type</label>
        <select id="postType">
          <option>Event</option>
          <option>Location</option>
          <option>Cocktail</option>
        </select>
      </div>
    </div>
    <button onclick="createSession()">Create session</button>
  </section>

  <section>
    <h2>2. Upload</h2>
    <label for="voice">Voice message</label>
    <input id="voice" type="file" accept="audio/*,video/mp4,video/webm">
    <label for="images">Pictures</label>
    <input id="images" type="file" accept="image/*" multiple onchange="renderImageChoices()">
    <div id="featuredChoices"></div>
    <label for="videos">Video</label>
    <input id="videos" type="file" accept="video/*">
    <button onclick="uploadFiles()">Upload files</button>
  </section>

  <section>
    <h2>3. Transcript</h2>
    <button onclick="transcribe()">Transcribe voice</button>
    <label for="transcript">Editable transcript</label>
    <textarea id="transcript" placeholder="The transcript will appear here. You can edit it at any moment."></textarea>
    <button class="secondary" onclick="saveTranscript()">Save transcript update</button>
  </section>

  <section>
    <h2>Status</h2>
    <div id="status" class="status">Ready.</div>
  </section>
</main>

<script>
let sessionId = sessionStorage.getItem("flairlab_session_id") || "";
document.getElementById("apiKey").value = sessionStorage.getItem("flairlab_api_key") || "";
function key(){ return document.getElementById("apiKey").value.trim(); }
function headers(json=true){ const h = {"X-API-Key": key()}; if(json) h["Content-Type"]="application/json"; return h; }
function status(obj){ document.getElementById("status").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2); }
function saveKey(){ sessionStorage.setItem("flairlab_api_key", key()); status("API key saved in this browser session."); }
async function api(path, options={}) {
  const res = await fetch(path, options);
  const text = await res.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(typeof data === "string" ? data : JSON.stringify(data));
  return data;
}
async function createSession(){
  saveKey();
  const data = await api("/app/sessions", {
    method:"POST",
    headers:headers(),
    body:JSON.stringify({client_id:document.getElementById("clientId").value || "flairlab", post_type:document.getElementById("postType").value})
  });
  sessionId = data.session_id;
  sessionStorage.setItem("flairlab_session_id", sessionId);
  status(data);
}
function renderImageChoices(){
  const wrap = document.getElementById("featuredChoices");
  wrap.innerHTML = "";
  [...document.getElementById("images").files].forEach((file, index) => {
    const row = document.createElement("label");
    row.className = "image-choice";
    row.innerHTML = `<input type="radio" name="featured" value="${file.name}" ${index===0 ? "checked" : ""}><span>${file.name}</span>`;
    wrap.appendChild(row);
  });
}
async function uploadFiles(){
  if(!sessionId) throw new Error("Create a session first.");
  const form = new FormData();
  const voice = document.getElementById("voice").files[0];
  if(!voice) throw new Error("Select a voice file.");
  form.append("voice", voice);
  [...document.getElementById("images").files].forEach(f => form.append("images", f));
  const video = document.getElementById("videos").files[0];
  if(video) form.append("videos", video);
  const featured = document.querySelector("input[name='featured']:checked");
  if(featured) form.append("featured_image_filename", featured.value);
  const data = await api(`/app/sessions/${sessionId}/uploads`, {method:"POST", headers:{"X-API-Key":key()}, body:form});
  status(data);
}
async function transcribe(){
  if(!sessionId) throw new Error("Create a session first.");
  status("Transcribing...");
  const data = await api(`/app/sessions/${sessionId}/transcribe`, {method:"POST", headers:headers(false)});
  document.getElementById("transcript").value = data.transcript?.text || "";
  status(data);
}
async function saveTranscript(){
  if(!sessionId) throw new Error("Create a session first.");
  const data = await api(`/app/sessions/${sessionId}/transcript`, {
    method:"PUT",
    headers:headers(),
    body:JSON.stringify({text:document.getElementById("transcript").value})
  });
  status(data);
}
window.addEventListener("unhandledrejection", e => status("Error: " + e.reason.message));
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return APP_HTML


@app.get("/app", response_class=HTMLResponse)
def app_interface() -> str:
    return APP_HTML


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/clients")
def clients(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    flairlab = get_client_config("flairlab")
    return {
        "clients": [
            {
                "client_id": "flairlab",
                "wp_base_url": flairlab.wp_base_url,
                "status": "configured" if flairlab.wp_username and flairlab.wp_app_password else "missing_credentials",
            }
        ]
    }


@app.post("/app/sessions", response_model=SessionCreateResponse)
def create_session(
    payload: SessionCreateRequest,
    _: None = Depends(verify_api_key),
) -> SessionCreateResponse:
    session_id = uuid.uuid4().hex
    state = {
        "session_id": session_id,
        "client_id": payload.client_id,
        "post_type": payload.post_type,
        "status": "created",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "steps": {
            "upload_voice_and_media": "pending",
            "select_featured_image": "pending",
            "transcribe_voice": "pending",
            "refine_with_ai_chat": "pending",
            "approve_csv": "pending",
            "create_wordpress_post": "pending",
        },
    }
    write_session_state(session_id, state)
    return SessionCreateResponse(
        session_id=session_id,
        client_id=payload.client_id,
        post_type=payload.post_type,
        status="created",
        next_step="upload_voice_and_media",
    )


@app.get("/app/sessions/{session_id}", response_model=SessionStateResponse)
def get_session(
    session_id: str,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    return SessionStateResponse(**read_session_state(session_id))


@app.post("/app/sessions/{session_id}/uploads", response_model=SessionStateResponse)
async def upload_session_files(
    session_id: str,
    voice: UploadFile = File(...),
    images: list[UploadFile] | None = File(default=None),
    videos: list[UploadFile] | None = File(default=None),
    featured_image_filename: str | None = Form(default=None),
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    session_dir = APP_SESSION_ROOT / session_id

    voice_info = save_upload_file(voice, session_dir / "voice", "voice")
    validate_extension(voice_info, AUDIO_EXTENSIONS, "voice")

    image_infos = []
    for index, image in enumerate(images or [], start=1):
        image_info = save_upload_file(image, session_dir / "images", f"image_{index}.jpg")
        validate_extension(image_info, IMAGE_EXTENSIONS, "image")
        image_infos.append(image_info)

    video_infos = []
    for index, video in enumerate(videos or [], start=1):
        video_info = save_upload_file(video, session_dir / "videos", f"video_{index}.mp4")
        validate_extension(video_info, VIDEO_EXTENSIONS, "video")
        video_infos.append(video_info)

    if len(video_infos) > 1:
        raise HTTPException(status_code=400, detail="Only one video per post is supported for now.")

    if featured_image_filename:
        known_image_names = {item["filename"] for item in image_infos}
        if featured_image_filename not in known_image_names:
            raise HTTPException(status_code=400, detail="Featured image must match one uploaded image filename.")

    state["files"] = {
        "voice": voice_info,
        "images": image_infos,
        "videos": video_infos,
        "featured_image_filename": featured_image_filename,
    }
    state["status"] = "files_uploaded"
    state["steps"]["upload_voice_and_media"] = "complete"
    state["steps"]["select_featured_image"] = "complete" if featured_image_filename else "pending"
    state["steps"]["transcribe_voice"] = "pending"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/app/sessions/{session_id}/transcribe", response_model=SessionStateResponse)
def transcribe_session_voice(
    session_id: str,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    voice = state.get("files", {}).get("voice")
    if not voice:
        raise HTTPException(status_code=400, detail="Upload a voice file before transcription.")

    transcript_text = transcribe_audio_file(voice["path"], model=DEFAULT_TRANSCRIPTION_MODEL)
    state["transcript"] = {
        "text": transcript_text,
        "source": "openai_transcription",
        "model": DEFAULT_TRANSCRIPTION_MODEL,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    state["status"] = "transcribed"
    state["steps"]["transcribe_voice"] = "complete"
    state["steps"]["refine_with_ai_chat"] = "pending"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.put("/app/sessions/{session_id}/transcript", response_model=SessionStateResponse)
def update_session_transcript(
    session_id: str,
    payload: TranscriptUpdateRequest,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    state["transcript"] = {
        "text": payload.text,
        "source": "manual_update",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    state["status"] = "transcript_updated"
    state["steps"]["transcribe_voice"] = "complete"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/event-posts/from-zip")
async def action_event_post_from_zip(
    payload: EventPostActionRequest,
    _: None = Depends(verify_api_key),
):
    return await import_event_post_from_zip(payload)


app.mount("/action", action_app)
