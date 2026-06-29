from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.images.step_02_processor import PillowProcessor
from app.v2.providers.step_02_openai import (
    OpenAIImageEditingProvider,
    OpenAILanguageModelProvider,
    OpenAISpeechToTextProvider,
    OpenAIVisionProvider,
)
from app.v2.providers.step_03_wordpress import ExistingWordPressProvider
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.sessions.step_04_gcs_repository import GCSSessionRepository
from app.v2.sessions.step_03_service import ContentSessionService
from app.v2.storage.step_01_local import LocalObjectStorageProvider
from app.v2.storage.step_03_gcs import GCSObjectStorageProvider
from app.v2.models.step_01_session import ContentSession
from app.v2.models.step_02_payload import WordPressFields, WordPressPayload
from step_40_wordpress_api import find_term, preflight_wordpress_permissions
from config import (
    OPENAI_API_KEY,
    V2_LANGUAGE_MODEL,
    V2_IMAGE_EDIT_MODEL,
    V2_TRANSCRIPTION_MODEL,
    V2_VISION_MODEL,
    V2_SESSION_GCS_PREFIX,
)

_lock = RLock()
_service: ContentSessionService | None = None


def get_v2_service() -> ContentSessionService:
    global _service
    with _lock:
        if _service is not None:
            return _service
        workbook_path = (
            os.getenv("V2_KNOWLEDGE_WORKBOOK_PATH")
            or "data/knowledge/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm"
        )
        session_root = Path(os.getenv("V2_SESSION_ROOT", "data/v2_sessions"))
        if V2_SESSION_GCS_PREFIX:
            repository = GCSSessionRepository(V2_SESSION_GCS_PREFIX)
            object_storage = GCSObjectStorageProvider(
                V2_SESSION_GCS_PREFIX.rstrip("/") + "/objects"
            )
        else:
            repository = FileSessionRepository(session_root)
            object_storage = LocalObjectStorageProvider(session_root / "objects")
        language_model = (
            OpenAILanguageModelProvider(
                api_key=OPENAI_API_KEY,
                model=V2_LANGUAGE_MODEL,
            )
            if OPENAI_API_KEY and V2_LANGUAGE_MODEL
            else None
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
            )
            if OPENAI_API_KEY and V2_IMAGE_EDIT_MODEL
            else None
        )
        _service = ContentSessionService(
            knowledge=KnowledgeBaseService(workbook_path),
            repository=repository,
            wordpress=ExistingWordPressProvider(),
            language_model=language_model,
            speech_to_text=speech_to_text,
            vision=vision,
            image_editor=image_editor,
            object_storage=object_storage,
            image_processor=PillowProcessor(),
        )
        return _service


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
        "storage_mode": "gcs" if V2_SESSION_GCS_PREFIX else "local_file",
        "models": {
            "language": V2_LANGUAGE_MODEL,
            "vision": V2_VISION_MODEL,
            "transcription": V2_TRANSCRIPTION_MODEL,
        },
        "wordpress_contract": wordpress_contract,
    }


def reset_v2_service_for_tests() -> None:
    global _service
    with _lock:
        _service = None
