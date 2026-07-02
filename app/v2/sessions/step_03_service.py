from __future__ import annotations

import uuid
import json
import os
from datetime import date, datetime, timezone
from typing import Any
from pathlib import Path
import tempfile

from pydantic import ValidationError

from app.v2.context.step_01_builder import GenerationContextBuilder
from app.v2.content_generation.step_01_schema_factory import (
    LinkSelectionResponse,
    build_fact_extraction_model,
    build_generation_model,
    build_image_analysis_model,
    build_image_metadata_model,
)
from app.v2.content_generation.step_02_prompts import structured_task_input
from app.v2.errors import (
    DraftValidationError,
    ImageProcessingError,
    InvalidInternalLinksError,
    MissingRequiredFactsError,
    ModelOutputValidationError,
    ModelProviderError,
    PublishingNotApprovedError,
    SessionOwnershipError,
    UnknownPostTypeError,
    TranscriptionProviderError,
    VisionProviderError,
    WordPressRequestError,
)
from app.v2.internal_links.step_01_service import InternalLinkService
from app.v2.images.step_02_processor import PillowProcessor
from app.v2.images.step_03_metadata_context import (
    ImageMetadataFactContextBuilder,
    ImageMetadataFieldContextBuilder,
    ImageMetadataRuleMatcher,
)
from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.models.step_01_session import Approval, ContentSession, FactValue
from app.v2.models.step_02_payload import WordPressPayload
from app.v2.payloads.step_02_builder import PayloadBuilder
from app.v2.providers.step_01_interfaces import WordPressProvider
from app.v2.providers.step_01_interfaces import (
    ImageEditingProvider,
    LanguageModelProvider,
    ObjectStorageProvider,
    SpeechToTextProvider,
    VisionProvider,
)
from app.v2.sessions.step_01_repository import SessionRepository
from app.v2.sessions.step_02_state_machine import SessionStateMachine
from app.v2.storage.step_02_uploads import safe_upload_name
from app.v2.workflow.step_04_generation_conditions import (
    GenerationConditionEvaluator,
    source_fact_dependencies_are_available,
)
from app.v2.workflow.step_02_clarification import ClarificationService
from app.v2.validation.step_01_draft import DraftValidator


class ContentSessionService:
    """Application service for the typed content session lifecycle."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeBaseService,
        repository: SessionRepository,
        wordpress: WordPressProvider | None = None,
        language_model: LanguageModelProvider | None = None,
        speech_to_text: SpeechToTextProvider | None = None,
        vision: VisionProvider | None = None,
        image_editor: ImageEditingProvider | None = None,
        object_storage: ObjectStorageProvider | None = None,
        image_processor: PillowProcessor | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.repository = repository
        self.wordpress = wordpress
        self.language_model = language_model
        self.speech_to_text = speech_to_text
        self.vision = vision
        self.image_editor = image_editor
        self.object_storage = object_storage
        self.image_processor = image_processor
        self.clarification = ClarificationService()
        self.context_builder = GenerationContextBuilder()
        self.payload_builder = PayloadBuilder()
        self.internal_links = InternalLinkService()
        self.draft_validator = DraftValidator()
        self.generation_condition_evaluator = GenerationConditionEvaluator()
        self.image_metadata_fact_context_builder = ImageMetadataFactContextBuilder()
        self.image_metadata_rule_matcher = ImageMetadataRuleMatcher()
        self.image_metadata_field_context_builder = ImageMetadataFieldContextBuilder()

    @staticmethod
    def _milestone(session: ContentSession, message: str) -> None:
        if os.getenv("V2_MILESTONE_LOGS", "1").lower() in {"0", "false", "off", "no"}:
            return
        print(
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"[pipeline milestone] session={session.session_id[:8]} state={session.state} {message}",
            flush=True,
        )

    @staticmethod
    def _normalize_date_value(value: Any) -> Any:
        if value in (None, ""):
            return value
        if isinstance(value, datetime):
            return value.date().strftime("%d.%m.%Y")
        if isinstance(value, date):
            return value.strftime("%d.%m.%Y")
        text = str(value).strip()
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, fmt).strftime("%d.%m.%Y")
            except ValueError:
                pass
        return value

    @classmethod
    def _normalize_fact_values(
        cls,
        snapshot: Any,
        post_type_key: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        date_fact_keys = {
            row.field_key
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == post_type_key
            and row.field_role == "input_fact"
            and row.value_type == "date"
        }
        return {
            key: cls._normalize_date_value(value) if key in date_fact_keys else value
            for key, value in values.items()
        }

    def create(self, *, user_id: str, post_type_key: str) -> ContentSession:
        snapshot = self.knowledge.current()
        post_type = snapshot.post_type(post_type_key)
        if (
            post_type is None
            or not post_type.enabled
            or not post_type.generation_enabled
            or not post_type.template_ready
        ):
            raise UnknownPostTypeError(
                f"Post type {post_type_key!r} is unavailable for generation."
            )
        session = ContentSession(
            session_id=uuid.uuid4().hex,
            user_id=user_id,
            post_type_key=post_type_key,
            wordpress_post_type=post_type.wp_post_type,
            state="created",
            workbook_hash=snapshot.version.sha256,
            language=post_type.default_language,
            workflow_steps={
                row.step_key: "pending"
                for row in snapshot.workflow_steps
            },
        )
        created = self.repository.create(session)
        self._milestone(created, f"created post_type_key={post_type_key}")
        return created

    def get(self, session_id: str) -> ContentSession:
        return self.repository.get(session_id)

    def list_recent(
        self,
        *,
        user_id: str | None,
        client_id: str | None = None,
        post_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        del client_id
        normalized_post_type = (post_type or "").strip().lower()
        normalized_status = (status or "").strip().lower()
        sessions = []
        for session in self.repository.list():
            if user_id and session.user_id != user_id:
                continue
            if normalized_post_type and normalized_post_type not in {
                session.post_type_key.lower(),
                session.wordpress_post_type.lower(),
            }:
                continue
            if normalized_status and normalized_status != session.state.lower():
                continue
            sessions.append(session)
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return [self._archive_item(session) for session in sessions[: max(1, min(limit, 200))]]

    def delete_many(self, *, session_ids: list[str], user_id: str | None) -> dict[str, Any]:
        deleted_ids: list[str] = []
        errors: dict[str, str] = {}
        for session_id in session_ids:
            cleaned = str(session_id or "").strip()
            if not cleaned:
                continue
            try:
                session = self.repository.get(cleaned)
                if user_id and session.user_id != user_id:
                    errors[cleaned] = "The authenticated user does not own this session."
                    continue
                if self.repository.delete(cleaned):
                    deleted_ids.append(cleaned)
            except Exception as exc:
                errors[cleaned] = str(exc)
        return {
            "deleted": len(deleted_ids),
            "deleted_ids": deleted_ids,
            "errors": errors,
        }

    def require_owner(self, session_id: str, user_id: str | None) -> ContentSession:
        session = self.repository.get(session_id)
        if not user_id or session.user_id != user_id:
            raise SessionOwnershipError("The authenticated user does not own this session.")
        return session

    def attach_upload(
        self,
        session_id: str,
        *,
        source: Path,
        kind: str,
        filename: str,
        content_type: str,
        expected_version: int,
        use_vision: bool = True,
    ) -> ContentSession:
        if self.object_storage is None:
            raise RuntimeError("An ObjectStorageProvider is not configured.")
        session = self.repository.get(session_id)
        self._milestone(session, f"upload received kind={kind} filename={filename}")
        storage_uri = self.object_storage.put(
            source,
            f"{session.session_id}/{kind}/{filename}",
        )
        from app.v2.models.step_01_session import MediaReference

        reference = MediaReference(
            media_id=uuid.uuid4().hex,
            filename=filename,
            storage_uri=storage_uri,
            content_type=content_type,
            size_bytes=source.stat().st_size,
        )
        changes: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if kind == "audio":
            changes["audio_refs"] = [*session.audio_refs, reference]
        elif kind == "image":
            changes["image_refs"] = [*session.image_refs, reference]
        else:
            raise ValueError(f"Unsupported upload kind: {kind}")
        updated = session.model_copy(update=changes)
        if updated.state == "created":
            updated = SessionStateMachine(
                self.knowledge.by_hash(updated.workbook_hash)
            ).transition(updated, "uploading")
        if kind == "image":
            snapshot = self.knowledge.by_hash(updated.workbook_hash)
            if use_vision:
                self._milestone(updated, "image Vision analysis started")
                updated = self._analyze_missing_images(snapshot, updated)
                self._milestone(updated, "image Vision analysis finished")
            self._milestone(updated, "Pillow processing started")
            updated = self._process_missing_images(snapshot, updated)
            self._milestone(updated, "Pillow processing finished")
        return self.repository.save(updated, expected_version=expected_version)

    def add_inputs(
        self,
        session_id: str,
        *,
        manual_text: str | None,
        confirmed_facts: dict[str, Any] | None,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        updated = session.model_copy(
            update={
                "manual_text": manual_text if manual_text is not None else session.manual_text,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        if confirmed_facts:
            confirmed_facts = self._normalize_fact_values(
                snapshot,
                session.post_type_key,
                confirmed_facts,
            )
            facts = dict(updated.confirmed_facts)
            for key, value in confirmed_facts.items():
                facts[key] = FactValue(
                    value=value,
                    source="user_correction",
                    confidence=1,
                    confirmed=True,
                )
            updated = updated.model_copy(update={"confirmed_facts": facts})
        if updated.state == "created":
            updated = SessionStateMachine(
                snapshot
            ).transition(updated, "uploading")
        return self.repository.save(updated, expected_version=expected_version)

    def analyze(self, session_id: str, *, expected_version: int) -> ContentSession:
        session = self.repository.get(session_id)
        self._milestone(session, "analysis started")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        state_machine = SessionStateMachine(snapshot)
        if session.state == "uploading":
            session = state_machine.transition(session, "analyzing")
        if session.audio_refs:
            if self.speech_to_text is None or self.object_storage is None:
                raise RuntimeError(
                    "Speech transcription requires configured speech and storage providers."
                )
            transcripts: list[str] = []
            for reference in session.audio_refs:
                self._milestone(session, f"transcription started filename={reference.filename}")
                with tempfile.TemporaryDirectory() as temporary:
                    local = self.object_storage.get(
                        reference.storage_uri,
                        Path(temporary) / reference.filename,
                    )
                    try:
                        transcripts.append(self.speech_to_text.transcribe(local))
                    except Exception as exc:
                        raise TranscriptionProviderError(
                            f"Transcription failed for {reference.filename}: {exc}"
                        ) from exc
                    session = self._record_provider_usage(session, self.speech_to_text)
                self._milestone(session, f"transcription finished filename={reference.filename}")
            session = session.model_copy(update={"transcript": "\n\n".join(transcripts)})
        if self.language_model is not None and (session.manual_text or session.transcript):
            self._milestone(session, "fact extraction started")
            input_rows = [
                row
                for row in snapshot.acf_fields
                if row.enabled
                and row.post_type_key == session.post_type_key
                and row.field_role == "input_fact"
            ]
            enum_families = {
                family: tuple(snapshot.validation_family(family))
                for family in {row.format_or_enum for row in input_rows if row.format_or_enum}
            }
            response_model = build_fact_extraction_model(
                input_rows,
                enum_families=enum_families,
            )
            instructions = [
                row.model_dump(exclude={"sheet_row"})
                for row in snapshot.agent_instructions
                if row.enabled
                and row.owner == "language_model"
                and row.post_type_key in {"*", session.post_type_key}
                and row.workflow_stage in {"all", "analysis"}
            ]
            messages = structured_task_input(
                task="fact_extraction",
                instructions=instructions,
                context={
                    "manual_text": session.manual_text,
                    "transcript": session.transcript,
                    "fact_schema": [
                        row.model_dump(exclude={"sheet_row"})
                        for row in input_rows
                    ],
                },
            )
            parsed = self._structured(
                task="fact_extraction",
                messages=messages,
                schema=response_model,
            )
            session = self._record_provider_usage(session, self.language_model)
            extracted = dict(session.extracted_facts)
            confirmed = dict(session.confirmed_facts)
            source = "manual_text" if session.manual_text else "transcript"
            parsed_values = self._normalize_fact_values(
                snapshot,
                session.post_type_key,
                parsed.model_dump(exclude_none=True),
            )
            for key, value in parsed_values.items():
                fact = FactValue(
                    value=value,
                    source=source,
                    confidence=0.8,
                    confirmed=False,
                )
                extracted[key] = fact
            session = session.model_copy(
                update={"extracted_facts": extracted, "confirmed_facts": confirmed}
            )
            session = self._confirm_extracted_input_facts(snapshot, session)
            self._milestone(session, "fact extraction finished")
        missing = self.clarification.missing_required_dependencies(snapshot, session)
        if missing:
            questions = self.clarification.bundled_questions(missing)
            session = session.model_copy(update={"clarification_questions": questions})
            if session.state != "needs_input":
                session = state_machine.transition(session, "needs_input")
            self._milestone(session, f"analysis needs input missing={len(missing)}")
        else:
            if session.state in {"uploading", "analyzing", "needs_input"}:
                session = state_machine.transition(session, "ready_to_generate")
            self._milestone(session, "analysis ready_to_generate")
        return self.repository.save(session, expected_version=expected_version)

    def answer(
        self,
        session_id: str,
        *,
        corrections: dict[str, Any],
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        corrections = self._normalize_fact_values(
            snapshot,
            session.post_type_key,
            corrections,
        )
        updated = self.clarification.apply_corrections(session, corrections)
        updated = updated.model_copy(update={"clarification_questions": []})
        if session.state == "needs_input":
            updated = SessionStateMachine(snapshot).transition(updated, "analyzing")
        return self.repository.save(updated, expected_version=expected_version)

    def update_image_metadata(
        self,
        session_id: str,
        *,
        filename: str,
        metadata: dict[str, Any],
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        reference = next(
            (
                item
                for item in session.image_refs
                if item.filename == filename
            ),
            None,
        )
        if reference is None:
            processed = next(
                (
                    item
                    for item in session.processed_images
                    if item.get("filename") == filename
                ),
                None,
            )
            if processed:
                media_id = str(processed.get("media_id") or "")
                reference = next(
                    (item for item in session.image_refs if item.media_id == media_id),
                    None,
                )
        if reference is None:
            raise ValueError(f"Image not found in this session: {filename}")

        image_metadata = [
            row
            for row in session.image_metadata
            if row.get("media_id") != reference.media_id
        ]
        existing = next(
            (
                row
                for row in session.image_metadata
                if row.get("media_id") == reference.media_id
            ),
            {},
        )
        processed = next(
            (
                row
                for row in session.processed_images
                if row.get("media_id") == reference.media_id
            ),
            {},
        )
        image_metadata.append(
            {
                **existing,
                "media_id": reference.media_id,
                "image_number": existing.get("image_number") or len(image_metadata) + 1,
                "image_usage": existing.get("image_usage") or "gallery",
                "image_priority": existing.get("image_priority") or len(image_metadata) + 1,
                "path": existing.get("path") or processed.get("path") or reference.storage_uri,
                "image_alt": metadata.get("alt_text") or metadata.get("image_alt") or "",
                "image_title": metadata.get("title") or metadata.get("image_title") or "",
                "image_caption": metadata.get("caption") or metadata.get("image_caption") or "",
                "image_description": (
                    metadata.get("description")
                    or metadata.get("image_description")
                    or existing.get("image_description")
                    or ""
                ),
                "image_description_wp": (
                    metadata.get("image_description_wp")
                    or existing.get("image_description_wp")
                    or ""
                ),
            }
        )
        updated = session.model_copy(
            update={
                "image_metadata": sorted(
                    image_metadata,
                    key=lambda row: int(row.get("image_priority") or 999),
                ),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self.repository.save(updated, expected_version=expected_version)

    def set_featured_image(
        self,
        session_id: str,
        *,
        filename: str,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        reference, processed = self._find_image_reference_and_processed(session, filename)
        image_metadata_by_media = {
            str(row.get("media_id")): dict(row)
            for row in session.image_metadata
            if row.get("media_id")
        }
        for index, image_ref in enumerate(session.image_refs, 1):
            row = image_metadata_by_media.get(image_ref.media_id, {})
            processed_row = next(
                (
                    item
                    for item in session.processed_images
                    if item.get("media_id") == image_ref.media_id
                ),
                {},
            )
            row.update(
                {
                    "media_id": image_ref.media_id,
                    "image_number": index,
                    "image_usage": "featured" if image_ref.media_id == reference.media_id else "gallery",
                    "image_priority": 1 if image_ref.media_id == reference.media_id else index + 1,
                    "path": row.get("path") or processed_row.get("path") or image_ref.storage_uri,
                }
            )
            image_metadata_by_media[image_ref.media_id] = row
        updated = session.model_copy(
            update={
                "image_metadata": sorted(
                    image_metadata_by_media.values(),
                    key=lambda row: int(row.get("image_priority") or 999),
                ),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._milestone(updated, f"featured image selected filename={processed.get('filename') or filename}")
        return self.repository.save(updated, expected_version=expected_version)

    def media_path(
        self,
        session_id: str,
        *,
        kind: str,
        filename: str,
        original: bool = False,
    ) -> Path:
        session = self.repository.get(session_id)
        if kind == "image":
            processed = next(
                (
                    item
                    for item in session.processed_images
                    if item.get("filename") == filename
                    or any(
                        ref.media_id == item.get("media_id") and ref.filename == filename
                        for ref in session.image_refs
                    )
                ),
                None,
            )
            if original:
                reference = next(
                    (
                        ref
                        for ref in session.image_refs
                        if ref.filename == filename
                        or (processed and ref.media_id == processed.get("media_id"))
                    ),
                    None,
                )
                if reference is not None:
                    return self._materialize_media_uri(
                        reference.storage_uri,
                        session_id=session_id,
                        filename=reference.filename,
                    )
            if processed is not None:
                return self._materialize_media_uri(
                    str(processed.get("path") or processed.get("output") or ""),
                    session_id=session_id,
                    filename=str(processed.get("filename") or filename),
                )
            reference = next((ref for ref in session.image_refs if ref.filename == filename), None)
            if reference is not None:
                return self._materialize_media_uri(
                    reference.storage_uri,
                    session_id=session_id,
                    filename=reference.filename,
                )
        if kind == "audio":
            reference = next((ref for ref in session.audio_refs if ref.filename == filename), None)
            if reference is not None:
                return self._materialize_media_uri(
                    reference.storage_uri,
                    session_id=session_id,
                    filename=reference.filename,
                )
        raise ValueError(f"Media not found in this session: {kind}/{filename}")

    def _materialize_media_uri(
        self,
        uri: str,
        *,
        session_id: str,
        filename: str,
    ) -> Path:
        if uri.startswith("gs://"):
            if self.object_storage is None:
                raise ValueError("GCS media storage is not configured.")
            destination = (
                Path(tempfile.gettempdir())
                / "flairlab-v2-media-cache"
                / session_id
                / safe_upload_name(filename, Path(filename).suffix or ".bin")
            )
            return self.object_storage.get(uri, destination)
        return Path(uri)

    def remove_media(
        self,
        session_id: str,
        *,
        kind: str,
        filename: str,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if kind == "images":
            reference = next(
                (
                    ref
                    for ref in session.image_refs
                    if ref.filename == filename
                    or any(
                        item.get("media_id") == ref.media_id and item.get("filename") == filename
                        for item in session.processed_images
                    )
                ),
                None,
            )
            if reference is None:
                raise ValueError(f"Image not found in this session: {filename}")
            media_id = reference.media_id
            updates["image_refs"] = [ref for ref in session.image_refs if ref.media_id != media_id]
            updates["processed_images"] = [
                item for item in session.processed_images if item.get("media_id") != media_id
            ]
            updates["image_metadata"] = [
                item for item in session.image_metadata if item.get("media_id") != media_id
            ]
            image_analysis = dict(session.image_analysis)
            image_analysis.pop(media_id, None)
            updates["image_analysis"] = image_analysis
        elif kind == "voices":
            reference = next((ref for ref in session.audio_refs if ref.filename == filename), None)
            if reference is None:
                raise ValueError(f"Voice not found in this session: {filename}")
            updates["audio_refs"] = [
                ref for ref in session.audio_refs if ref.media_id != reference.media_id
            ]
            if not updates["audio_refs"]:
                updates["transcript"] = ""
        else:
            raise ValueError(f"Unsupported media kind: {kind}")
        return self.repository.save(session.model_copy(update=updates), expected_version=expected_version)

    def optimize_image(
        self,
        session_id: str,
        *,
        filename: str,
        prompt: str,
        expected_version: int,
    ) -> ContentSession:
        if self.image_editor is None or self.object_storage is None:
            raise RuntimeError("An ImageEditingProvider and ObjectStorageProvider are required.")
        session = self.repository.get(session_id)
        reference, processed = self._find_image_reference_and_processed(session, filename)
        if processed is None:
            raise ValueError(f"Processed image not found in this session: {filename}")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.object_storage.get(
                reference.storage_uri,
                root / reference.filename,
            )
            edited = root / str(processed.get("filename") or f"{Path(reference.filename).stem}.png")
            self.image_editor.edit(source, edited, {"prompt": prompt})
            storage_uri = self.object_storage.put(
                edited,
                f"{session.session_id}/processed/{edited.name}",
            )
        session = self._record_provider_usage(session, self.image_editor)
        processed_images = []
        for item in session.processed_images:
            if item.get("media_id") != reference.media_id:
                processed_images.append(item)
                continue
            operations = [
                str(operation)
                for operation in item.get("operations", item.get("applied_operations", []))
                if str(operation).strip()
            ]
            operations.append("openai_image_optimization")
            processed_images.append(
                {
                    **item,
                    "path": storage_uri,
                    "output": storage_uri,
                    "size_bytes": Path(storage_uri).stat().st_size if not storage_uri.startswith("gs://") else item.get("size_bytes"),
                    "operations": operations[-20:],
                    "image_optimization": {
                        "prompt": prompt,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            )
        return self.repository.save(
            session.model_copy(
                update={
                    "processed_images": processed_images,
                    "updated_at": datetime.now(timezone.utc),
                }
            ),
            expected_version=expected_version,
        )

    def restore_image_original(
        self,
        session_id: str,
        *,
        filename: str,
        expected_version: int,
    ) -> ContentSession:
        if self.object_storage is None:
            raise RuntimeError("An ObjectStorageProvider is required.")
        session = self.repository.get(session_id)
        reference, processed = self._find_image_reference_and_processed(session, filename)
        if processed is None:
            raise ValueError(f"Processed image not found in this session: {filename}")
        output_name = str(processed.get("filename") or reference.filename)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.object_storage.get(reference.storage_uri, root / reference.filename)
            storage_uri = self.object_storage.put(
                original,
                f"{session.session_id}/processed/{output_name}",
            )
        processed_images = []
        for item in session.processed_images:
            if item.get("media_id") != reference.media_id:
                processed_images.append(item)
                continue
            operations = [
                str(operation)
                for operation in item.get("operations", item.get("applied_operations", []))
                if str(operation).strip()
            ]
            operations.append("restore_original")
            processed_images.append(
                {
                    **item,
                    "path": storage_uri,
                    "output": storage_uri,
                    "original_uri": reference.storage_uri,
                    "size_bytes": reference.size_bytes,
                    "operations": operations[-20:],
                    "image_optimization": {
                        "restored_from_original": True,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
            )
        return self.repository.save(
            session.model_copy(
                update={
                    "processed_images": processed_images,
                    "updated_at": datetime.now(timezone.utc),
                }
            ),
            expected_version=expected_version,
        )

    def generate(
        self,
        session_id: str,
        *,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
        selected_links: list[dict[str, str]],
        current_url: str | None,
        use_vision_for_image_metadata: bool = True,
        revision_instruction: str | None = None,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        missing = self.clarification.missing_required_dependencies(snapshot, session)
        if missing:
            raise MissingRequiredFactsError(
                "Required fact dependencies remain unresolved."
            )
        state_machine = SessionStateMachine(snapshot)
        if session.state in {"ready_to_generate", "needs_review"}:
            session = state_machine.transition(session, "generating")
        generation_trace = dict(session.generation_trace)
        if self.language_model is not None:
            enum_families = {
                row.list_name: tuple(snapshot.validation_family(row.list_name))
                for row in snapshot.validation_values
            }
            if not shared_fields:
                self._milestone(session, "shared field generation started")
                rows = [
                    row for row in snapshot.shared_fields
                    if row.enabled and row.include_in_ai_schema
                ]
                context = self.context_builder.build(
                    snapshot=snapshot,
                    task="generation",
                    post_type_key=session.post_type_key,
                    session=session,
                    field_keys=[row.field_key for row in rows],
                )
                context_payload = context.model_dump(by_alias=True)
                context_payload["current_shared_fields"] = shared_fields
                generation_trace.update(
                    self._generation_trace_from_context(
                        context,
                        field_keys=[row.field_key for row in rows],
                        generation_task="shared_field_generation",
                    )
                )
                if revision_instruction:
                    context_payload["draft_revision"] = {
                        "instruction": revision_instruction,
                        "current_shared_fields": shared_fields,
                        "current_acf_source_fields": session.acf_source_fields,
                    }
                model = build_generation_model(
                    rows,
                    name="SharedFieldsResponse",
                    enum_families=enum_families,
                )
                messages = structured_task_input(
                    task="shared_field_generation",
                    instructions=context.instructions,
                    context=context_payload,
                )
                shared_fields = self._structured(
                    task="shared_field_generation",
                    messages=messages,
                    schema=model,
                ).model_dump(exclude_none=True)
                session = self._record_provider_usage(session, self.language_model)
                self._milestone(session, "shared field generation finished")
            if not acf_source_fields:
                self._milestone(session, "ACF field generation started")
                rows = [
                    row for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == session.post_type_key
                    and row.field_role != "input_fact"
                    and row.include_in_ai_schema
                    and self._acf_field_is_eligible(row, session)
                ]
                context = self.context_builder.build(
                    snapshot=snapshot,
                    task="generation",
                    post_type_key=session.post_type_key,
                    session=session,
                    field_keys=[row.field_key for row in rows],
                )
                context_payload = context.model_dump(by_alias=True)
                generation_trace.update(
                    self._generation_trace_from_context(
                        context,
                        field_keys=[row.field_key for row in rows],
                        generation_task="acf_field_generation",
                    )
                )
                if revision_instruction:
                    context_payload["draft_revision"] = {
                        "instruction": revision_instruction,
                        "current_shared_fields": session.shared_fields,
                        "current_acf_source_fields": session.acf_source_fields,
                    }
                model = build_generation_model(
                    rows,
                    name="ACFFieldsResponse",
                    enum_families=enum_families,
                )
                messages = structured_task_input(
                    task="acf_field_generation",
                    instructions=context.instructions,
                    context=context_payload,
                )
                acf_source_fields = self._structured(
                    task="acf_field_generation",
                    messages=messages,
                    schema=model,
                ).model_dump(exclude_none=True)
                session = self._record_provider_usage(session, self.language_model)
                self._milestone(session, "ACF field generation finished")
        eligible = self.internal_links.eligible(
            snapshot,
            post_type_key=session.post_type_key,
            language=session.language,
            current_url=current_url,
        )
        if self.language_model is not None and not selected_links and eligible.candidates:
            self._milestone(session, "internal link ranking started")
            context = self.context_builder.build(
                snapshot=snapshot,
                task="internal_links",
                post_type_key=session.post_type_key,
                session=session,
            )
            messages = structured_task_input(
                task="internal_link_ranking",
                instructions=context.instructions,
                context={
                    "confirmed_facts": context.confirmed_facts,
                    "candidates": [
                        {
                            "link_id": row.link_id,
                            "anchor_text": row.anchor_text,
                            "anchor_variants": row.anchor_variants,
                            "usage_context": row.usage_context,
                            "priority": row.priority,
                        }
                        for row in eligible.candidates
                    ],
                },
            )
            ranked_links = self._structured(
                task="internal_link_ranking",
                messages=messages,
                schema=LinkSelectionResponse,
            )
            session = self._record_provider_usage(session, self.language_model)
            selected_links = [row.model_dump() for row in ranked_links.selections]
            self._milestone(session, "internal link ranking finished")
        minimum_links, maximum_links = self._internal_link_range(snapshot)
        if maximum_links is not None and len(selected_links) > maximum_links:
            selected_links = selected_links[:maximum_links]
        selected_links = self._complete_internal_link_selection(
            eligible,
            selected_links,
            minimum_links=minimum_links,
            maximum_links=maximum_links,
        )
        try:
            related_links_html = self.internal_links.render(
                eligible,
                selected_links,
                minimum_links=minimum_links,
                maximum_links=maximum_links,
            )
        except ValueError as exc:
            raise InvalidInternalLinksError(str(exc)) from exc
        session = self._process_missing_images(snapshot, session)
        processed_images = list(session.processed_images)
        routed_shared = dict(shared_fields)
        routed_shared["related_links_html"] = related_links_html
        post_type = snapshot.post_type(session.post_type_key)
        if post_type is None:
            raise UnknownPostTypeError(session.post_type_key)
        routed_shared.setdefault("status", post_type.default_status)
        routed_shared.setdefault("category", post_type.wp_category_name)
        validation_report = self.draft_validator.validate(
            snapshot,
            post_type_key=session.post_type_key,
            shared_values=routed_shared,
            acf_source_values=acf_source_fields,
            no_eligible_links=not eligible.candidates,
            session=session,
        )
        payload = self.payload_builder.build(
            snapshot,
            post_type_key=session.post_type_key,
            shared_values=routed_shared,
            acf_source_values=acf_source_fields,
            media=session.image_metadata,
        )
        if session.image_refs:
            session = session.model_copy(
                update={
                    "shared_fields": routed_shared,
                    "acf_source_fields": acf_source_fields,
                    "selected_links": selected_links,
                    "eligible_link_ids": [row.link_id for row in eligible.candidates],
                    "related_links_html": related_links_html,
                    "wordpress_payload": payload.model_dump(),
                }
            )
            if use_vision_for_image_metadata:
                self._milestone(session, "contextual image Vision analysis started")
                session = self._analyze_missing_images(snapshot, session)
                self._milestone(session, "contextual image Vision analysis finished")
            self._milestone(session, "image metadata generation started")
            session = self._generate_missing_image_metadata(
                snapshot,
                session,
                overwrite_existing=True,
            )
            self._milestone(session, "image metadata generation finished")
            payload = self.payload_builder.build(
                snapshot,
                post_type_key=session.post_type_key,
                shared_values=routed_shared,
                acf_source_values=acf_source_fields,
                media=session.image_metadata,
            )
        image_metadata = list(session.image_metadata)
        payload = self.payload_builder.build(
            snapshot,
            post_type_key=session.post_type_key,
            shared_values=routed_shared,
            acf_source_values=acf_source_fields,
            media=image_metadata,
        )
        session = session.model_copy(
            update={
                "shared_fields": routed_shared,
                "acf_source_fields": acf_source_fields,
                "selected_links": selected_links,
                "eligible_link_ids": [row.link_id for row in eligible.candidates],
                "related_links_html": related_links_html,
                "wordpress_payload": payload.model_dump(),
                "processed_images": processed_images,
                "image_metadata": image_metadata,
                "validation_report": validation_report,
                "generation_trace": generation_trace,
            }
        )
        if session.state in {"ready_to_publish", "published"} and revision_instruction:
            session = session.model_copy(
                update={
                    "state": "needs_review",
                    "approval": Approval(),
                    "publication_idempotency_key": None,
                }
            )
        else:
            session = state_machine.transition(session, "needs_review")
        self._milestone(session, "draft generation finished")
        return self.repository.save(session, expected_version=expected_version)

    def _structured(
        self,
        *,
        task: str,
        messages: list[dict[str, str]],
        schema: type[Any],
    ) -> Any:
        if self.language_model is None:
            raise RuntimeError("A LanguageModelProvider is not configured.")
        current_messages = list(messages)
        validation_errors: list[str] = []
        max_attempts = 5 if task in {"shared_field_generation", "acf_field_generation"} else 3
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.language_model.structured(
                    task=task,
                    context={"messages": current_messages},
                    schema=schema,
                )
                return result
            except (ValidationError, ValueError) as validation_error:
                feedback = self._validation_feedback(validation_error)
                validation_errors.append(feedback)
                if attempt == max_attempts:
                    raise ModelOutputValidationError(
                        f"Structured output failed validation for {task} after "
                        f"{attempt} attempts: {feedback}"
                    ) from validation_error
                current_messages = [
                    *messages,
                    {
                        "role": "system",
                        "content": (
                            "Regenerate the complete response object. The previous "
                            "response failed deterministic validation. Fix every listed "
                            "field exactly; respect minimum and maximum word/character "
                            "counts by counting before responding. For any minimum word "
                            "failure, write at least 10 words more than the minimum while "
                            "remaining below the maximum. Validation feedback: "
                            + feedback
                        ),
                    },
                ]
            except Exception as provider_error:
                raise ModelProviderError(
                    f"Model provider failed for {task} on attempt {attempt}: "
                    f"{provider_error}"
                ) from provider_error
        raise ModelOutputValidationError(
            f"Structured output failed validation for {task}: {validation_errors}"
        )

    @staticmethod
    def _record_provider_usage(
        session: ContentSession,
        provider: Any,
    ) -> ContentSession:
        event = getattr(provider, "last_usage", None)
        if not isinstance(event, dict):
            return session
        usage = dict(session.ai_usage or {})
        usage.setdefault("call_count", 0)
        usage.setdefault("prompt_tokens", 0)
        usage.setdefault("completion_tokens", 0)
        usage.setdefault("total_tokens", 0)
        usage.setdefault("estimated_cost_usd", 0.0)
        usage.setdefault("unknown_usage_calls", 0)
        services = dict(usage.get("services") or {})

        service = str(event.get("service") or "unknown")
        service_stats = dict(
            services.get(service)
            or {
                "service": service,
                "call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "unknown_usage_calls": 0,
            }
        )
        prompt_tokens = int(event.get("prompt_tokens") or 0)
        completion_tokens = int(event.get("completion_tokens") or 0)
        total_tokens = int(event.get("total_tokens") or prompt_tokens + completion_tokens)
        estimated_cost = event.get("estimated_cost_usd")
        unknown_usage = estimated_cost is None

        usage["call_count"] = int(usage.get("call_count") or 0) + 1
        usage["prompt_tokens"] = int(usage.get("prompt_tokens") or 0) + prompt_tokens
        usage["completion_tokens"] = int(usage.get("completion_tokens") or 0) + completion_tokens
        usage["total_tokens"] = int(usage.get("total_tokens") or 0) + total_tokens
        if unknown_usage:
            usage["unknown_usage_calls"] = int(usage.get("unknown_usage_calls") or 0) + 1
        else:
            usage["estimated_cost_usd"] = round(
                float(usage.get("estimated_cost_usd") or 0.0) + float(estimated_cost),
                8,
            )

        service_stats["call_count"] = int(service_stats.get("call_count") or 0) + 1
        service_stats["prompt_tokens"] = int(service_stats.get("prompt_tokens") or 0) + prompt_tokens
        service_stats["completion_tokens"] = int(service_stats.get("completion_tokens") or 0) + completion_tokens
        service_stats["total_tokens"] = int(service_stats.get("total_tokens") or 0) + total_tokens
        if unknown_usage:
            service_stats["unknown_usage_calls"] = (
                int(service_stats.get("unknown_usage_calls") or 0) + 1
            )
        else:
            service_stats["estimated_cost_usd"] = round(
                float(service_stats.get("estimated_cost_usd") or 0.0) + float(estimated_cost),
                8,
            )
        services[service] = service_stats
        usage["services"] = services
        usage["last_call"] = {
            **event,
            "unknown_usage": unknown_usage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        usage["updated_at"] = usage["last_call"]["updated_at"]
        return session.model_copy(update={"ai_usage": usage})

    def _analyze_missing_images(
        self,
        snapshot: Any,
        session: ContentSession,
    ) -> ContentSession:
        if self.vision is None or self.object_storage is None or not session.image_refs:
            return session
        image_analysis = dict(session.image_analysis)
        missing_refs = [
            reference
            for reference in session.image_refs
            if reference.media_id not in image_analysis
        ]
        if not missing_refs:
            return session
        enum_families = {
            family: tuple(snapshot.validation_family(family))
            for family in {
                row.output_domain
                for row in snapshot.image_analysis_rules
                if row.output_domain
            }
        }
        response_model = build_image_analysis_model(
            list(snapshot.image_analysis_rules),
            enum_families=enum_families,
        )
        vision_context = {
            "task": "image_analysis",
            "rules": [
                {
                    "analysis_key": row.analysis_key,
                    "intent_de": row.intent_de,
                }
                for row in snapshot.image_analysis_rules
                if row.enabled
            ],
            "instructions": [
                row.instruction_de
                for row in snapshot.agent_instructions
                if row.enabled
                and row.owner == "language_model"
                and row.post_type_key in {"*", session.post_type_key}
                and row.workflow_stage in {"all", "image_metadata"}
            ],
            "confirmed_facts": {
                key: value.model_dump()
                for key, value in session.confirmed_facts.items()
            },
        }
        for reference in missing_refs:
            with tempfile.TemporaryDirectory() as temporary:
                local = self.object_storage.get(
                    reference.storage_uri,
                    Path(temporary) / reference.filename,
                )
                try:
                    parsed = self.vision.analyze(
                        local,
                        response_model,
                        vision_context,
                    )
                except Exception as exc:
                    raise VisionProviderError(
                        f"Vision analysis failed for {reference.filename}: {exc}"
                    ) from exc
                session = self._record_provider_usage(session, self.vision)
                image_analysis[reference.media_id] = parsed.model_dump()
        return session.model_copy(update={"image_analysis": image_analysis})

    def _process_missing_images(
        self,
        snapshot: Any,
        session: ContentSession,
    ) -> ContentSession:
        if self.image_processor is None or self.object_storage is None or not session.image_refs:
            return session
        processed_images = list(session.processed_images)
        processed_media_ids = {
            str(item.get("media_id"))
            for item in processed_images
            if item.get("media_id")
        }
        unprocessed_refs = [
            reference
            for reference in session.image_refs
            if reference.media_id not in processed_media_ids
        ]
        if not unprocessed_refs:
            return session
        output_format = str(
            next(
                row.value
                for row in snapshot.pillow_rules
                if row.enabled and row.rule_key == "output.format"
            )
        ).lower()
        for reference in unprocessed_refs:
            with tempfile.TemporaryDirectory() as temporary:
                source = self.object_storage.get(
                    reference.storage_uri,
                    Path(temporary) / reference.filename,
                )
                output = Path(temporary) / f"{Path(reference.filename).stem}.{output_format}"
                try:
                    result = self.image_processor.process(
                        snapshot,
                        source=source,
                        destination=output,
                        analysis=session.image_analysis.get(reference.media_id, {}),
                    )
                except Exception as exc:
                    raise ImageProcessingError(
                        f"Failed to process image {reference.filename}: {exc}"
                    ) from exc
                storage_uri = self.object_storage.put(
                    output,
                    f"{session.session_id}/processed/{output.name}",
                )
                processed_images.append(
                    {
                        **result,
                        "media_id": reference.media_id,
                        "filename": output.name,
                        "path": storage_uri,
                        "original_uri": reference.storage_uri,
                    }
                )
        return session.model_copy(update={"processed_images": processed_images})

    def _generate_missing_image_metadata(
        self,
        snapshot: Any,
        session: ContentSession,
        *,
        overwrite_existing: bool = False,
    ) -> ContentSession:
        if self.language_model is None or not session.image_refs:
            return session
        previous_metadata_by_media = {
            str(item.get("media_id")): dict(item)
            for item in session.image_metadata
            if item.get("media_id")
        }
        image_metadata = [] if overwrite_existing else list(session.image_metadata)
        metadata_media_ids = {
            str(item.get("media_id"))
            for item in image_metadata
            if item.get("media_id")
            and any(
                item.get(key)
                for key in (
                    "image_alt",
                    "image_title",
                    "image_caption",
                    "image_description",
                    "image_description_wp",
                    "image_filename",
                )
            )
        }
        missing_metadata_refs = [
            reference
            for reference in session.image_refs
            if overwrite_existing or reference.media_id not in metadata_media_ids
        ]
        if not missing_metadata_refs:
            return session

        metadata_rows = list(snapshot.image_metadata_fields)
        metadata_model = build_image_metadata_model(
            metadata_rows,
            enum_families={},
        )
        image_instructions = [
            row.model_dump(exclude={"sheet_row"})
            for row in snapshot.agent_instructions
            if row.enabled
            and row.owner == "language_model"
            and row.post_type_key in {"*", session.post_type_key}
            and row.workflow_stage in {"all", "image_metadata"}
        ]
        processed_images = list(session.processed_images)
        for index, reference in enumerate(session.image_refs, 1):
            if not overwrite_existing and reference.media_id in metadata_media_ids:
                continue
            existing = next(
                (
                    row
                    for row in image_metadata
                    if row.get("media_id") == reference.media_id
                ),
                previous_metadata_by_media.get(reference.media_id, {}),
            ) or {}
            image_metadata = [
                row
                for row in image_metadata
                if row.get("media_id") != reference.media_id
            ]
            messages = structured_task_input(
                task="image_metadata",
                instructions=image_instructions,
                context=self._image_metadata_context(
                    snapshot,
                    session,
                    reference.media_id,
                    metadata_rows,
                ),
            )
            generated = self._structured(
                task="image_metadata",
                messages=messages,
                schema=metadata_model,
            ).model_dump(exclude_none=True)
            session = self._record_provider_usage(session, self.language_model)
            processed = next(
                (row for row in processed_images if row["media_id"] == reference.media_id),
                {},
            )
            image_usage = existing.get("image_usage") or ("featured" if index == 1 else "gallery")
            image_metadata.append(
                {
                    "media_id": reference.media_id,
                    "image_number": index,
                    "image_usage": image_usage,
                    "image_priority": 1 if image_usage == "featured" else (index + 1),
                    "path": processed.get("path", reference.storage_uri),
                    **generated,
                }
            )
            metadata_media_ids.add(reference.media_id)
        return session.model_copy(
            update={
                "image_metadata": sorted(
                    image_metadata,
                    key=lambda row: (
                        0 if row.get("image_usage") == "featured" else 1,
                        int(row.get("image_priority") or 999),
                    ),
                )
            }
        )

    @staticmethod
    def _confirm_extracted_input_facts(
        snapshot: Any,
        session: ContentSession,
    ) -> ContentSession:
        confirmed = dict(session.confirmed_facts)
        input_fact_keys = {
            row.field_key
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == session.post_type_key
            and row.field_role == "input_fact"
        }
        changed = False
        for key, fact in session.extracted_facts.items():
            if key not in input_fact_keys or key in confirmed:
                continue
            if fact.value in (None, "", []):
                continue
            confirmed[key] = fact.model_copy(
                update={
                    "confirmed": True,
                    "confidence": max(float(fact.confidence or 0), 0.85),
                }
            )
            changed = True
        if not changed:
            return session
        return session.model_copy(update={"confirmed_facts": confirmed})

    def _image_metadata_context(
        self,
        snapshot: Any,
        session: ContentSession,
        media_id: str,
        metadata_rows: list[Any],
    ) -> dict[str, Any]:
        image_analysis = session.image_analysis.get(media_id, {})
        matching_rules = self.image_metadata_rule_matcher.match(
            rules=list(snapshot.image_metadata_rules),
            post_type_key=session.post_type_key,
            image_analysis=image_analysis,
            content_signals=session.content_signals,
            context_tags=session.context_tags,
        )
        rule_fact_context = self.image_metadata_field_context_builder.build(
            metadata_rows=metadata_rows,
            matching_rules=matching_rules,
            session=session,
        )
        must_use_when_natural = [
            {
                "rule_id": rule.rule_id,
                "priority": rule.priority,
                "usage_mode": rule.usage_mode,
                "instruction_de": rule.instruction_de,
                "target_field_keys": rule.target_field_keys,
                "confirmed_source_facts": {
                    key: session.confirmed_facts[key].model_dump()
                    for key in rule.source_fact_keys
                    if key in session.confirmed_facts
                    and session.confirmed_facts[key].confirmed
                    and session.confirmed_facts[key].value not in (None, "", [])
                },
            }
            for rule in matching_rules
            if rule.usage_mode != "exclude"
        ]
        return {
            "confirmed_facts": {
                key: value.model_dump()
                for key, value in session.confirmed_facts.items()
            },
            "base_confirmed_facts": self.image_metadata_fact_context_builder.build_base_facts(
                session=session,
                acf_schema=list(snapshot.acf_fields),
            ),
            "shared_fields": session.shared_fields,
            "acf_source_fields": session.acf_source_fields,
            "wordpress_payload": session.wordpress_payload,
            "image_analysis": image_analysis,
            "must_use_when_natural": must_use_when_natural,
            "fields": rule_fact_context,
            "image_schema": [
                row.model_dump(exclude={"sheet_row"})
                for row in metadata_rows
            ],
        }

    @staticmethod
    def _generation_trace_from_context(
        context: Any,
        *,
        field_keys: list[str],
        generation_task: str,
    ) -> dict[str, Any]:
        trace: dict[str, Any] = {}
        shared_rules = []
        for instruction in context.instructions:
            text = str(instruction.get("instruction_de") or "").strip()
            if text:
                shared_rules.append({
                    "source": "agent_instructions",
                    "scope": "task",
                    "shared": True,
                    "rule_id": instruction.get("instruction_id") or instruction.get("rule_id"),
                    "priority": instruction.get("priority"),
                    "text": text,
                })
        for pattern in context.story_patterns:
            text = str(pattern.get("prompt_fragment_de") or pattern.get("use_when_de") or "").strip()
            if text:
                shared_rules.append({
                    "source": "story_patterns",
                    "scope": "story_pattern",
                    "shared": True,
                    "rule_id": pattern.get("pattern_id"),
                    "priority": pattern.get("priority"),
                    "text": text,
                })

        for field_key in field_keys:
            field = context.fields.get(field_key)
            if field is None:
                continue
            schema = dict(field.schema_data)
            rules: list[dict[str, Any]] = []
            description = str(schema.get("description_de") or "").strip()
            if description:
                rules.append({
                    "source": "field_schema.description_de",
                    "scope": "field",
                    "shared": False,
                    "text": description,
                })
            guidance = str(schema.get("guidance_de") or "").strip()
            if guidance:
                rules.append({
                    "source": "field_schema.guidance_de",
                    "scope": "field",
                    "shared": False,
                    "text": guidance,
                })
            limits = []
            if schema.get("min_words") is not None:
                limits.append(f"min_words={schema.get('min_words')}")
            if schema.get("max_words") is not None:
                limits.append(f"max_words={schema.get('max_words')}")
            if schema.get("min_characters") is not None:
                limits.append(f"min_characters={schema.get('min_characters')}")
            if schema.get("max_characters") is not None:
                limits.append(f"max_characters={schema.get('max_characters')}")
            if limits:
                rules.append({
                    "source": "field_schema.validation_limits",
                    "scope": "field",
                    "shared": False,
                    "text": ", ".join(limits),
                })
            for source, scope, shared, rows in (
                ("seo_rules", "field", False, field.exact_rules),
                ("seo_rules", "group", True, field.group_rules),
                ("seo_rules", "section", True, field.section_rules),
                ("style_rules", "style", True, field.style_rules),
            ):
                for row in rows:
                    text = str(row.get("instruction_de") or "").strip()
                    if not text:
                        continue
                    rules.append({
                        "source": source,
                        "scope": scope,
                        "shared": shared,
                        "rule_id": row.get("rule_id"),
                        "priority": row.get("priority"),
                        "target_type": row.get("target_type") or row.get("match_type"),
                        "target_key": row.get("target_key") or row.get("match_value"),
                        "text": text,
                    })
            trace[field_key] = {
                "field_key": field_key,
                "label": schema.get("description_de") or field_key,
                "generation_task": generation_task,
                "value_type": schema.get("value_type"),
                "group": schema.get("group"),
                "section": schema.get("section"),
                "rules": [*shared_rules, *rules],
            }
        return trace

    @staticmethod
    def _archive_item(session: ContentSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "client_id": session.user_id,
            "post_type": session.post_type_key,
            "status": session.state,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "storage": "v2",
            "wordpress_post_id": session.wordpress_result.get("post_id"),
            "has_images": bool(session.image_refs),
            "has_transcript": bool(session.transcript),
            "has_draft": bool(session.wordpress_payload),
            "missing_media_total": 0,
            "missing_media_images": 0,
            "missing_media_videos": 0,
            "missing_media_voices": 0,
        }

    @staticmethod
    def _find_image_reference_and_processed(
        session: ContentSession,
        filename: str,
    ) -> tuple[Any, dict[str, Any] | None]:
        requested = str(filename or "").strip()
        processed = next(
            (
                item
                for item in session.processed_images
                if item.get("filename") == requested
            ),
            None,
        )
        reference = next(
            (
                item
                for item in session.image_refs
                if item.filename == requested
                or (processed is not None and item.media_id == processed.get("media_id"))
            ),
            None,
        )
        if reference is None:
            reference = next(
                (
                    item
                    for item in session.image_refs
                    if any(
                        processed_item.get("media_id") == item.media_id
                        and processed_item.get("filename") == requested
                        for processed_item in session.processed_images
                    )
                ),
                None,
            )
        if reference is None:
            raise ValueError(f"Image not found in this session: {filename}")
        if processed is None:
            processed = next(
                (
                    item
                    for item in session.processed_images
                    if item.get("media_id") == reference.media_id
                ),
                None,
            )
        return reference, processed

    @staticmethod
    def _acf_field_is_eligible(row: Any, session: ContentSession) -> bool:
        if not source_fact_dependencies_are_available(row, session):
            return False
        return GenerationConditionEvaluator().evaluate(
            row.generation_condition,
            session=session,
        )

    @staticmethod
    def _validation_feedback(error: ValidationError | ValueError) -> str:
        if isinstance(error, ValidationError):
            details = [
                {
                    "field": ".".join(str(part) for part in item["loc"]),
                    "message": item["msg"],
                }
                for item in error.errors()
            ]
            return json.dumps(details, ensure_ascii=False)
        return str(error)

    @staticmethod
    def _internal_link_range(snapshot: Any) -> tuple[int, int | None]:
        for row in snapshot.internal_link_rules:
            if row.enabled and row.operator == "between":
                values = [int(part) for part in str(row.value).split(";") if part.strip()]
                if len(values) == 2:
                    return values[0], values[1]
        return 0, None

    @staticmethod
    def _complete_internal_link_selection(
        eligible: Any,
        selected_links: list[dict[str, str]],
        *,
        minimum_links: int,
        maximum_links: int | None,
    ) -> list[dict[str, str]]:
        effective_minimum = min(minimum_links, len(eligible.candidates))
        if effective_minimum <= 0:
            return selected_links[:maximum_links] if maximum_links is not None else selected_links
        completed: list[dict[str, str]] = []
        records = {row.link_id: row for row in eligible.candidates}
        seen_urls: set[str] = set()
        seen_anchors: set[str] = set()
        limit = maximum_links if maximum_links is not None else len(eligible.candidates)

        def add(link_id: str, anchor_text: str) -> None:
            if len(completed) >= limit:
                return
            record = records.get(link_id)
            if record is None:
                return
            anchor = str(anchor_text or record.anchor_text).strip()
            if anchor not in {record.anchor_text, *record.anchor_variants}:
                anchor = record.anchor_text
            normalized_anchor = anchor.casefold()
            if record.target_url in seen_urls or normalized_anchor in seen_anchors:
                return
            seen_urls.add(record.target_url)
            seen_anchors.add(normalized_anchor)
            completed.append({"link_id": record.link_id, "anchor_text": anchor})

        for selection in selected_links:
            add(str(selection.get("link_id") or ""), str(selection.get("anchor_text") or ""))
        if len(completed) >= effective_minimum:
            return completed
        for record in eligible.candidates:
            add(record.link_id, record.anchor_text)
            if len(completed) >= effective_minimum:
                break
        return completed

    def approve(
        self,
        session_id: str,
        *,
        user_id: str,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        approval = Approval(
            approved=True,
            approved_by=user_id,
            approved_at=datetime.now(timezone.utc),
        )
        updated = session.model_copy(update={"approval": approval})
        updated = SessionStateMachine(snapshot).transition(updated, "ready_to_publish")
        return self.repository.save(updated, expected_version=expected_version)

    def update_draft_fields(
        self,
        session_id: str,
        *,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        if not session.wordpress_payload:
            raise DraftValidationError("Generate a draft before saving manual draft edits.")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        updated_shared = {
            **session.shared_fields,
            **(shared_fields or {}),
        }
        updated_acf = {
            **session.acf_source_fields,
            **(acf_source_fields or {}),
        }
        payload = self.payload_builder.build(
            snapshot,
            post_type_key=session.post_type_key,
            shared_values=updated_shared,
            acf_source_values=updated_acf,
            media=session.image_metadata,
        )
        updated = session.model_copy(
            update={
                "shared_fields": updated_shared,
                "acf_source_fields": updated_acf,
                "wordpress_payload": payload.model_dump(),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._milestone(updated, "manual draft fields saved")
        return self.repository.save(updated, expected_version=expected_version)

    def publish(
        self,
        session_id: str,
        *,
        idempotency_key: str,
        expected_version: int,
        target_post_id: int | None = None,
        force_create_new: bool = False,
        partial_update: bool = False,
        shared_fields: dict[str, Any] | None = None,
        acf_source_fields: dict[str, Any] | None = None,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        self._milestone(session, "publication started")
        if (
            session.state == "published"
            and session.publication_idempotency_key == idempotency_key
            and session.wordpress_result
            and not target_post_id
            and not force_create_new
        ):
            return session
        if not session.approval.approved:
            raise PublishingNotApprovedError("Explicit approval is required before publication.")
        if self.wordpress is None:
            raise RuntimeError("A WordPressProvider is not configured.")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        partial_update = bool(partial_update and target_post_id and not force_create_new)
        changed_shared = dict(shared_fields or {})
        changed_acf = dict(acf_source_fields or {})
        partial_update_fields = (
            self._wordpress_partial_update_fields(
                snapshot,
                session.post_type_key,
                shared_fields=changed_shared,
                acf_source_fields=changed_acf,
            )
            if partial_update
            else None
        )
        state_machine = SessionStateMachine(snapshot)
        refined = self._generate_missing_image_metadata(
            snapshot,
            session,
            overwrite_existing=True,
        )
        if shared_fields or acf_source_fields:
            refined = refined.model_copy(
                update={
                    "shared_fields": {
                        **refined.shared_fields,
                        **(shared_fields or {}),
                    },
                    "acf_source_fields": {
                        **refined.acf_source_fields,
                        **(acf_source_fields or {}),
                    },
                }
            )
        self._milestone(refined, "publication metadata refinement finished")
        if shared_fields or acf_source_fields or refined.image_refs:
            payload = self.payload_builder.build(
                snapshot,
                post_type_key=refined.post_type_key,
                shared_values=refined.shared_fields,
                acf_source_values=refined.acf_source_fields,
                media=refined.image_metadata,
            )
            refined = refined.model_copy(update={"wordpress_payload": payload.model_dump()})
        publishing = (
            refined.model_copy(update={"state": "publishing"})
            if refined.state == "published"
            else state_machine.transition(refined, "publishing")
        )
        try:
            wordpress_payload = WordPressPayload.model_validate(publishing.wordpress_payload)
            if partial_update:
                if publishing.published_wordpress_payload:
                    payload_diff_fields = self._wordpress_payload_diff_fields(
                        wordpress_payload.model_dump(),
                        publishing.published_wordpress_payload,
                    )
                    partial_update_fields = self._merge_partial_update_fields(
                        partial_update_fields or {},
                        payload_diff_fields,
                    )
                if not any(partial_update_fields.values()):
                    self._milestone(session, "publication skipped; no changed WordPress fields")
                    return session
            wordpress_payload = wordpress_payload.model_copy(
                update={
                    "media": self._materialize_publication_media(
                        publishing,
                        wordpress_payload.media,
                    )
                }
            )
            result = self.wordpress.publish(
                session=publishing,
                payload=wordpress_payload,
                idempotency_key=idempotency_key,
                target_post_id=target_post_id,
                force_create_new=force_create_new,
                partial_update_fields=partial_update_fields,
            )
        except Exception as exc:
            raise WordPressRequestError(f"WordPress publication failed: {exc}") from exc
        published = publishing.model_copy(
            update={
                "wordpress_result": result,
                "publication_idempotency_key": idempotency_key,
                "published_wordpress_payload": wordpress_payload.model_dump(),
            }
        )
        published = state_machine.transition(published, "published")
        self._milestone(published, "publication finished")
        return self.repository.save(published, expected_version=expected_version)

    @staticmethod
    def _merge_partial_update_fields(
        *items: dict[str, set[str]],
    ) -> dict[str, set[str]]:
        merged: dict[str, set[str]] = {
            "wordpress": set(),
            "meta": set(),
            "acf": set(),
        }
        for item in items:
            for group in merged:
                merged[group].update(item.get(group, set()))
        return merged

    @staticmethod
    def _wordpress_payload_diff_fields(
        current: dict[str, Any],
        previous: dict[str, Any],
    ) -> dict[str, set[str]]:
        fields: dict[str, set[str]] = {
            "wordpress": set(),
            "meta": set(),
            "acf": set(),
        }
        if not previous:
            return fields
        for key, value in dict(current.get("wordpress") or {}).items():
            if value != dict(previous.get("wordpress") or {}).get(key):
                fields["wordpress"].add(key)
        for key, value in dict(current.get("meta") or {}).items():
            if value != dict(previous.get("meta") or {}).get(key):
                fields["meta"].add(key)
        for key, value in dict(current.get("acf") or {}).items():
            if value != dict(previous.get("acf") or {}).get(key):
                fields["acf"].add(key)
        return fields

    @staticmethod
    def _wordpress_partial_update_fields(
        snapshot: Any,
        post_type_key: str,
        *,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
    ) -> dict[str, set[str]]:
        fields: dict[str, set[str]] = {
            "wordpress": set(),
            "meta": set(),
            "acf": set(),
        }
        shared_by_key = {
            row.field_key: row
            for row in snapshot.shared_fields
            if row.enabled and row.include_in_payload
        }
        for field_key in shared_fields:
            row = shared_by_key.get(field_key)
            if row is None:
                continue
            if row.destination_type == "wordpress":
                fields["wordpress"].add(row.destination_key)
            elif row.destination_type == "yoast":
                fields["meta"].add(row.destination_key)
            elif row.destination_type == "acf":
                fields["acf"].add(row.destination_key)

        acf_rows = [
            row
            for row in snapshot.acf_fields
            if row.enabled and row.post_type_key == post_type_key
        ]
        acf_by_key = {row.field_key: row for row in acf_rows}
        for field_key in acf_source_fields:
            row = acf_by_key.get(field_key)
            if row is None:
                continue
            if row.field_role == "direct_acf":
                fields["acf"].add(row.acf_field_name or field_key)
            elif row.field_role == "aggregation_source" and row.aggregation_group:
                for group_row in acf_rows:
                    if group_row.aggregation_group == row.aggregation_group and group_row.acf_field_name:
                        fields["acf"].add(group_row.acf_field_name)
        return fields

    def _materialize_publication_media(
        self,
        session: ContentSession,
        media: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        processed_by_media = {
            str(item.get("media_id")): item
            for item in session.processed_images
            if item.get("media_id")
        }
        materialized: list[dict[str, Any]] = []
        for item in media:
            next_item = dict(item)
            uri = str(next_item.get("path") or next_item.get("output") or "").strip()
            if uri:
                processed = processed_by_media.get(str(next_item.get("media_id") or ""))
                filename = (
                    str((processed or {}).get("filename") or "").strip()
                    or self._filename_from_uri(uri)
                    or f"{next_item.get('media_id') or 'media'}.bin"
                )
                path = self._materialize_media_uri(
                    uri,
                    session_id=session.session_id,
                    filename=filename,
                )
                next_item["path"] = str(path)
                next_item["output"] = str(path)
            materialized.append(next_item)
        return materialized

    @staticmethod
    def _filename_from_uri(uri: str) -> str:
        value = str(uri or "").rstrip("/")
        if not value:
            return ""
        return value.rsplit("/", 1)[-1]
