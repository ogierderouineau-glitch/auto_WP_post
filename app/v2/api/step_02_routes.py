from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from datetime import datetime, timezone
import os
import tempfile
from pathlib import Path
from typing import Any
import traceback
import uuid

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.v2.api.step_01_models import (
    AnswersRequest,
    ApproveRequest,
    CreateSessionRequest,
    DraftChatRequest,
    FeaturedImageRequest,
    GenerateRequest,
    ImageOptimizationRequest,
    ImageMetadataUpdateRequest,
    InputsRequest,
    PublishRequest,
    SessionResponse,
    SessionsDeleteRequest,
    VersionedRequest,
)
from config import KNOWLEDGE_SOURCE_POLICY, KNOWLEDGE_WORKBOOK_GCS_URI
from app.v2.errors import InvalidUploadError, SessionOwnershipError, V2Error
from app.v2.sessions.step_03_service import ContentSessionService
from app.v2.storage.step_02_uploads import safe_upload_name, validate_upload


_SESSION_JOBS: dict[str, dict[str, Any]] = {}
_SESSION_JOB_EXECUTOR = ThreadPoolExecutor(
    max_workers=int(os.getenv("V2_SESSION_JOB_WORKERS", "2"))
)


def create_router(
    service_provider: Callable[[], ContentSessionService],
    auth_dependency: Callable[..., Any] | None = None,
    readiness_provider: Callable[[], dict[str, Any]] | None = None,
) -> APIRouter:
    dependencies = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(prefix="/api/content-sessions", tags=["V2 content sessions"], dependencies=dependencies)

    @router.post("", response_model=SessionResponse, status_code=201)
    async def create_session(
        payload: CreateSessionRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        if not x_user_id or x_user_id != payload.user_id:
            raise SessionOwnershipError(
                "X-User-ID must match the session user_id."
            )
        return SessionResponse(session=service_provider().create(**payload.model_dump()))

    @router.get("/_workbook")
    async def workbook_status(
        post_type_key: str | None = Query(default=None),
    ) -> dict[str, Any]:
        snapshot = service_provider().knowledge.current()
        selectable_post_types = [
            row
            for row in snapshot.post_types
            if row.enabled and row.user_selectable
        ]
        enabled_post_types = [row for row in snapshot.post_types if row.enabled]
        post_types = selectable_post_types or enabled_post_types
        selected_post_type = (
            snapshot.post_type(post_type_key)
            if post_type_key
            else None
        )
        if (
            selected_post_type is None
            or not selected_post_type.enabled
            or (selectable_post_types and not selected_post_type.user_selectable)
        ):
            selected_post_type = post_types[0] if post_types else None
        selected_post_type_key = selected_post_type.post_type_key if selected_post_type else None
        return {
            **snapshot.version.model_dump(mode="json"),
            "storage_mode": "gcs" if KNOWLEDGE_WORKBOOK_GCS_URI else "local_file",
            "knowledge_source_policy": KNOWLEDGE_SOURCE_POLICY or "auto",
            "gcs_uri": KNOWLEDGE_WORKBOOK_GCS_URI or None,
            "selected_post_type_key": selected_post_type_key,
            "post_types": [
                {
                    "post_type_key": row.post_type_key,
                    "display_name_de": row.display_name_de,
                    "wp_category_name": row.wp_category_name,
                    "default_language": row.default_language,
                    "generation_enabled": row.generation_enabled,
                    "template_ready": row.template_ready,
                    "description_de": row.description_de,
                }
                for row in post_types
            ],
            "acf_guidance_list": _legacy_acf_guidance_list(snapshot),
            "fact_schema": [
                {
                    "field_key": row.field_key,
                    "label": row.description_de or row.field_key,
                    "required": bool(row.required_for_analysis),
                }
                for row in snapshot.acf_fields
                if row.enabled
                and row.post_type_key == selected_post_type_key
                and row.field_role == "input_fact"
            ],
        }

    @router.post("/_workbook/reload")
    async def reload_workbook() -> dict[str, Any]:
        version = service_provider().knowledge.reload().version
        return version.model_dump(mode="json")

    @router.get("/_readiness")
    async def readiness() -> dict[str, Any]:
        if readiness_provider is None:
            return {"ready": False, "reason": "readiness_provider_not_configured"}
        return readiness_provider()

    @router.get("/recent")
    async def recent_sessions(
        client_id: str | None = Query(default=None),
        post_type: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=200),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> dict[str, Any]:
        return {
            "sessions": service_provider().list_recent(
                user_id=x_user_id,
                client_id=client_id,
                post_type=post_type,
                status=status,
                limit=limit,
            )
        }

    @router.post("/delete")
    async def delete_sessions(
        payload: SessionsDeleteRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> dict[str, Any]:
        return service_provider().delete_many(
            session_ids=payload.session_ids,
            user_id=x_user_id,
        )

    @router.get("/{session_id}", response_model=SessionResponse)
    async def get_session(
        session_id: str,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(session=service_provider().get(session_id))

    @router.post("/{session_id}/inputs", response_model=SessionResponse)
    async def add_inputs(
        session_id: str,
        payload: InputsRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().add_inputs(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/uploads", response_model=SessionResponse)
    async def upload(
        session_id: str,
        expected_version: int = Form(...),
        kind: str = Form(..., pattern="^(audio|image)$"),
        use_vision: bool = Form(default=True),
        upload: UploadFile = File(...),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        suffix = Path(upload.filename or "").suffix
        safe_name = safe_upload_name(upload.filename or "", suffix or ".bin")
        max_bytes = int(
            os.getenv(
                "V2_MAX_IMAGE_BYTES" if kind == "image" else "V2_MAX_AUDIO_BYTES",
                str(20 * 1024 * 1024 if kind == "image" else 50 * 1024 * 1024),
            )
        )
        fd, temporary_name = tempfile.mkstemp(prefix="v2-upload-", suffix=Path(safe_name).suffix)
        try:
            size = 0
            with os.fdopen(fd, "wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise InvalidUploadError(
                            f"Upload exceeds the {max_bytes}-byte limit."
                        )
                    handle.write(chunk)
            temporary = Path(temporary_name)
            try:
                content_type = validate_upload(
                    temporary,
                    kind=kind,
                    declared_content_type=upload.content_type,
                    max_bytes=max_bytes,
                )
            except ValueError as exc:
                raise InvalidUploadError(str(exc)) from exc
            session = service_provider().attach_upload(
                session_id,
                source=temporary,
                kind=kind,
                filename=safe_name,
                content_type=content_type,
                expected_version=expected_version,
                use_vision=use_vision,
            )
            return SessionResponse(session=session)
        finally:
            await upload.close()
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @router.post("/{session_id}/draft-chat/transcribe")
    async def transcribe_draft_chat_voice(
        session_id: str,
        upload: UploadFile = File(...),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> dict[str, str]:
        service_provider().require_owner(session_id, x_user_id)
        service = service_provider()
        if service.speech_to_text is None:
            raise RuntimeError("A V2 SpeechToTextProvider is not configured.")
        suffix = Path(upload.filename or "").suffix or ".webm"
        safe_name = safe_upload_name(upload.filename or "", suffix)
        max_bytes = int(os.getenv("V2_MAX_AUDIO_BYTES", str(50 * 1024 * 1024)))
        fd, temporary_name = tempfile.mkstemp(prefix="v2-draft-chat-", suffix=Path(safe_name).suffix)
        try:
            size = 0
            with os.fdopen(fd, "wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise InvalidUploadError(
                            f"Upload exceeds the {max_bytes}-byte limit."
                        )
                    handle.write(chunk)
            temporary = Path(temporary_name)
            try:
                validate_upload(
                    temporary,
                    kind="audio",
                    declared_content_type=upload.content_type,
                    max_bytes=max_bytes,
                )
            except ValueError as exc:
                raise InvalidUploadError(str(exc)) from exc
            return {"text": service.speech_to_text.transcribe(temporary)}
        finally:
            await upload.close()
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @router.post("/{session_id}/analyze", response_model=SessionResponse)
    async def analyze(
        session_id: str,
        payload: VersionedRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().analyze(
                session_id,
                expected_version=payload.expected_version,
            )
        )

    @router.post("/{session_id}/answers", response_model=SessionResponse)
    async def answer(
        session_id: str,
        payload: AnswersRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().answer(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/generate", response_model=SessionResponse)
    async def generate(
        session_id: str,
        payload: GenerateRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().generate(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/generate-job")
    async def start_generate_job(
        session_id: str,
        payload: GenerateRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> dict[str, Any]:
        service_provider().require_owner(session_id, x_user_id)
        job = _create_session_job(session_id, "generate")
        _SESSION_JOB_EXECUTOR.submit(
            _run_session_job,
            job["job_id"],
            service_provider,
            session_id,
            "generate",
            payload.model_dump(),
        )
        return job

    @router.post("/{session_id}/draft-chat", response_model=SessionResponse)
    async def draft_chat(
        session_id: str,
        payload: DraftChatRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        data = payload.model_dump()
        message = str(data.pop("message", "")).strip()
        if not message:
            raise InvalidUploadError("Draft chat message is required.")
        data["revision_instruction"] = message
        session = service_provider().generate(session_id, **data)
        chat = [
            *session.draft_chat,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": "Entwurf wurde anhand deiner Nachricht strukturiert aktualisiert.",
            },
        ]
        session = service_provider().repository.save(
            session.model_copy(update={"draft_chat": chat}),
            expected_version=session.version,
        )
        return SessionResponse(session=session)

    @router.get("/jobs/{job_id}")
    async def session_job(job_id: str) -> dict[str, Any]:
        return _SESSION_JOBS.get(
            job_id,
            {
                "job_id": job_id,
                "status": "not_found",
                "error": "Job not found. It may belong to a previous server process.",
            },
        )

    @router.get("/{session_id}/preview", response_model=SessionResponse)
    async def preview(
        session_id: str,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(session=service_provider().get(session_id))

    @router.post("/{session_id}/approve", response_model=SessionResponse)
    async def approve(
        session_id: str,
        payload: ApproveRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().approve(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/publish", response_model=SessionResponse)
    async def publish(
        session_id: str,
        payload: PublishRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().publish(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/publish-job")
    async def start_publish_job(
        session_id: str,
        payload: PublishRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> dict[str, Any]:
        service_provider().require_owner(session_id, x_user_id)
        job = _create_session_job(session_id, "publish")
        _SESSION_JOB_EXECUTOR.submit(
            _run_session_job,
            job["job_id"],
            service_provider,
            session_id,
            "publish",
            payload.model_dump(),
        )
        return job

    @router.put("/{session_id}/image-metadata", response_model=SessionResponse)
    async def update_image_metadata(
        session_id: str,
        payload: ImageMetadataUpdateRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().update_image_metadata(session_id, **payload.model_dump())
        )

    @router.put("/{session_id}/featured-image", response_model=SessionResponse)
    async def update_featured_image(
        session_id: str,
        payload: FeaturedImageRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().set_featured_image(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/images/optimize", response_model=SessionResponse)
    async def optimize_image(
        session_id: str,
        payload: ImageOptimizationRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().optimize_image(session_id, **payload.model_dump())
        )

    @router.post("/{session_id}/images/restore-original", response_model=SessionResponse)
    async def restore_image_original(
        session_id: str,
        payload: VersionedRequest,
        filename: str = Query(...),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().restore_image_original(
                session_id,
                filename=filename,
                expected_version=payload.expected_version,
            )
        )

    @router.get("/{session_id}/media/images/{filename}")
    async def get_image(
        session_id: str,
        filename: str,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> FileResponse:
        service_provider().require_owner(session_id, x_user_id)
        path = service_provider().media_path(session_id, kind="image", filename=filename)
        return FileResponse(path)

    @router.get("/{session_id}/media/images/{filename}/original")
    async def get_original_image(
        session_id: str,
        filename: str,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> FileResponse:
        service_provider().require_owner(session_id, x_user_id)
        path = service_provider().media_path(
            session_id,
            kind="image",
            filename=filename,
            original=True,
        )
        return FileResponse(path)

    @router.delete("/{session_id}/media/{kind}/{filename}", response_model=SessionResponse)
    async def remove_media(
        session_id: str,
        kind: str,
        filename: str,
        payload: VersionedRequest,
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    ) -> SessionResponse:
        service_provider().require_owner(session_id, x_user_id)
        return SessionResponse(
            session=service_provider().remove_media(
                session_id,
                kind=kind,
                filename=filename,
                expected_version=payload.expected_version,
            )
        )

    return router


def _legacy_acf_guidance_list(snapshot: Any) -> list[dict[str, str]]:
    """Expose V2 workbook routing in the shape the familiar UI already reads."""

    rows: list[dict[str, str]] = []
    for row in snapshot.shared_fields:
        if not row.enabled or row.destination_type != "acf" or not row.destination_key:
            continue
        rows.append(
            {
                "user_field": row.field_key,
                "user_field_name": row.field_key,
                "acf_field": row.destination_key,
                "acf_field_name": row.destination_key,
                "guidance": row.description_de or "",
                "ai_guidance": row.description_de or "",
            }
        )
    for row in snapshot.acf_fields:
        if not row.enabled or not row.acf_field_name:
            continue
        rows.append(
            {
                "user_field": row.field_key,
                "user_field_name": row.field_key,
                "acf_field": row.acf_field_name,
                "acf_field_name": row.acf_field_name,
                "guidance": row.guidance_de or row.description_de or "",
                "ai_guidance": row.guidance_de or row.description_de or "",
            }
        )
    return rows


def _create_session_job(session_id: str, operation: str) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "job_id": job_id,
        "session_id": session_id,
        "operation": operation,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "session": None,
        "error": None,
    }
    _SESSION_JOBS[job_id] = job
    return job


def _run_session_job(
    job_id: str,
    service_provider: Callable[[], ContentSessionService],
    session_id: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    job = _SESSION_JOBS[job_id]
    job["status"] = "running"
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        service = service_provider()
        if operation == "generate":
            session = service.generate(session_id, **payload)
        elif operation == "publish":
            session = service.publish(session_id, **payload)
        else:
            raise ValueError(f"Unsupported session job operation: {operation}")
        job["status"] = "complete"
        job["session"] = session.model_dump(mode="json")
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        job["traceback"] = traceback.format_exc(limit=5)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()


async def v2_error_handler(_request: Request, exc: V2Error) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.as_dict())
