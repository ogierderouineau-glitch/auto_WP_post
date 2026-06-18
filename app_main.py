import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field as PydanticField

from action_api_event_import import (
    EventPostActionRequest,
    app as action_app,
    build_import_args,
    import_event_post_from_zip,
    post_response_from_output,
)
from app_draft_generator import create_session_draft, rebuild_session_package, revise_session_draft
from app_knowledge_base import guidance_for_field, load_workbook_guidance
from app_transcription import DEFAULT_TRANSCRIPTION_MODEL, transcribe_audio_file
from config import KNOWLEDGE_WORKBOOK_PATH, KNOWLEDGE_WORKBOOK_SHEET, get_client_config
from run_event_import import run_import
from step_10_event_payload import DEFAULT_DATA_GID, DEFAULT_SHEET_ID, load_csv_text, parse_helper_csv


APP_SESSION_ROOT = Path("data/app_sessions")
DEFAULT_KNOWLEDGE_WORKBOOK_PATH = Path("data/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".ogg", ".opus", ".wav", ".webm", ".mp4"}
WORKBOOK_EXTENSIONS = {".xlsm", ".xlsx"}

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
    draft: dict[str, Any] = PydanticField(default_factory=dict)
    wordpress_post: dict[str, Any] = PydanticField(default_factory=dict)
    ui_cache: dict[str, Any] = PydanticField(default_factory=dict)


class TranscriptUpdateRequest(BaseModel):
    text: str


class DraftGenerateRequest(BaseModel):
    category: str = "auto event post"


class DraftUpdateRequest(BaseModel):
    csv_text: str


class DraftChatRequest(BaseModel):
    message: str


class UiCacheUpdateRequest(BaseModel):
    cache: dict[str, Any] = PydanticField(default_factory=dict)


class CreateWordPressPostRequest(BaseModel):
    status: str = "draft"
    existing_post_mode: str = "update"


def write_session_state(session_id: str, state: dict[str, Any]) -> None:
    session_dir = APP_SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cache_dir = session_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "session_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    transcript_text = state.get("transcript", {}).get("text")
    if transcript_text is not None:
        (cache_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")
    draft_csv = state.get("draft", {}).get("csv_text")
    if draft_csv is not None:
        (cache_dir / "draft.csv").write_text(draft_csv, encoding="utf-8")
    wordpress_post = state.get("wordpress_post")
    if wordpress_post:
        (cache_dir / "wordpress_post.json").write_text(
            json.dumps(wordpress_post, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def read_session_state(session_id: str) -> dict[str, Any]:
    path = APP_SESSION_ROOT / session_id / "state.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def safe_upload_name(filename: str | None, fallback: str) -> str:
    raw_name = Path(filename or fallback).name
    cleaned = "".join(char if char.isalnum() or char in "._- " else "_" for char in raw_name).strip()
    return cleaned or fallback


def save_upload_file(upload: UploadFile, target_dir: Path, fallback: str) -> dict[str, Any]:
    target_dir.mkdir(parents=True, exist_ok=True)
    original_filename = upload.filename or fallback
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
        "original_filename": original_filename,
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


def load_helper_specs():
    helper_csv_text = load_csv_text(DEFAULT_SHEET_ID, DEFAULT_DATA_GID, None)
    specs = parse_helper_csv(helper_csv_text)
    workbook_guidance = load_workbook_guidance(active_knowledge_workbook_path(), KNOWLEDGE_WORKBOOK_SHEET)
    for spec in specs:
        guidance_items = guidance_for_field(workbook_guidance, spec.source_name, spec.acf_name)
        if guidance_items:
            combined = [item for item in [spec.guidance, *guidance_items] if item]
            spec.guidance = "\n".join(dict.fromkeys(combined))
    return specs


def active_knowledge_workbook_path() -> Path:
    return Path(KNOWLEDGE_WORKBOOK_PATH) if KNOWLEDGE_WORKBOOK_PATH else DEFAULT_KNOWLEDGE_WORKBOOK_PATH


def read_json_if_exists(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "Could not parse JSON file.", "path": str(path)}


def knowledge_status_payload() -> dict[str, Any]:
    path = active_knowledge_workbook_path()
    guidance = load_workbook_guidance(path, KNOWLEDGE_WORKBOOK_SHEET)
    return {
        "path": str(path),
        "exists": path.exists(),
        "configured_sheet": KNOWLEDGE_WORKBOOK_SHEET,
        "loaded_sheet": guidance.get("sheet"),
        "guidance_items": len(guidance.get("items", [])),
        "error": guidance.get("error"),
    }


APP_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FLAIRLAB Event Post Generator</title>
  <style>
    :root { color-scheme: light; --ink:#1f2933; --muted:#627386; --line:#d8e0e8; --brand:#0f766e; --brand-strong:#0b5f59; --soft:#f5f7fa; --paper:#ffffff; --danger:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:linear-gradient(180deg, #eef7f5 0, #f8fafc 260px, #ffffff 100%); }
    main { width:min(920px, 100%); margin:0 auto; padding:22px 16px 56px; }
    @media (min-width: 1260px) {
      main { margin-left:max(16px, calc((100vw - 1180px) / 2)); margin-right:380px; }
    }
    header { padding:16px 0 22px; margin-bottom:18px; }
    h1 { font-size:clamp(24px, 6vw, 38px); line-height:1.05; margin:0 0 8px; letter-spacing:0; }
    h2 { font-size:18px; margin:0 0 14px; }
    p { color:var(--muted); line-height:1.45; margin:0; }
    section { padding:18px 0; border-bottom:1px solid var(--line); }
    details.panel { background:rgba(255,255,255,.92); border:1px solid var(--line); border-radius:8px; padding:0; margin:0 0 12px; box-shadow:0 14px 34px rgba(31,41,51,.06); overflow:hidden; }
    details.panel > summary { list-style:none; display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 18px; cursor:pointer; font-weight:800; font-size:18px; }
    details.panel > summary::-webkit-details-marker { display:none; }
    details.panel > summary::after { content:"+"; flex:0 0 auto; width:28px; height:28px; border-radius:8px; display:grid; place-items:center; background:var(--soft); border:1px solid var(--line); color:var(--muted); font-size:18px; line-height:1; }
    details.panel[open] > summary::after { content:"-"; }
    .panel-body { padding:0 18px 18px; }
    label { display:block; font-weight:650; font-size:14px; margin:14px 0 7px; }
    input, select, textarea, button { width:100%; font:inherit; border-radius:8px; }
    input, select, textarea { border:1px solid var(--line); padding:11px 12px; background:#fff; transition:border-color .15s ease, box-shadow .15s ease; }
    input:focus, select:focus, textarea:focus { outline:0; border-color:var(--brand); box-shadow:0 0 0 3px rgba(15,118,110,.12); }
    input[type="file"] { padding:10px; background:var(--soft); }
    textarea { min-height:220px; resize:vertical; line-height:1.45; }
    button { border:0; padding:12px 14px; background:var(--brand); color:white; font-weight:750; cursor:pointer; margin-top:14px; transition:transform .12s ease, background .15s ease, box-shadow .15s ease; box-shadow:0 10px 22px rgba(15,118,110,.18); }
    button:hover:not(:disabled) { transform:translateY(-1px); background:var(--brand-strong); }
    button.secondary { background:#314352; box-shadow:0 10px 22px rgba(49,67,82,.14); }
    button.secondary:hover:not(:disabled) { background:#253644; }
    button:disabled { opacity:.55; cursor:not-allowed; }
    .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); }
    .status { background:var(--soft); border:1px solid var(--line); padding:12px; border-radius:8px; white-space:pre-wrap; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; overflow:auto; }
    .status-rail { position:fixed; right:16px; top:16px; width:340px; max-height:calc(100vh - 32px); overflow:auto; z-index:12; background:#fff; border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 18px 46px rgba(31,41,51,.14); }
    .status-rail h2 { margin-bottom:10px; }
    .status-rail-output { max-height:48vh; }
    .status-rail-state { display:flex; align-items:center; gap:10px; margin-top:12px; color:var(--muted); font-size:14px; }
    .mini-spinner { width:18px; height:18px; border-radius:999px; border:3px solid #d8e0e8; border-top-color:var(--brand); display:none; animation:spin .8s linear infinite; }
    .is-busy .mini-spinner { display:block; }
    .loading-backdrop { position:fixed; inset:0; display:none; align-items:center; justify-content:center; padding:18px; background:rgba(255,255,255,.72); backdrop-filter:blur(2px); z-index:30; }
    .loading-backdrop.open { display:flex; }
    .loading-box { width:min(360px, 100%); background:#fff; border:1px solid var(--line); border-radius:8px; padding:20px; box-shadow:0 22px 60px rgba(31,41,51,.22); text-align:center; }
    .spinner { width:42px; height:42px; margin:0 auto 14px; border-radius:999px; border:5px solid #d8e0e8; border-top-color:var(--brand); animation:spin .8s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }
    @media (max-width: 1259px) {
      .status-rail { left:12px; right:12px; top:auto; bottom:12px; width:auto; max-height:30vh; }
      main { padding-bottom:220px; }
    }
    .summary { background:var(--soft); border:1px solid var(--line); padding:12px; border-radius:8px; color:var(--muted); font-size:14px; line-height:1.45; margin-top:14px; }
    .links { display:grid; gap:10px; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); margin-top:14px; }
    .links a { display:block; text-align:center; text-decoration:none; border-radius:8px; padding:12px 14px; background:#314352; color:#fff; font-weight:750; }
    .draft-table-wrap { border:1px solid var(--line); border-radius:8px; overflow:auto; max-height:70vh; background:#fff; }
    .draft-table { width:100%; border-collapse:collapse; min-width:620px; }
    .draft-table th, .draft-table td { border-bottom:1px solid #eef2f6; padding:9px; vertical-align:top; text-align:left; }
    .draft-table th { position:sticky; top:0; background:var(--soft); z-index:1; font-size:13px; }
    .draft-table td:first-child { width:220px; color:var(--muted); font-weight:650; overflow-wrap:anywhere; }
    .draft-table textarea { min-height:76px; border:0; padding:0; border-radius:0; resize:vertical; line-height:1.4; }
    .raw-csv { display:none; }
    .chat-log { display:grid; gap:10px; max-height:320px; overflow:auto; }
    .chat-message { padding:10px 12px; border-radius:8px; border:1px solid var(--line); white-space:pre-wrap; line-height:1.45; }
    .chat-message.user { background:#eef7f5; }
    .chat-message.assistant { background:var(--soft); }
    .modal-backdrop { position:fixed; inset:0; display:none; align-items:center; justify-content:center; padding:18px; background:rgba(31,41,51,.46); z-index:20; }
    .modal-backdrop.open { display:flex; }
    .modal { width:min(620px, 100%); max-height:90vh; overflow:auto; background:#fff; border-radius:8px; padding:18px; box-shadow:0 22px 60px rgba(31,41,51,.28); }
    .modal h2 { margin-bottom:8px; }
    .modal-actions { display:grid; gap:10px; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); margin-top:16px; }
    .modal-actions a, .modal-actions button { display:block; text-align:center; text-decoration:none; border-radius:8px; padding:12px 14px; background:var(--brand); color:#fff; font-weight:750; margin:0; }
    .modal-actions .secondary { background:#314352; }
    .image-choice { display:flex; gap:8px; align-items:center; padding:8px 0; border-bottom:1px solid #eef2f6; }
    .image-choice input { width:auto; }
    .image-choice span { overflow-wrap:anywhere; }
    .image-preview-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(120px, 1fr)); gap:10px; margin-top:12px; }
    .image-preview { border:1px solid var(--line); border-radius:8px; overflow:hidden; background:#fff; box-shadow:0 8px 18px rgba(31,41,51,.06); }
    .image-preview img { width:100%; aspect-ratio:1; object-fit:cover; display:block; }
    .image-preview span { display:block; padding:7px; font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
    .recording-controls { display:grid; gap:10px; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); }
    .icon-button { display:flex; align-items:center; justify-content:center; gap:10px; min-height:48px; }
    .icon-symbol { width:22px; height:22px; border-radius:999px; display:inline-grid; place-items:center; background:rgba(255,255,255,.18); flex:0 0 auto; position:relative; }
    .icon-record::before { content:""; width:10px; height:10px; border-radius:999px; background:#ffebe7; box-shadow:0 0 0 4px rgba(255,235,231,.18); }
    .icon-stop::before { content:""; width:10px; height:10px; border-radius:2px; background:#fff; }
    .recording-indicator { color:var(--danger); font-weight:750; margin-top:10px; display:none; align-items:center; gap:8px; }
    .recording-indicator::before { content:""; width:10px; height:10px; border-radius:999px; background:var(--danger); animation:pulse 1s ease-in-out infinite; }
    .is-recording .recording-indicator { display:flex; }
    @keyframes pulse { 0%, 100% { transform:scale(1); opacity:.55; } 50% { transform:scale(1.45); opacity:1; } }
  </style>
</head>
<body>
<main>
  <header>
    <h1>FLAIRLAB Event Post Generator</h1>
    <p>Create a session, record or upload voice and media, then refine the post before publishing.</p>
  </header>

  <details id="panelAccess" class="panel" open>
    <summary>Access</summary>
    <div class="panel-body">
    <label for="apiKey">API key</label>
    <input id="apiKey" type="password" autocomplete="off" placeholder="X-API-Key">
    <button class="secondary" onclick="run(saveKeyAndMaybeCreateSession)">Save key</button>
    </div>
  </details>

  <details id="panelKnowledge" class="panel">
    <summary>Knowledge File</summary>
    <div class="panel-body">
    <label for="knowledgeWorkbook">Template/database workbook</label>
    <input id="knowledgeWorkbook" type="file" accept=".xlsm,.xlsx">
    <button id="uploadKnowledgeButton" class="secondary" onclick="run(uploadKnowledgeWorkbook)">Update knowledge file</button>
    <div id="knowledgeSummary" class="summary">Current workbook status will appear here.</div>
    </div>
  </details>

  <details id="panelSession" class="panel" open>
    <summary>1. Session</summary>
    <div class="panel-body">
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
      <div>
        <label for="category">Category</label>
        <input id="category" value="auto event post">
      </div>
    </div>
    <button onclick="run(createSession)">Create session</button>
    <div id="sessionSummary" class="summary">No active session.</div>
    </div>
  </details>

  <details id="panelUpload" class="panel">
    <summary>2. Upload</summary>
    <div class="panel-body">
    <label for="voice">Voice messages</label>
    <div class="recording-controls">
      <button id="startRecordingButton" class="secondary icon-button" onclick="run(startRecording)" type="button"><span class="icon-symbol icon-record" aria-hidden="true"></span><span>Record voice</span></button>
      <button id="stopRecordingButton" class="secondary icon-button" onclick="stopRecording()" disabled type="button"><span class="icon-symbol icon-stop" aria-hidden="true"></span><span>Stop and upload</span></button>
    </div>
    <div id="recordingIndicator" class="recording-indicator">Recording</div>
    <audio id="recordingPlayback" controls style="display:none;width:100%;margin-top:12px;"></audio>
    <input id="voice" type="file" accept="audio/*,video/mp4,video/webm" multiple>
    <label for="images">Pictures</label>
    <input id="images" type="file" accept="image/*" multiple onchange="renderImageChoices()">
    <div id="featuredChoices"></div>
    <div id="imagePreviews" class="image-preview-grid"></div>
    <label for="videos">Video</label>
    <input id="videos" type="file" accept="video/*">
    <button id="uploadButton" onclick="run(uploadFiles)" disabled>Upload files</button>
    </div>
  </details>

  <details id="panelTranscript" class="panel">
    <summary>3. Transcript</summary>
    <div class="panel-body">
    <button id="transcribeButton" onclick="run(transcribe)" disabled>Transcribe voice</button>
    <label for="transcript">Editable transcript</label>
    <textarea id="transcript" placeholder="The transcript will appear here. You can edit it at any moment."></textarea>
    <button id="saveTranscriptButton" class="secondary" onclick="run(saveTranscript)" disabled>Save transcript update</button>
    </div>
  </details>

  <details id="panelDraft" class="panel">
    <summary>4. Draft</summary>
    <div class="panel-body">
    <button id="generateDraftButton" onclick="run(generateDraft)" disabled>Generate draft CSV</button>
    <label>Editable fields</label>
    <div id="draftTable" class="draft-table-wrap summary">Generate a draft to review fields here.</div>
    <textarea id="draftCsv" class="raw-csv" aria-hidden="true"></textarea>
    <button id="saveDraftButton" class="secondary" onclick="run(saveDraft)" disabled>Save draft edits</button>
    <label for="draftChatInput">Ask the agent to revise the draft</label>
    <div id="draftChatLog" class="chat-log summary">Generate a draft, then ask for changes here.</div>
    <textarea id="draftChatInput" placeholder="Example: Build the FAQ section from the facts, add a stronger CTA H2, and make the hero fields more specific."></textarea>
    <button id="sendDraftChatButton" onclick="run(sendDraftChat)" disabled>Send to agent</button>
    </div>
  </details>

  <details id="panelWordPress" class="panel">
    <summary>5. WordPress</summary>
    <div class="panel-body">
    <label for="postStatus">Post status</label>
    <select id="postStatus">
      <option value="draft">draft</option>
      <option value="publish">publish</option>
      <option value="pending">pending</option>
      <option value="private">private</option>
    </select>
    <button id="createPostButton" onclick="run(createWordPressPost)" disabled>Create WordPress post</button>
    <div id="postLinks" class="links"></div>
    </div>
  </details>

  <details id="panelStatus" class="panel" open>
    <summary>Status</summary>
    <div class="panel-body">
    <div id="status" class="status">Ready.</div>
    </div>
  </details>
</main>

<aside id="statusRail" class="status-rail" aria-live="polite">
  <h2>Status</h2>
  <div id="statusRailContent" class="status status-rail-output">Ready.</div>
  <div id="statusRailState" class="status-rail-state">
    <span class="mini-spinner" aria-hidden="true"></span>
    <span id="statusRailStateText">Idle</span>
  </div>
</aside>

<div id="loadingOverlay" class="loading-backdrop" role="status" aria-live="polite" aria-label="Working">
  <div class="loading-box">
    <div class="spinner" aria-hidden="true"></div>
    <strong id="loadingText">Working...</strong>
  </div>
</div>

<div id="resultModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="resultModalTitle">
  <div class="modal">
    <h2 id="resultModalTitle">Post created</h2>
    <div id="resultModalSummary" class="summary"></div>
    <div id="resultModalLinks" class="modal-actions"></div>
  </div>
</div>

<div id="apiKeyModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="apiKeyModalTitle">
  <div class="modal">
    <h2 id="apiKeyModalTitle">API key required</h2>
    <p>Enter the interface API key to start a session.</p>
    <label for="apiKeyModalInput">API key</label>
    <input id="apiKeyModalInput" type="password" autocomplete="off" placeholder="X-API-Key">
    <div class="modal-actions">
      <button type="button" onclick="run(saveKeyFromModal)">Continue</button>
    </div>
  </div>
</div>

<script>
let sessionId = sessionStorage.getItem("flairlab_session_id") || "";
let mediaRecorder = null;
let recordedVoiceBlob = null;
let recordedVoiceName = "";
let recordedChunks = [];
let imagePreviewUrls = [];
document.getElementById("apiKey").value = sessionStorage.getItem("flairlab_api_key") || "";
function key(){ return document.getElementById("apiKey").value.trim(); }
function headers(json=true){ const h = {"X-API-Key": key()}; if(json) h["Content-Type"]="application/json"; return h; }
function status(obj){
  const text = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  document.getElementById("status").textContent = text;
  document.getElementById("statusRailContent").textContent = text;
}
function esc(value){
  return String(value ?? "").replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function actionLabel(fn){
  return ({
    createSession:"Creating session...",
    uploadFiles:"Uploading files...",
    transcribe:"Transcribing voice...",
    saveTranscript:"Saving transcript...",
    generateDraft:"Generating draft...",
    saveDraft:"Saving draft...",
    sendDraftChat:"Updating draft with agent...",
    createWordPressPost:"Creating WordPress post...",
    openSessionLogs:"Opening logs...",
    uploadKnowledgeWorkbook:"Updating knowledge file...",
    startRecording:"Opening microphone...",
    saveKeyFromModal:"Starting..."
  })[fn?.name] || "Working...";
}
let busyCount = 0;
function setBusy(isBusy, label="Working..."){
  busyCount = Math.max(0, busyCount + (isBusy ? 1 : -1));
  const active = busyCount > 0;
  document.body.classList.toggle("is-busy", active);
  document.getElementById("loadingOverlay").classList.toggle("open", active);
  document.getElementById("loadingText").textContent = label;
  document.getElementById("statusRailStateText").textContent = active ? label : "Idle";
}
function openPanel(id, scroll=false){
  const panel = document.getElementById(id);
  if(!panel) return;
  panel.open = true;
  if(scroll) panel.scrollIntoView({behavior:"smooth", block:"start"});
}
function closePanel(id){
  const panel = document.getElementById(id);
  if(panel) panel.open = false;
}
function openWorkflowPanels(data){
  if(!data) return;
  openPanel("panelAccess");
  openPanel("panelSession");
  if(data.session_id) openPanel("panelUpload");
  if(data.files?.voice || data.files?.voices?.length) openPanel("panelTranscript");
  if(data.transcript?.text) openPanel("panelDraft");
  if(data.draft?.csv_text) openPanel("panelWordPress");
  if(data.wordpress_post?.view_url) openPanel("panelStatus");
}
function openPanelsFromCurrentInputs(){
  if(sessionId) openPanel("panelUpload");
  if(document.getElementById("transcript").value.trim()) openPanel("panelDraft");
  if(document.getElementById("draftCsv").value.trim()) openPanel("panelWordPress");
}
function uiCacheKey(){
  return sessionId ? `flairlab_ui_cache_${sessionId}` : "";
}
function collectUiCache(){
  const tableCsv = syncDraftCsvFromTable();
  return {
    client_id: document.getElementById("clientId").value,
    post_type: document.getElementById("postType").value,
    category: document.getElementById("category").value,
    post_status: document.getElementById("postStatus").value,
    transcript_text: document.getElementById("transcript").value,
    draft_csv_text: tableCsv || document.getElementById("draftCsv").value,
    draft_chat_input: document.getElementById("draftChatInput").value,
    knowledge_status: JSON.parse(sessionStorage.getItem("flairlab_knowledge_status") || "null"),
    saved_at: new Date().toISOString()
  };
}
function saveUiCacheLocal(){
  const key = uiCacheKey();
  if(!key) return;
  const cache = collectUiCache();
  if(!cache.transcript_text && !cache.draft_csv_text) return;
  sessionStorage.setItem(key, JSON.stringify(cache));
}
function applyUiCache(cache){
  if(!cache) return;
  if(cache.client_id) document.getElementById("clientId").value = cache.client_id;
  if(cache.post_type) document.getElementById("postType").value = cache.post_type;
  if(cache.category) document.getElementById("category").value = cache.category;
  if(cache.post_status) document.getElementById("postStatus").value = cache.post_status;
  if(cache.transcript_text !== undefined) document.getElementById("transcript").value = cache.transcript_text;
  if(cache.draft_csv_text !== undefined){
    document.getElementById("draftCsv").value = cache.draft_csv_text;
    renderDraftTable(cache.draft_csv_text);
  }
  if(cache.draft_chat_input !== undefined) document.getElementById("draftChatInput").value = cache.draft_chat_input;
  if(cache.knowledge_status) renderKnowledgeStatus(cache.knowledge_status);
}
let uiCacheTimer = null;
async function saveUiCache(){
  if(!sessionId) return;
  saveUiCacheLocal();
  if(!key()) return;
  const cache = collectUiCache();
  await api(`/app/sessions/${sessionId}/ui-cache`, {
    method:"PUT",
    headers:headers(),
    body:JSON.stringify({cache})
  });
}
function scheduleUiCacheSave(){
  saveUiCacheLocal();
  clearTimeout(uiCacheTimer);
  uiCacheTimer = setTimeout(() => {
    saveUiCache().catch(error => console.warn("UI cache save failed", error));
  }, 900);
}
function parseCsv(text){
  const rows = [];
  let row = [], field = "", quoted = false;
  for(let index = 0; index < text.length; index++){
    const char = text[index];
    const next = text[index + 1];
    if(quoted){
      if(char === '"' && next === '"'){ field += '"'; index++; }
      else if(char === '"'){ quoted = false; }
      else { field += char; }
    } else if(char === '"'){
      quoted = true;
    } else if(char === ","){
      row.push(field); field = "";
    } else if(char === "\\n"){
      row.push(field); rows.push(row); row = []; field = "";
    } else if(char !== "\\r"){
      field += char;
    }
  }
  if(field || row.length) { row.push(field); rows.push(row); }
  return rows;
}
function csvEscape(value){
  const text = String(value ?? "");
  return /[",\\n\\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
function csvFromRows(rows){
  return rows.map(row => row.map(csvEscape).join(",")).join("\\n") + "\\n";
}
function renderDraftTable(csvText){
  const target = document.getElementById("draftTable");
  const rows = parseCsv(csvText || "");
  const headers = rows[0] || [];
  const values = rows[1] || [];
  if(!headers.length){
    target.className = "draft-table-wrap summary";
    target.textContent = "Generate a draft to review fields here.";
    return;
  }
  target.className = "draft-table-wrap";
  target.innerHTML = `<table class="draft-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody></tbody></table>`;
  const body = target.querySelector("tbody");
  headers.forEach((header, index) => {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    const value = document.createElement("td");
    const input = document.createElement("textarea");
    name.textContent = header;
    input.dataset.csvField = header;
    input.value = values[index] || "";
    input.addEventListener("input", () => { syncDraftCsvFromTable(); updateButtons(); scheduleUiCacheSave(); });
    value.appendChild(input);
    tr.appendChild(name);
    tr.appendChild(value);
    body.appendChild(tr);
  });
}
function renderKnowledgeStatus(data){
  const target = document.getElementById("knowledgeSummary");
  if(!data){
    target.textContent = "Current workbook status will appear here.";
    return;
  }
  sessionStorage.setItem("flairlab_knowledge_status", JSON.stringify(data));
  target.innerHTML =
    `<strong>Path:</strong> ${esc(data.path || "")}<br>` +
    `<strong>Exists:</strong> ${data.exists ? "yes" : "no"}<br>` +
    `<strong>Sheet:</strong> ${esc(data.loaded_sheet || data.configured_sheet || "")}<br>` +
    `<strong>Guidance rows:</strong> ${esc(data.guidance_items ?? 0)}` +
    `${data.error ? `<br><strong>Error:</strong> ${esc(data.error)}` : ""}`;
}
async function loadKnowledgeStatus(){
  const cached = JSON.parse(sessionStorage.getItem("flairlab_knowledge_status") || "null");
  if(cached) renderKnowledgeStatus(cached);
  if(!key()) return;
  const data = await api("/app/knowledge/status", {headers:headers(false)});
  renderKnowledgeStatus(data);
}
async function uploadKnowledgeWorkbook(){
  const file = document.getElementById("knowledgeWorkbook").files[0];
  if(!file) throw new Error("Select a workbook first.");
  const form = new FormData();
  form.append("workbook", file);
  const data = await api("/app/knowledge/workbook", {method:"POST", headers:{"X-API-Key":key()}, body:form});
  renderKnowledgeStatus(data);
  status(data);
}
function revokeImagePreviewUrls(){
  imagePreviewUrls.forEach(url => URL.revokeObjectURL(url));
  imagePreviewUrls = [];
}
function renderImagePreviewItems(items){
  const wrap = document.getElementById("imagePreviews");
  wrap.innerHTML = "";
  items.forEach(item => {
    const card = document.createElement("div");
    card.className = "image-preview";
    const image = document.createElement("img");
    image.src = item.url;
    image.alt = item.name || "Uploaded image";
    const label = document.createElement("span");
    label.textContent = item.name || "";
    card.appendChild(image);
    card.appendChild(label);
    wrap.appendChild(card);
  });
}
async function renderUploadedImagePreviews(images){
  if(!sessionId || !images?.length || !key()) return;
  revokeImagePreviewUrls();
  const items = [];
  for(const image of images){
    try {
      const response = await fetch(`/app/sessions/${sessionId}/images/${encodeURIComponent(image.filename)}`, {headers:headers(false)});
      if(!response.ok) continue;
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      imagePreviewUrls.push(url);
      items.push({url, name:image.original_filename || image.filename});
    } catch (error) {
      console.warn("Image preview failed", error);
    }
  }
  if(items.length) renderImagePreviewItems(items);
}
async function startRecording(){
  if(!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined"){
    throw new Error("This browser does not support in-app audio recording.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({audio:true});
  recordedChunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.addEventListener("dataavailable", event => {
    if(event.data.size) recordedChunks.push(event.data);
  });
  mediaRecorder.addEventListener("stop", () => {
    stream.getTracks().forEach(track => track.stop());
    recordedVoiceBlob = new Blob(recordedChunks, {type:mediaRecorder.mimeType || "audio/webm"});
    recordedVoiceName = `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.webm`;
    const playback = document.getElementById("recordingPlayback");
    playback.src = URL.createObjectURL(recordedVoiceBlob);
    playback.style.display = "block";
    document.body.classList.remove("is-recording");
    document.getElementById("startRecordingButton").disabled = false;
    document.getElementById("stopRecordingButton").disabled = true;
    status(`Recording ready: ${recordedVoiceName}`);
    uploadRecordedVoiceAndRetranscribe().catch(error => {
      console.error(error);
      status("Error: " + (error?.message || error));
      setBusy(false);
    });
  });
  mediaRecorder.start();
  document.body.classList.add("is-recording");
  document.getElementById("startRecordingButton").disabled = true;
  document.getElementById("stopRecordingButton").disabled = false;
}
function stopRecording(){
  if(mediaRecorder && mediaRecorder.state !== "inactive"){
    setBusy(true, "Uploading recording...");
    mediaRecorder.stop();
  }
}
async function uploadRecordedVoiceAndRetranscribe(){
  if(!recordedVoiceBlob) return;
  if(!key()) {
    showApiKeyModal();
    throw new Error("API key is required before uploading the recording.");
  }
  if(!sessionId) await createSession();
  const form = new FormData();
  form.append("voices", recordedVoiceBlob, recordedVoiceName || "recording.webm");
  const uploadData = await api(`/app/sessions/${sessionId}/uploads`, {method:"POST", headers:{"X-API-Key":key()}, body:form});
  recordedVoiceBlob = null;
  await renderFreshSession(uploadData);
  openPanel("panelTranscript", true);
  status("Recording uploaded. Retranscribing all voice messages...");
  const transcriptData = await api(`/app/sessions/${sessionId}/transcribe`, {method:"POST", headers:headers(false)});
  document.getElementById("transcript").value = transcriptData.transcript?.text || "";
  await renderFreshSession(transcriptData);
  openPanel("panelDraft", true);
  status(transcriptData);
  setBusy(false);
}
function syncDraftCsvFromTable(){
  const fields = [...document.querySelectorAll("[data-csv-field]")];
  if(!fields.length) return document.getElementById("draftCsv").value;
  const headers = fields.map(field => field.dataset.csvField);
  const values = fields.map(field => field.value);
  const csvText = csvFromRows([headers, values]);
  document.getElementById("draftCsv").value = csvText;
  return csvText;
}
function renderDraftChat(chat){
  const target = document.getElementById("draftChatLog");
  if(!chat || !chat.length){
    target.className = "chat-log summary";
    target.textContent = "Generate a draft, then ask for changes here.";
    return;
  }
  target.className = "chat-log";
  target.innerHTML = "";
  chat.forEach(item => {
    const div = document.createElement("div");
    div.className = `chat-message ${item.role === "user" ? "user" : "assistant"}`;
    div.textContent = item.content || "";
    target.appendChild(div);
  });
  target.scrollTop = target.scrollHeight;
}
function logsUrl(){
  return sessionId ? `/app/sessions/${sessionId}/logs` : "";
}
async function openSessionLogs(){
  if(!sessionId) throw new Error("Create a session first.");
  const logWindow = window.open("", "_blank");
  const data = await api(logsUrl(), {headers:headers(false)});
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>Session logs ${esc(sessionId)}</title>` +
    `<style>body{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin:24px;line-height:1.45;color:#1f2933;background:#fff}` +
    `pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;border:1px solid #d8e0e8;border-radius:8px;padding:14px}</style></head>` +
    `<body><h1>Session logs</h1><pre>${esc(JSON.stringify(data, null, 2))}</pre></body></html>`;
  if(logWindow){
    logWindow.document.open();
    logWindow.document.write(html);
    logWindow.document.close();
  } else {
    status(data);
  }
}
function closeResultModal(){
  document.getElementById("resultModal").classList.remove("open");
}
function showApiKeyModal(){
  document.getElementById("apiKeyModalInput").value = key();
  document.getElementById("apiKeyModal").classList.add("open");
  setTimeout(() => document.getElementById("apiKeyModalInput").focus(), 0);
}
function closeApiKeyModal(){
  document.getElementById("apiKeyModal").classList.remove("open");
}
async function saveKeyFromModal(){
  const modalKey = document.getElementById("apiKeyModalInput").value.trim();
  if(!modalKey) throw new Error("API key is required.");
  document.getElementById("apiKey").value = modalKey;
  saveKey();
  closeApiKeyModal();
  if(!sessionId) await createSession();
  else await restoreSession();
}
function showResultModal(post){
  if(!post || !post.post_id) return;
  document.getElementById("resultModalSummary").innerHTML =
    `<strong>Post ID:</strong> ${esc(post.post_id || "")}<br>` +
    `<strong>Status:</strong> ${esc(post.status || "")}<br>` +
    `<strong>Write mode:</strong> ${esc(post.post_write_mode || "")}<br>` +
    `<strong>Output dir:</strong> ${esc(post.output_dir || "")}`;
  const viewLink = post.view_url
    ? `<a href="${esc(post.view_url)}" target="_blank" rel="noopener">View post</a>`
    : "";
  const editLink = post.edit_url
    ? `<a href="${esc(post.edit_url)}" target="_blank" rel="noopener">Edit post</a>`
    : "";
  document.getElementById("resultModalLinks").innerHTML =
    viewLink +
    editLink +
    `<a href="#" class="secondary" onclick="run(openSessionLogs); return false;">Session logs</a>` +
    `<button class="secondary" type="button" onclick="closeResultModal()">Close</button>`;
  document.getElementById("resultModal").classList.add("open");
}
function fileList(files){
  if(!files || files.length === 0) return "none";
  return files.map(file => esc(file.original_filename || file.filename)).join(", ");
}
function cacheWithValues(cache){
  return cache && Object.keys(cache).length ? cache : null;
}
function renderSession(data, options={}){
  if(!data) return;
  document.getElementById("clientId").value = data.client_id || "flairlab";
  document.getElementById("postType").value = data.post_type || "Event";
  document.getElementById("transcript").value = data.transcript?.text || "";
  document.getElementById("draftCsv").value = data.draft?.csv_text || "";
  renderDraftTable(data.draft?.csv_text || "");
  renderDraftChat(data.draft?.chat || []);
  if(data.draft?.category) document.getElementById("category").value = data.draft.category;
  const files = data.files || {};
  const featured = files.featured_image_filename || "none";
  const post = data.wordpress_post || {};
  document.getElementById("postLinks").innerHTML = post.post_id
    ? `${post.view_url ? `<a href="${esc(post.view_url)}" target="_blank" rel="noopener">View post</a>` : ""}${post.edit_url ? `<a href="${esc(post.edit_url)}" target="_blank" rel="noopener">Edit post</a>` : ""}<a href="#" onclick="run(openSessionLogs); return false;">Session logs</a>`
    : "";
  document.getElementById("sessionSummary").innerHTML =
    `<strong>Session:</strong> ${esc(data.session_id)}<br>` +
    `<strong>Status:</strong> ${esc(data.status || "created")}<br>` +
    `<strong>Voice:</strong> ${fileList(files.voices || (files.voice ? [files.voice] : []))}<br>` +
    `<strong>Pictures:</strong> ${fileList(files.images)}<br>` +
    `<strong>Featured:</strong> ${esc(featured)}<br>` +
    `<strong>Video:</strong> ${fileList(files.videos)}`;
  renderUploadedImagePreviews(files.images || []);
  openWorkflowPanels(data);
  if(options.applyCache !== false){
    const localCache = uiCacheKey() ? JSON.parse(sessionStorage.getItem(uiCacheKey()) || "null") : null;
    applyUiCache(cacheWithValues(data.ui_cache) || localCache);
    openPanelsFromCurrentInputs();
  }
  updateButtons();
}
async function renderFreshSession(data){
  renderSession(data, {applyCache:false});
  saveUiCache().catch(error => console.warn("UI cache save failed", error));
}
function updateButtons(){
  const hasSession = !!sessionId;
  const hasTranscript = !!document.getElementById("transcript").value.trim();
  const hasDraft = !!document.getElementById("draftCsv").value.trim();
  const hasChatMessage = !!document.getElementById("draftChatInput").value.trim();
  document.getElementById("uploadButton").disabled = !hasSession;
  document.getElementById("transcribeButton").disabled = !hasSession;
  document.getElementById("saveTranscriptButton").disabled = !hasSession || !hasTranscript;
  document.getElementById("generateDraftButton").disabled = !hasSession || !hasTranscript;
  document.getElementById("saveDraftButton").disabled = !hasSession || !hasDraft;
  document.getElementById("sendDraftChatButton").disabled = !hasSession || !hasDraft || !hasChatMessage;
  document.getElementById("createPostButton").disabled = !hasSession || !hasDraft;
}
async function restoreSession(){
  if(!sessionId || !key()) {
    updateButtons();
    return;
  }
  try {
    const data = await api(`/app/sessions/${sessionId}`, {headers:headers(false)});
    renderSession(data);
    status(data);
  } catch (error) {
    console.warn(error);
    const localCache = uiCacheKey() ? JSON.parse(sessionStorage.getItem(uiCacheKey()) || "null") : null;
    applyUiCache(localCache);
    openPanelsFromCurrentInputs();
    status("Server session could not be restored, but local cached edits were kept in this browser.");
  } finally {
    updateButtons();
  }
}
async function initializeApp(){
  updateButtons();
  await loadKnowledgeStatus().catch(error => console.warn(error));
  if(!key()){
    openPanel("panelAccess", true);
    showApiKeyModal();
    status("Enter your API key to start.");
    return;
  }
  if(sessionId){
    await restoreSession();
    return;
  }
  await createSession();
}
async function run(fn){
  setBusy(true, actionLabel(fn));
  try {
    await fn();
  } catch (error) {
    console.error(error);
    status("Error: " + (error?.message || error));
  } finally {
    setBusy(false);
    updateButtons();
  }
}
function saveKey(){ sessionStorage.setItem("flairlab_api_key", key()); status("API key saved in this browser session."); loadKnowledgeStatus().catch(error => console.warn(error)); }
async function saveKeyAndMaybeCreateSession(){
  saveKey();
  if(!sessionId && key()) await createSession();
}
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
  await renderFreshSession(data);
  openPanel("panelUpload", true);
  status(data);
  updateButtons();
}
function renderImageChoices(){
  const wrap = document.getElementById("featuredChoices");
  wrap.innerHTML = "";
  const files = [...document.getElementById("images").files];
  revokeImagePreviewUrls();
  renderImagePreviewItems(files.map(file => {
    const url = URL.createObjectURL(file);
    imagePreviewUrls.push(url);
    return {url, name:file.name};
  }));
  files.forEach((file, index) => {
    const row = document.createElement("label");
    row.className = "image-choice";
    row.innerHTML = `<input type="radio" name="featured" value="${file.name}" ${index===0 ? "checked" : ""}><span>${file.name}</span>`;
    wrap.appendChild(row);
  });
}
async function uploadFiles(){
  if(!sessionId) throw new Error("Create a session first.");
  const form = new FormData();
  const voices = [...document.getElementById("voice").files];
  if(!voices.length && !recordedVoiceBlob) throw new Error("Select or record at least one voice file.");
  if(recordedVoiceBlob) form.append("voices", recordedVoiceBlob, recordedVoiceName || "recording.webm");
  voices.forEach(file => form.append("voices", file));
  [...document.getElementById("images").files].forEach(f => form.append("images", f));
  const video = document.getElementById("videos").files[0];
  if(video) form.append("videos", video);
  const featured = document.querySelector("input[name='featured']:checked");
  if(featured) form.append("featured_image_filename", featured.value);
  const data = await api(`/app/sessions/${sessionId}/uploads`, {method:"POST", headers:{"X-API-Key":key()}, body:form});
  await renderFreshSession(data);
  openPanel("panelTranscript", true);
  status("Voice uploaded. Retranscribing all voice messages...");
  const transcriptData = await api(`/app/sessions/${sessionId}/transcribe`, {method:"POST", headers:headers(false)});
  document.getElementById("transcript").value = transcriptData.transcript?.text || "";
  await renderFreshSession(transcriptData);
  openPanel("panelDraft", true);
  status(transcriptData);
  updateButtons();
}
async function transcribe(){
  if(!sessionId) throw new Error("Create a session first.");
  status("Transcribing...");
  const data = await api(`/app/sessions/${sessionId}/transcribe`, {method:"POST", headers:headers(false)});
  document.getElementById("transcript").value = data.transcript?.text || "";
  await renderFreshSession(data);
  openPanel("panelDraft", true);
  status(data);
  updateButtons();
}
async function saveTranscript(){
  if(!sessionId) throw new Error("Create a session first.");
  const data = await api(`/app/sessions/${sessionId}/transcript`, {
    method:"PUT",
    headers:headers(),
    body:JSON.stringify({text:document.getElementById("transcript").value})
  });
  await renderFreshSession(data);
  openPanel("panelDraft", true);
  status(data);
  updateButtons();
}
async function generateDraft(){
  if(!sessionId) throw new Error("Create a session first.");
  if(!document.getElementById("transcript").value.trim()) throw new Error("Transcribe or enter notes first.");
  status("Generating draft CSV...");
  const data = await api(`/app/sessions/${sessionId}/draft`, {
    method:"POST",
    headers:headers(),
    body:JSON.stringify({category:document.getElementById("category").value || "auto event post"})
  });
  await renderFreshSession(data);
  openPanel("panelDraft", true);
  status(data);
  updateButtons();
}
async function saveDraft(){
  if(!sessionId) throw new Error("Create a session first.");
  const csvText = syncDraftCsvFromTable();
  const data = await api(`/app/sessions/${sessionId}/draft`, {
    method:"PUT",
    headers:headers(),
    body:JSON.stringify({csv_text:csvText})
  });
  await renderFreshSession(data);
  openPanel("panelDraft", true);
  status(data);
  updateButtons();
}
async function sendDraftChat(){
  if(!sessionId) throw new Error("Create a session first.");
  const message = document.getElementById("draftChatInput").value.trim();
  if(!message) throw new Error("Write a message for the draft agent.");
  await saveDraft();
  status("Updating draft with agent...");
  const data = await api(`/app/sessions/${sessionId}/draft/chat`, {
    method:"POST",
    headers:headers(),
    body:JSON.stringify({message})
  });
  document.getElementById("draftChatInput").value = "";
  await renderFreshSession(data);
  openPanel("panelDraft", true);
  status(data);
  updateButtons();
}
async function createWordPressPost(){
  if(!sessionId) throw new Error("Create a session first.");
  syncDraftCsvFromTable();
  status("Creating WordPress post...");
  await saveDraft();
  const data = await api(`/app/sessions/${sessionId}/wordpress-post`, {
    method:"POST",
    headers:headers(),
    body:JSON.stringify({status:document.getElementById("postStatus").value, existing_post_mode:"update"})
  });
  showResultModal(data.wordpress_post);
  await renderFreshSession(data);
  openPanel("panelWordPress", true);
  status(data);
  updateButtons();
}
document.getElementById("resultModal").addEventListener("click", event => {
  if(event.target.id === "resultModal") closeResultModal();
});
document.getElementById("apiKeyModalInput").addEventListener("keydown", event => {
  if(event.key === "Enter") run(saveKeyFromModal);
});
["clientId", "postType", "category", "postStatus", "transcript", "draftChatInput"].forEach(id => {
  document.getElementById(id).addEventListener("input", () => { updateButtons(); scheduleUiCacheSave(); });
  document.getElementById(id).addEventListener("change", () => { updateButtons(); scheduleUiCacheSave(); });
});
window.addEventListener("error", e => status("Error: " + e.message));
window.addEventListener("unhandledrejection", e => status("Error: " + (e.reason?.message || e.reason)));
initializeApp().catch(error => {
  console.error(error);
  status("Error: " + (error?.message || error));
});
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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


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


@app.get("/app/knowledge/status")
def get_knowledge_status(_: None = Depends(verify_api_key)) -> dict[str, Any]:
    return knowledge_status_payload()


@app.post("/app/knowledge/workbook")
async def upload_knowledge_workbook(
    workbook: UploadFile = File(...),
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    filename = safe_upload_name(workbook.filename, "knowledge_workbook.xlsm")
    suffix = Path(filename).suffix.lower()
    if suffix not in WORKBOOK_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload an .xlsm or .xlsx workbook.")

    destination = active_knowledge_workbook_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.stem}.uploading{suffix}")

    with temporary.open("wb") as output:
        while chunk := await workbook.read(1024 * 1024):
            output.write(chunk)

    guidance = load_workbook_guidance(temporary, KNOWLEDGE_WORKBOOK_SHEET)
    if guidance.get("error") or not guidance.get("items"):
        temporary.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=guidance.get("error") or "Workbook did not expose any AI guidance rows.",
        )

    if destination.exists():
        backup = destination.with_suffix(destination.suffix + ".bak")
        destination.replace(backup)
    temporary.replace(destination)
    return {
        "success": True,
        "message": "Knowledge workbook updated.",
        **knowledge_status_payload(),
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


@app.get("/app/sessions/{session_id}/logs")
def get_session_logs(
    session_id: str,
    _: None = Depends(verify_api_key),
) -> dict[str, Any]:
    state = read_session_state(session_id)
    session_dir = APP_SESSION_ROOT / session_id
    wordpress_post = state.get("wordpress_post", {})
    output_dir_value = wordpress_post.get("output_dir")
    output_dir = Path(output_dir_value) if output_dir_value else None

    import_logs: dict[str, Any] = {}
    if output_dir and output_dir.exists():
        for filename in (
            "technical_log.json",
            "warnings.json",
            "created_post.json",
            "wordpress_create_payload.json",
            "wordpress_payload_preview.json",
            "acf_payload.json",
            "advanced_custom_fields_update_response.json",
            "media_upload_plan.json",
            "media_upload_cache.json",
        ):
            value = read_json_if_exists(output_dir / filename)
            if value is not None:
                import_logs[filename] = value
    cache_dir = session_dir / "cache"
    cache_files: dict[str, Any] = {}
    if cache_dir.exists():
        for path in sorted(cache_dir.iterdir()):
            if path.suffix == ".json":
                cache_files[path.name] = read_json_if_exists(path)
            elif path.is_file():
                cache_files[path.name] = path.read_text(encoding="utf-8")

    return {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "state": state,
        "ui_cache": state.get("ui_cache", {}),
        "cache_files": cache_files,
        "draft_csv": state.get("draft", {}).get("csv_text"),
        "wordpress_import_output_dir": str(output_dir) if output_dir else None,
        "wordpress_import_logs": import_logs,
    }


@app.get("/app/sessions/{session_id}/images/{filename}")
def get_session_image(
    session_id: str,
    filename: str,
    _: None = Depends(verify_api_key),
) -> FileResponse:
    state = read_session_state(session_id)
    images = state.get("files", {}).get("images", [])
    match = next((item for item in images if item.get("filename") == filename), None)
    if not match:
        raise HTTPException(status_code=404, detail="Image not found in this session.")
    path = Path(match["path"])
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Image file is missing.")
    return FileResponse(path)


@app.put("/app/sessions/{session_id}/ui-cache", response_model=SessionStateResponse)
def update_session_ui_cache(
    session_id: str,
    payload: UiCacheUpdateRequest,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    state["ui_cache"] = {
        **payload.cache,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/app/sessions/{session_id}/uploads", response_model=SessionStateResponse)
async def upload_session_files(
    session_id: str,
    voices: list[UploadFile] | None = File(default=None),
    images: list[UploadFile] | None = File(default=None),
    videos: list[UploadFile] | None = File(default=None),
    featured_image_filename: str | None = Form(default=None),
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    session_dir = APP_SESSION_ROOT / session_id
    existing_files = state.get("files", {})

    voice_infos = list(existing_files.get("voices") or ([existing_files["voice"]] if existing_files.get("voice") else []))
    for index, voice in enumerate(voices or [], start=1):
        voice_info = save_upload_file(voice, session_dir / "voice", f"voice_{len(voice_infos) + index}")
        validate_extension(voice_info, AUDIO_EXTENSIONS, "voice")
        voice_infos.append(voice_info)
    if not voice_infos:
        raise HTTPException(status_code=400, detail="Upload at least one voice file.")

    image_infos = []
    for index, image in enumerate(images or [], start=1):
        image_info = save_upload_file(image, session_dir / "images", f"image_{index}.jpg")
        validate_extension(image_info, IMAGE_EXTENSIONS, "image")
        image_infos.append(image_info)
    if not image_infos:
        image_infos = list(existing_files.get("images", []))

    video_infos = []
    for index, video in enumerate(videos or [], start=1):
        video_info = save_upload_file(video, session_dir / "videos", f"video_{index}.mp4")
        validate_extension(video_info, VIDEO_EXTENSIONS, "video")
        video_infos.append(video_info)
    if not video_infos:
        video_infos = list(existing_files.get("videos", []))

    if len(video_infos) > 1:
        raise HTTPException(status_code=400, detail="Only one video per post is supported for now.")

    if featured_image_filename:
        featured_match = next(
            (
                item
                for item in image_infos
                if item["original_filename"] == featured_image_filename
                or item["filename"] == safe_upload_name(featured_image_filename, "featured_image")
            ),
            None,
        )
        if not featured_match:
            raise HTTPException(status_code=400, detail="Featured image must match one uploaded image filename.")
        featured_image_filename = featured_match["filename"]

    effective_featured_image = featured_image_filename or existing_files.get("featured_image_filename")
    state["files"] = {
        "voice": voice_infos[0],
        "voices": voice_infos,
        "images": image_infos,
        "videos": video_infos,
        "featured_image_filename": effective_featured_image,
    }
    state["status"] = "files_uploaded"
    state["steps"]["upload_voice_and_media"] = "complete"
    state["steps"]["select_featured_image"] = "complete" if effective_featured_image else "pending"
    state["steps"]["transcribe_voice"] = "pending"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/app/sessions/{session_id}/transcribe", response_model=SessionStateResponse)
def transcribe_session_voice(
    session_id: str,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    files = state.get("files", {})
    voices = files.get("voices") or ([files["voice"]] if files.get("voice") else [])
    if not voices:
        raise HTTPException(status_code=400, detail="Upload a voice file before transcription.")

    transcript_parts = []
    transcript_items = []
    for index, voice in enumerate(voices, start=1):
        text = transcribe_audio_file(voice["path"], model=DEFAULT_TRANSCRIPTION_MODEL)
        transcript_parts.append(text.strip())
        transcript_items.append({
            "index": index,
            "filename": voice.get("original_filename") or voice.get("filename"),
            "text": text,
        })
    transcript_text = "\n\n".join(part for part in transcript_parts if part)
    state["transcript"] = {
        "text": transcript_text,
        "source": "openai_transcription",
        "model": DEFAULT_TRANSCRIPTION_MODEL,
        "items": transcript_items,
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


@app.post("/app/sessions/{session_id}/draft", response_model=SessionStateResponse)
async def generate_session_draft(
    session_id: str,
    payload: DraftGenerateRequest,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    session_dir = APP_SESSION_ROOT / session_id
    if not state.get("files", {}).get("images"):
        raise HTTPException(status_code=400, detail="Upload at least one image before generating a draft.")

    try:
        specs = await run_in_threadpool(load_helper_specs)
        draft = await run_in_threadpool(create_session_draft, session_dir, state, specs, payload.category)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not generate draft: {exc}") from exc

    state["draft"] = draft
    state["status"] = "draft_generated"
    state["steps"]["refine_with_ai_chat"] = "complete"
    state["steps"]["approve_csv"] = "pending"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.put("/app/sessions/{session_id}/draft", response_model=SessionStateResponse)
def update_session_draft(
    session_id: str,
    payload: DraftUpdateRequest,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    if not state.get("draft"):
        raise HTTPException(status_code=400, detail="Generate a draft before saving draft edits.")

    session_dir = APP_SESSION_ROOT / session_id
    zip_path = rebuild_session_package(session_dir, payload.csv_text, state)
    state["draft"]["csv_text"] = payload.csv_text
    state["draft"]["zip_path"] = str(zip_path)
    state["draft"]["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["status"] = "draft_updated"
    state["steps"]["approve_csv"] = "pending"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/app/sessions/{session_id}/draft/chat", response_model=SessionStateResponse)
async def chat_with_draft_agent(
    session_id: str,
    payload: DraftChatRequest,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Chat message is required.")

    state = read_session_state(session_id)
    if not state.get("draft"):
        raise HTTPException(status_code=400, detail="Generate a draft before chatting with the draft agent.")

    session_dir = APP_SESSION_ROOT / session_id
    try:
        specs = await run_in_threadpool(load_helper_specs)
        draft = await run_in_threadpool(revise_session_draft, session_dir, state, specs, message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not revise draft: {exc}") from exc

    state["draft"] = draft
    state["status"] = "draft_revised"
    state["steps"]["refine_with_ai_chat"] = "complete"
    state["steps"]["approve_csv"] = "pending"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/app/sessions/{session_id}/wordpress-post", response_model=SessionStateResponse)
async def create_session_wordpress_post(
    session_id: str,
    payload: CreateWordPressPostRequest,
    _: None = Depends(verify_api_key),
) -> SessionStateResponse:
    state = read_session_state(session_id)
    draft = state.get("draft", {})
    csv_text = draft.get("csv_text")
    if not csv_text:
        raise HTTPException(status_code=400, detail="Generate and approve a draft before creating the post.")

    session_dir = APP_SESSION_ROOT / session_id
    zip_path = rebuild_session_package(session_dir, csv_text, state)
    allowed_statuses = {"draft", "publish", "pending", "private"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Unsupported post status: {payload.status}")

    args = build_import_args(
        zip_path=zip_path,
        event_name=session_id,
        status=payload.status,
        row=0,
        required_category="auto event post",
        existing_post_mode=payload.existing_post_mode,
        client_id=state.get("client_id", "flairlab"),
    )
    args.output_root = APP_SESSION_ROOT / session_id / "wordpress_imports"

    try:
        output_dir = await run_in_threadpool(run_import, args)
        post_response = await run_in_threadpool(post_response_from_output, output_dir, state.get("client_id", "flairlab"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not create WordPress post: {exc}") from exc

    state["draft"]["zip_path"] = str(zip_path)
    state["wordpress_post"] = post_response
    state["status"] = "wordpress_post_created"
    state["steps"]["approve_csv"] = "complete"
    state["steps"]["create_wordpress_post"] = "complete"
    write_session_state(session_id, state)
    return SessionStateResponse(**state)


@app.post("/event-posts/from-zip")
async def action_event_post_from_zip(
    payload: EventPostActionRequest,
    _: None = Depends(verify_api_key),
):
    return await import_event_post_from_zip(payload)


app.mount("/action", action_app)
