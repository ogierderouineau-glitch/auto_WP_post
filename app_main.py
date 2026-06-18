import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
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
