from __future__ import annotations

import os
from pathlib import Path
import tempfile
from threading import RLock

from google.cloud import storage as gcs_storage

from backend.app.knowledge_base.step_04_service import KnowledgeBaseService
from backend.app.knowledge_base.step_02_loader import WorkbookLoader
from backend.app.knowledge_base.step_03_validator import WorkbookValidator
from backend.app.images.step_02_processor import PillowProcessor
from backend.app.providers.step_02_openai import (
    OpenAIImageEditingProvider,
    OpenAILanguageModelProvider,
    OpenAISpeechToTextProvider,
    OpenAIVisionProvider,
)
from backend.app.providers.step_03_wordpress import ExistingWordPressProvider
from backend.app.sessions.step_01_repository import FileSessionRepository
from backend.app.sessions.step_04_gcs_repository import GCSSessionRepository
from backend.app.sessions.step_03_service import ContentSessionService
from backend.app.storage.step_01_local import LocalObjectStorageProvider
from backend.app.storage.step_03_gcs import GCSObjectStorageProvider
from backend.app.models.step_01_session import ContentSession
from backend.app.models.step_02_payload import WordPressFields, WordPressPayload
from backend.wordpress_api import find_term, preflight_wordpress_permissions
from backend.config import (
    GCS_DATA_BUCKET,
    GCS_KNOWLEDGE_BUCKET,
    OPENAI_API_KEY,
    V2_LANGUAGE_MODEL,
    V2_IMAGE_EDIT_MODEL,
    V2_IMAGE_EDIT_QUALITY,
    V2_TRANSCRIPTION_MODEL,
    V2_VISION_MODEL,
    get_active_client_id,
    get_client_config,
)

_lock = RLock()
_services: dict[str, ContentSessionService] = {}


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    raw = str(uri or "").strip()
    if not raw.startswith("gs://"):
        raise ValueError("Client knowledge URI must use gs://bucket/path format.")
    bucket, _, blob = raw[5:].partition("/")
    if not bucket or not blob:
        raise ValueError("Client knowledge URI must include both bucket and object path.")
    return bucket, blob


def client_knowledge_gcs_uri(client_id: str | None = None) -> str:
    if not GCS_KNOWLEDGE_BUCKET:
        return ""
    client = get_client_config(client_id)
    return f"gs://{GCS_KNOWLEDGE_BUCKET}/{client.knowledge_workbook}"


def client_session_gcs_prefix(client_id: str | None = None) -> str:
    if not GCS_DATA_BUCKET:
        return ""
    client = get_client_config(client_id)
    return f"gs://{GCS_DATA_BUCKET}/{client.session_prefix}"


def _resolve_local_workbook(path: Path) -> Path:
    workspace_knowledge_dir = Path.cwd() / "data" / "knowledge"
    local_candidates = [
        workspace_knowledge_dir / path.name,
        workspace_knowledge_dir / f"{path.stem}.xlsm",
        workspace_knowledge_dir / f"{path.stem}.xlsx",
    ]
    for candidate in local_candidates:
        if candidate.is_file():
            WorkbookValidator().validate(WorkbookLoader().load(candidate))
            return candidate

    workbook_candidates = sorted(
        candidate for candidate in workspace_knowledge_dir.glob("*.xlsm") if candidate.is_file()
    )
    if workbook_candidates:
        WorkbookValidator().validate(WorkbookLoader().load(workbook_candidates[0]))
        return workbook_candidates[0]

    raise FileNotFoundError(f"Local workbook not found for {path}")


def _sync_workbook_from_gcs(path: Path, gcs_uri: str) -> Path:
    if not gcs_uri or not os.getenv("RENDER"):
        return _resolve_local_workbook(path)

    temporary_path: Path | None = None
    try:
        bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        client = gcs_storage.Client()
        blob = client.bucket(bucket_name).blob(blob_name)
        if not blob.exists():
            raise RuntimeError(f"Workbook object does not exist in GCS: {gcs_uri}")
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.stem}.gcs-",
            suffix=path.suffix,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        blob.download_to_filename(str(temporary_path))
        WorkbookValidator().validate(WorkbookLoader().load(temporary_path))
        os.replace(temporary_path, path)
        temporary_path = None
    except Exception:
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def _configured_workbook_path(client_id: str | None = None) -> Path:
    client = get_client_config(client_id)
    suffix = Path(client.knowledge_workbook).suffix or ".xlsm"
    if os.getenv("RENDER") and GCS_KNOWLEDGE_BUCKET:
        path = Path("/tmp/speech2post/knowledge") / f"{client.client_id}{suffix}"
    else:
        path = Path.cwd() / "data" / "knowledge" / f"{client.client_id}{suffix}"
    return _sync_workbook_from_gcs(path, client_knowledge_gcs_uri(client.client_id))


def configured_workbook_path(client_id: str | None = None) -> Path:
    """Return the synchronized workbook path used by the current service."""
    return _configured_workbook_path(client_id or get_active_client_id())


def get_v2_service(client_id: str | None = None) -> ContentSessionService:
    resolved_client_id = client_id or get_active_client_id()
    with _lock:
        if resolved_client_id in _services:
            return _services[resolved_client_id]
        workbook_path = _configured_workbook_path(resolved_client_id)
        session_root = Path(os.getenv("V2_SESSION_ROOT", "data/v2_sessions")) / resolved_client_id
        session_gcs_prefix = client_session_gcs_prefix(resolved_client_id)
        use_local_storage = not os.getenv("RENDER") or not session_gcs_prefix
        if use_local_storage:
            repository = FileSessionRepository(session_root, extra_roots=[session_root.parent])
            object_storage = LocalObjectStorageProvider(session_root / "objects")
        else:
            repository = GCSSessionRepository(session_gcs_prefix)
            object_storage = GCSObjectStorageProvider(
                session_gcs_prefix.rstrip("/") + "/objects"
            )
        language_model = (
            OpenAILanguageModelProvider(
                api_key=OPENAI_API_KEY,
                model=V2_LANGUAGE_MODEL,
            )
            if OPENAI_API_KEY and V2_LANGUAGE_MODEL
            else None
        )
        metadata_model_name = os.getenv("V2_METADATA_MODEL", "gpt-5-mini").strip()
        metadata_language_model = (
            OpenAILanguageModelProvider(
                api_key=OPENAI_API_KEY,
                model=metadata_model_name,
            )
            if OPENAI_API_KEY and metadata_model_name
            else language_model
        )
        revision_model_name = os.getenv("V2_REVISION_MODEL", "gpt-5-mini").strip()
        revision_language_model = (
            OpenAILanguageModelProvider(
                api_key=OPENAI_API_KEY,
                model=revision_model_name,
            )
            if OPENAI_API_KEY and revision_model_name
            else language_model
        )
        speech_to_text = (
            OpenAISpeechToTextProvider(
                api_key=OPENAI_API_KEY,
                model=V2_TRANSCRIPTION_MODEL,
            )
            if OPENAI_API_KEY
            else None
        )
        vision = (
            OpenAIVisionProvider(
                api_key=OPENAI_API_KEY,
                model=V2_VISION_MODEL,
            )
            if OPENAI_API_KEY and V2_VISION_MODEL
            else None
        )
        image_editor = (
            OpenAIImageEditingProvider(
                api_key=OPENAI_API_KEY,
                model=V2_IMAGE_EDIT_MODEL,
                quality=V2_IMAGE_EDIT_QUALITY,
            )
            if OPENAI_API_KEY and V2_IMAGE_EDIT_MODEL
            else None
        )
        service = ContentSessionService(
            knowledge=KnowledgeBaseService(workbook_path),
            repository=repository,
            wordpress=ExistingWordPressProvider(client_id=resolved_client_id),
            language_model=language_model,
            revision_language_model=revision_language_model,
            metadata_language_model=metadata_language_model,
            speech_to_text=speech_to_text,
            vision=vision,
            image_editor=image_editor,
            object_storage=object_storage,
            image_processor=PillowProcessor(),
        )
        _services[resolved_client_id] = service
        return service


def reload_v2_knowledge_if_initialized(client_id: str | None = None) -> bool:
    """Reload the workbook without constructing unrelated V2 providers."""
    resolved_client_id = client_id or get_active_client_id()
    with _lock:
        service = _services.get(resolved_client_id)
        if service is None:
            return False
        service.knowledge.reload()
        return True


def v2_readiness() -> dict[str, object]:
    service = get_v2_service()
    snapshot = service.knowledge.current()
    provider_ready = all(
        (
            service.language_model is not None,
            service.speech_to_text is not None,
            service.vision is not None,
            service.object_storage is not None,
            service.image_processor is not None,
            service.wordpress is not None,
        )
    )
    wordpress_contract: dict[str, object]
    try:
        post_type = next(row for row in snapshot.post_types if row.enabled)
        acf_destinations = {
            row.acf_field_name
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == post_type.post_type_key
            and row.include_in_payload
            and row.acf_field_name
        }
        acf_destinations.update(
            row.destination_key
            for row in snapshot.shared_fields
            if row.enabled and row.include_in_payload and row.destination_type == "acf"
        )
        meta_destinations = {
            row.destination_key
            for row in snapshot.shared_fields
            if row.enabled and row.include_in_payload and row.destination_type == "yoast"
        }
        if post_type.post_shortcode_variables:
            meta_destinations.add("_generated_variables")
        preflight_session = ContentSession(
            session_id="readiness",
            user_id="readiness",
            post_type_key=post_type.post_type_key,
            wordpress_post_type=post_type.wp_post_type,
            state="created",
            workbook_hash=snapshot.version.sha256,
            language=post_type.default_language,
        )
        contract = (
            service.wordpress.contract_report(
                session=preflight_session,
                payload=WordPressPayload(
                    wordpress=WordPressFields(),
                    meta={key: "preflight" for key in meta_destinations},
                    acf={key: "preflight" for key in acf_destinations},
                ),
            )
            if isinstance(service.wordpress, ExistingWordPressProvider)
            else {"ready": False, "reason": "contract_report_unavailable"}
        )
        authentication = preflight_wordpress_permissions(strict=False)
        category = find_term("categories", post_type.wp_category_name)
        wordpress_contract = {
            "ready": bool(
                contract.get("ready")
                and authentication.get("authenticated")
                and not authentication.get("missing_capabilities")
                and category
            ),
            "authentication": {
                "authenticated": authentication.get("authenticated"),
                "missing_capabilities": authentication.get("missing_capabilities", []),
            },
            "category_found": bool(category),
            "contract": contract,
        }
    except Exception as exc:
        wordpress_contract = {
            "ready": False,
            "error": str(exc),
        }
    return {
        "ready": provider_ready and bool(wordpress_contract.get("ready")),
        "code_ready": provider_ready,
        "workbook": snapshot.version.model_dump(mode="json"),
        "providers": {
            "language_model": service.language_model is not None,
            "speech_to_text": service.speech_to_text is not None,
            "vision": service.vision is not None,
            "object_storage": service.object_storage is not None,
            "image_processor": service.image_processor is not None,
            "wordpress": service.wordpress is not None,
        },
        "storage_mode": "gcs" if client_session_gcs_prefix() else "local_file",
        "models": {
            "language": V2_LANGUAGE_MODEL,
            "vision": V2_VISION_MODEL,
            "transcription": V2_TRANSCRIPTION_MODEL,
        },
        "wordpress_contract": wordpress_contract,
    }


def reset_v2_service_for_tests() -> None:
    with _lock:
        _services.clear()
