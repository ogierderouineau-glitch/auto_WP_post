from __future__ import annotations

import uuid
import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Literal
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter, sleep

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

try:
    from PIL import Image
except Exception:
    Image = None

from backend.app.context.step_01_builder import GenerationContextBuilder
from backend.app.content_generation.step_01_schema_factory import (
    build_fact_extraction_model,
    build_generation_model,
    build_image_analysis_model,
    build_image_metadata_batch_model,
    build_image_metadata_model,
)
from backend.app.content_generation.step_02_prompts import structured_task_input
from backend.app.errors import (
    DraftValidationError,
    ImageProcessingError,
    InvalidInternalLinksError,
    InvalidUploadError,
    MissingRequiredFactsError,
    ModelOutputValidationError,
    ModelProviderError,
    PublishingNotApprovedError,
    SessionOwnershipError,
    UnknownPostTypeError,
    TranscriptionProviderError,
    VisionProviderError,
    VideoProcessingError,
    WordPressRequestError,
)
from backend.app.internal_links.step_01_service import InternalLinkInjectionResult, InternalLinkService
from backend.app.images.step_02_processor import PillowProcessor
from backend.app.images.step_03_metadata_context import (
    ImageMetadataFieldContextBuilder,
    ImageMetadataRuleMatcher,
)
from backend.app.knowledge_base.step_04_service import KnowledgeBaseService
from backend.app.models.step_01_session import Approval, ContentSession, FactValue, OperationRecord
from backend.app.models.step_02_payload import WordPressPayload
from backend.app.payloads.step_02_builder import PayloadBuilder
from backend.app.providers.step_01_interfaces import WordPressProvider
from backend.app.providers.step_01_interfaces import (
    ImageEditingProvider,
    LanguageModelProvider,
    ObjectStorageProvider,
    SpeechToTextProvider,
    VisionProvider,
)
from backend.app.sessions.step_01_repository import SessionRepository
from backend.app.sessions.step_02_state_machine import SessionStateMachine
from backend.app.storage.step_02_uploads import safe_upload_name
from backend.app.videos.step_01_processor import FfmpegVideoProcessor
from backend.app.workflow.step_04_generation_conditions import (
    GenerationConditionEvaluator,
    fact_is_usable,
    source_fact_dependencies_are_available,
)
from backend.app.workflow.step_02_clarification import ClarificationService
from backend.app.validation.step_01_draft import DraftValidator


class ContentSessionService:
    """Application service for the typed content session lifecycle."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeBaseService,
        repository: SessionRepository,
        wordpress: WordPressProvider | None = None,
        language_model: LanguageModelProvider | None = None,
        revision_language_model: LanguageModelProvider | None = None,
        metadata_language_model: LanguageModelProvider | None = None,
        speech_to_text: SpeechToTextProvider | None = None,
        vision: VisionProvider | None = None,
        image_editor: ImageEditingProvider | None = None,
        object_storage: ObjectStorageProvider | None = None,
        image_processor: PillowProcessor | None = None,
        video_processor: FfmpegVideoProcessor | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.repository = repository
        self.wordpress = wordpress
        self.language_model = language_model
        self.revision_language_model = revision_language_model or language_model
        self.metadata_language_model = metadata_language_model or language_model
        self.speech_to_text = speech_to_text
        self.vision = vision
        self.image_editor = image_editor
        self.object_storage = object_storage
        self.image_processor = image_processor
        self.video_processor = video_processor or FfmpegVideoProcessor()
        self.clarification = ClarificationService()
        self.context_builder = GenerationContextBuilder()
        self.payload_builder = PayloadBuilder()
        self.internal_links = InternalLinkService()
        self.draft_validator = DraftValidator()
        self.generation_condition_evaluator = GenerationConditionEvaluator()
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

    @staticmethod
    def _user_id_candidates(user_id: str | None) -> set[str]:
        candidates: set[str] = set()
        if not user_id:
            return candidates
        normalized = str(user_id).strip()
        if not normalized:
            return candidates
        candidates.add(normalized)
        if not normalized.endswith("-user"):
            candidates.add(f"{normalized}-user")
        else:
            candidates.add(normalized[:-5])
        return candidates

    @classmethod
    def _matches_user_scope(cls, session: ContentSession, user_id: str | None) -> bool:
        if not user_id:
            return True
        return session.user_id in cls._user_id_candidates(user_id)

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
            if user_id and not self._matches_user_scope(session, user_id):
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
                if user_id and not self._matches_user_scope(session, user_id):
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
        if not user_id or not self._matches_user_scope(session, user_id):
            raise SessionOwnershipError("The authenticated user does not own this session.")
        return session

    def record_operation(
        self,
        session_id: str,
        *,
        operation: str,
        status: str,
        started_at: datetime,
        duration_seconds: float,
        usage_before: dict[str, Any] | None = None,
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        before = usage_before or {}
        after = session.ai_usage or {}
        prompt_tokens = max(0, int(after.get("prompt_tokens") or 0) - int(before.get("prompt_tokens") or 0))
        completion_tokens = max(0, int(after.get("completion_tokens") or 0) - int(before.get("completion_tokens") or 0))
        total_tokens = max(0, int(after.get("total_tokens") or 0) - int(before.get("total_tokens") or 0))
        before_cost = float(before.get("estimated_cost_usd") or 0.0)
        after_cost = float(after.get("estimated_cost_usd") or 0.0)
        estimated_cost = max(0.0, after_cost - before_cost)
        call_delta = max(0, int(after.get("call_count") or 0) - int(before.get("call_count") or 0))
        operation_calls = list(after.get("calls") or [])[-call_delta:] if call_delta else []
        cost_known = bool(operation_calls) and all(
            call.get("estimated_cost_usd") is not None for call in operation_calls
        )
        finished_at = datetime.now(timezone.utc)
        record = OperationRecord.model_validate({
            "operation_id": uuid.uuid4().hex,
            "operation": operation,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": round(max(0.0, duration_seconds), 3),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(estimated_cost, 8) if cost_known else None,
            "error": error,
            "details": {**(details or {}), "model_calls": operation_calls},
        })
        return self.repository.save(
            session.model_copy(update={"operation_log": [record, *session.operation_log][:100]}),
            expected_version=session.version,
        )

    def update_generation_settings(
        self,
        session_id: str,
        *,
        language_model: str,
        reasoning_effort: str,
        generation_mode: str = "single",
        expected_version: int,
    ) -> ContentSession:
        # Settings are a field-scoped merge. Re-read the latest session so an
        # unrelated operation-log write cannot make this harmless update fail.
        del expected_version
        session = self.repository.get(session_id)
        return self.repository.save(
            session.model_copy(update={
                "language_model": language_model,
                "reasoning_effort": reasoning_effort,
                "generation_mode": generation_mode,
                "updated_at": datetime.now(timezone.utc),
            }),
            expected_version=session.version,
        )

    def review_content_quality(
        self,
        session_id: str,
        *,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        if session.version != expected_version:
            raise ValueError(
                f"Session version conflict: expected {expected_version}, found {session.version}."
            )
        if not session.wordpress_payload:
            raise DraftValidationError("Generate a draft before running a quality check.")

        fields = [
            {
                "field_id": f"{scope}:{key}",
                "label": key,
                "value": value,
            }
            for scope, values in (
                ("shared", session.shared_fields),
                ("acf", session.acf_source_fields),
            )
            for key, value in values.items()
            if isinstance(value, str) and value.strip()
        ]
        if not fields:
            raise DraftValidationError("The draft has no text fields to review.")

        field_ids = tuple(item["field_id"] for item in fields)
        field_id_type = Literal.__getitem__(field_ids)
        finding_model = create_model(
            "ContentQualityFinding",
            __config__=ConfigDict(extra="forbid"),
            field_id=(field_id_type, ...),
            category=(
                Literal[
                    "generic_marketing",
                    "repetition",
                    "sentence_rhythm",
                    "unnatural_transition",
                    "translated_phrasing",
                    "unsupported_personalization",
                    "overwritten_style",
                    "other",
                ],
                ...,
            ),
            severity=(Literal["low", "medium", "high"], ...),
            explanation=(str, Field(min_length=1)),
            suggestion=(str, Field(min_length=1)),
        )
        review_model = create_model(
            "ContentQualityReview",
            __config__=ConfigDict(extra="forbid"),
            rating=(Literal["natural", "needs_polish", "formulaic"], ...),
            summary=(str, Field(min_length=1)),
            findings=(list[finding_model], Field(default_factory=list)),
        )
        result = self._structured(
            task="content_quality_check",
            messages=structured_task_input(
                task="content_quality_check",
                instructions=[
                    {
                        "instruction": (
                            "Act as a German-language editorial quality reviewer, not an AI-text detector. "
                            "Identify only concrete issues with clarity, specificity, repetition, sentence "
                            "rhythm, transitions, translated phrasing, generic marketing language, overly "
                            "polished wording, or unsupported personalization. "
                            "Do not penalize necessary SEO terminology, factual business language, "
                            "HTML markup, field length constraints, or a professional tone. "
                            "Return concise, actionable findings. Do not rewrite the content."
                        )
                    }
                ],
                context={
                    "language": session.language,
                    "post_type": session.post_type_key,
                    "fields": fields,
                    "confirmed_facts": {
                        key: fact.model_dump()
                        for key, fact in session.confirmed_facts.items()
                        if fact.confirmed
                    },
                },
            ),
            schema=review_model,
            provider=self.revision_language_model,
        )
        session = self._record_provider_usage(session, self.revision_language_model)
        trace = dict(session.generation_trace)
        trace.pop("humanness_review", None)
        trace["quality_check"] = {
            **result.model_dump(),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_field_count": len(fields),
        }
        return self.repository.save(
            session.model_copy(
                update={
                    "generation_trace": trace,
                    "updated_at": datetime.now(timezone.utc),
                }
            ),
            expected_version=expected_version,
        )

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
        aspect_ratio: str | None = None,
    ) -> ContentSession:
        if self.object_storage is None:
            raise RuntimeError("An ObjectStorageProvider is not configured.")
        session = self.repository.get(session_id)
        self._milestone(session, f"upload received kind={kind} filename={filename}")
        from backend.app.models.step_01_session import MediaReference

        media_id = uuid.uuid4().hex
        processed_video: dict[str, Any] | None = None
        if kind == "video":
            with tempfile.TemporaryDirectory(prefix="v2-video-") as directory:
                try:
                    result = self.video_processor.process(
                        source,
                        Path(directory),
                        Path(filename).stem,
                    )
                except Exception as exc:
                    raise VideoProcessingError(
                        f"Video processing failed: {exc}"
                    ) from exc
                storage_uri = self.object_storage.put(
                    result.video,
                    f"{session.session_id}/video/{result.video.name}",
                )
                poster_uri = self.object_storage.put(
                    result.poster,
                    f"{session.session_id}/video/{result.poster.name}",
                )
                reference = MediaReference(
                    media_id=media_id,
                    filename=result.video.name,
                    storage_uri=storage_uri,
                    content_type="video/mp4",
                    size_bytes=result.video.stat().st_size,
                )
                processed_video = {
                    "media_id": media_id,
                    "filename": result.video.name,
                    "path": storage_uri,
                    "poster_filename": result.poster.name,
                    "poster_path": poster_uri,
                    "operations": list(result.operations),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
        else:
            storage_uri = self.object_storage.put(
                source,
                f"{session.session_id}/{kind}/{filename}",
            )
            reference = MediaReference(
                media_id=media_id,
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
        elif kind == "video":
            changes["video_refs"] = [*session.video_refs, reference]
            changes["processed_videos"] = [*session.processed_videos, processed_video]
            changes["video_metadata"] = [
                *session.video_metadata,
                {
                    "media_id": media_id,
                    "video_title": Path(filename).stem,
                    "video_caption": "",
                    "video_description": "",
                },
            ]
        else:
            raise ValueError(f"Unsupported upload kind: {kind}")
        updated = session.model_copy(update=changes)
        if updated.state == "created":
            updated = SessionStateMachine(
                self.knowledge.by_hash(updated.workbook_hash)
            ).transition(updated, "uploading")
        persisted = self.repository.save(updated, expected_version=expected_version)
        if kind == "image":
            snapshot = self.knowledge.by_hash(persisted.workbook_hash)
            enriched = persisted
            try:
                if use_vision:
                    self._milestone(enriched, "image Vision analysis started")
                    enriched = self._analyze_missing_images(
                        snapshot,
                        enriched,
                        media_ids={reference.media_id},
                    )
                    self._milestone(enriched, "image Vision analysis finished")
                self._milestone(enriched, "Pillow processing started")
                enriched = self._process_missing_images(
                    snapshot,
                    enriched,
                    media_ids={reference.media_id},
                    aspect_ratio=aspect_ratio,
                )
                self._milestone(enriched, "Pillow processing finished")
            except Exception as exc:
                self._milestone(persisted, f"image enrichment deferred after upload: {exc}")
                return persisted
            return self.repository.save(enriched, expected_version=persisted.version)
        return persisted

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

    def analyze(
        self,
        session_id: str,
        *,
        expected_version: int,
        review_fact_keys: list[str] | None = None,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        self._milestone(session, "analysis started")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        if review_fact_keys is not None:
            available_fact_keys = {
                row.field_key
                for row in snapshot.acf_fields
                if row.enabled
                and row.post_type_key == session.post_type_key
                and row.field_role == "input_fact"
            }
            if not review_fact_keys:
                raise InvalidUploadError("Select at least one fact to review.")
            invalid_fact_keys = set(review_fact_keys) - available_fact_keys
            if invalid_fact_keys:
                raise InvalidUploadError(
                    f"Unknown facts selected for review: {', '.join(sorted(invalid_fact_keys))}."
                )
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
            if review_fact_keys is not None:
                input_rows = [row for row in input_rows if row.field_key in review_fact_keys]
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
            analysis_provider = self._session_language_provider(session)
            parsed = self._structured(
                task="fact_extraction",
                messages=messages,
                schema=response_model,
                provider=analysis_provider,
            )
            session = self._record_provider_usage(session, analysis_provider)
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
                if review_fact_keys is not None:
                    confirmed.pop(key, None)
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
        state_machine = SessionStateMachine(snapshot)
        corrections = self._normalize_fact_values(
            snapshot,
            session.post_type_key,
            corrections,
        )
        updated = self.clarification.apply_corrections(session, corrections)
        updated = updated.model_copy(update={"clarification_questions": []})
        missing = self.clarification.missing_required_dependencies(snapshot, updated)
        if missing:
            updated = updated.model_copy(
                update={"clarification_questions": self.clarification.bundled_questions(missing)}
            )
            if updated.state != "needs_input":
                updated = state_machine.transition(updated, "needs_input")
        elif updated.state in {"needs_input", "analyzing", "uploading"}:
            updated = state_machine.transition(updated, "ready_to_generate")
        return self.repository.save(updated, expected_version=expected_version)

    def update_image_metadata(
        self,
        session_id: str,
        *,
        filename: str,
        metadata: dict[str, Any],
        use_vision_for_metadata: bool | None = None,
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
                "image_usage": metadata.get("image_usage") or existing.get("image_usage") or "gallery",
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
                "visible_taxonomy_terms": metadata.get(
                    "visible_taxonomy_terms",
                    existing.get("visible_taxonomy_terms", {}),
                ),
            }
        )
        image_metadata_vision = dict(session.image_metadata_vision)
        if use_vision_for_metadata is not None:
            if use_vision_for_metadata:
                image_metadata_vision[reference.media_id] = True
            else:
                image_metadata_vision.pop(reference.media_id, None)
        updated = session.model_copy(
            update={
                "image_metadata": sorted(
                    image_metadata,
                    key=lambda row: int(row.get("image_priority") or 999),
                ),
                "image_metadata_vision": image_metadata_vision,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self.repository.save(updated, expected_version=expected_version)

    def update_image_context_transcript(
        self,
        session_id: str,
        *,
        filename: str,
        transcript: str,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        reference, _ = self._find_image_reference_and_processed(session, filename)
        image_context_transcripts = dict(session.image_context_transcripts)
        cleaned = str(transcript or "").strip()
        if str(image_context_transcripts.get(reference.media_id) or "") == cleaned:
            return session
        if cleaned:
            image_context_transcripts[reference.media_id] = cleaned
        else:
            image_context_transcripts.pop(reference.media_id, None)
        updated = session.model_copy(
            update={
                "image_context_transcripts": image_context_transcripts,
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
        if kind == "video":
            processed = next(
                (
                    item for item in session.processed_videos
                    if item.get("filename") == filename
                    or item.get("poster_filename") == filename
                ),
                None,
            )
            if processed is not None:
                uri = (
                    processed.get("poster_path")
                    if processed.get("poster_filename") == filename
                    else processed.get("path")
                )
                return self._materialize_media_uri(
                    str(uri or ""),
                    session_id=session_id,
                    filename=filename,
                )
            reference = next((ref for ref in session.video_refs if ref.filename == filename), None)
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
                / "speech2post-media-cache"
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
            image_context_transcripts = dict(session.image_context_transcripts)
            image_context_transcripts.pop(media_id, None)
            updates["image_context_transcripts"] = image_context_transcripts
            image_metadata_vision = dict(session.image_metadata_vision)
            image_metadata_vision.pop(media_id, None)
            updates["image_metadata_vision"] = image_metadata_vision
        elif kind == "voices":
            reference = next((ref for ref in session.audio_refs if ref.filename == filename), None)
            if reference is None:
                raise ValueError(f"Voice not found in this session: {filename}")
            updates["audio_refs"] = [
                ref for ref in session.audio_refs if ref.media_id != reference.media_id
            ]
            if not updates["audio_refs"]:
                updates["transcript"] = ""
        elif kind == "videos":
            reference = next((ref for ref in session.video_refs if ref.filename == filename), None)
            if reference is None:
                raise ValueError(f"Video not found in this session: {filename}")
            media_id = reference.media_id
            updates["video_refs"] = [ref for ref in session.video_refs if ref.media_id != media_id]
            updates["processed_videos"] = [
                item for item in session.processed_videos if item.get("media_id") != media_id
            ]
            updates["video_metadata"] = [
                item for item in session.video_metadata if item.get("media_id") != media_id
            ]
            transcripts = dict(session.video_context_transcripts)
            transcripts.pop(media_id, None)
            updates["video_context_transcripts"] = transcripts
        else:
            raise ValueError(f"Unsupported media kind: {kind}")
        return self.repository.save(session.model_copy(update=updates), expected_version=expected_version)

    def save_video_metadata(
        self,
        session_id: str,
        *,
        filename: str,
        metadata: dict[str, Any],
        transcript: str,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        reference = next((ref for ref in session.video_refs if ref.filename == filename), None)
        if reference is None:
            raise ValueError(f"Video not found in this session: {filename}")
        allowed = {
            key: str(metadata.get(key) or "")
            for key in ("video_title", "video_caption", "video_description")
        }
        rows = [
            *(
                item for item in session.video_metadata
                if item.get("media_id") != reference.media_id
            ),
            {"media_id": reference.media_id, **allowed},
        ]
        transcripts = {
            **session.video_context_transcripts,
            reference.media_id: transcript,
        }
        return self.repository.save(
            session.model_copy(update={
                "video_metadata": rows,
                "video_context_transcripts": transcripts,
                "updated_at": datetime.now(timezone.utc),
            }),
            expected_version=expected_version,
        )

    def optimize_image(
        self,
        session_id: str,
        *,
        filename: str,
        prompt: str,
        expected_version: int,
    ) -> ContentSession:
        if self.image_editor is None or self.object_storage is None:
            raise ImageProcessingError("Image editing is not configured.")
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        edit_instructions = sorted(
            (
                row for row in getattr(snapshot, "agent_instructions", ())
                if row.enabled
                and row.owner == "language_model"
                and row.post_type_key in {"*", session.post_type_key}
                and row.workflow_stage == "ai_image_edit"
                and row.condition in {"always", "ai_edit_requested"}
            ),
            key=lambda row: ({"high": 0, "medium": 1, "low": 2}.get(row.priority, 9), row.instruction_id),
        )
        effective_prompt = prompt
        if edit_instructions:
            rules = "\n".join(
                "\n".join(
                    part
                    for part in (
                        f"{index}. Regel: {row.instruction_de.strip()}",
                        f"   Erwartetes Verhalten: {row.expected_behavior.strip()}"
                        if row.expected_behavior.strip() else "",
                    )
                    if part
                )
                for index, row in enumerate(edit_instructions, 1)
                if row.instruction_de.strip()
            )
            effective_prompt = (
                "Bearbeite das bereitgestellte Originalbild. Die folgenden Regeln sind verbindliche "
                "Erhaltungsbedingungen:\n"
                f"{rules}\n\n"
                "Führe ausschließlich die folgende ausdrücklich gewünschte Änderung aus:\n"
                f"{prompt}\n\n"
                "Alle nicht ausdrücklich genannten Bildbereiche, Personen, Gesichter, Identitätsmerkmale, "
                "Körpermerkmale und Umgebungsdetails müssen möglichst unverändert bleiben. Erfinde, entferne "
                "oder ersetze keine weiteren Elemente."
            )
        reference, processed = self._find_image_reference_and_processed(session, filename)
        if processed is None:
            raise ValueError(f"Processed image not found in this session: {filename}")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.object_storage.get(
                reference.storage_uri,
                root / reference.filename,
            )
            output_name = str(processed.get("filename") or f"{Path(reference.filename).stem}.png")
            edited = (
                root / f"ai-edit-{Path(output_name).stem}.png"
                if self.image_processor is not None
                else root / output_name
            )
            try:
                edited = self.image_editor.edit(source, edited, {"prompt": effective_prompt})
            except Exception as exc:
                raise ImageProcessingError(f"Image edit failed: {exc}") from exc
            normalization: dict[str, Any] = {}
            if self.image_processor is not None:
                normalized = root / output_name
                try:
                    normalization = self.image_processor.process(
                        snapshot,
                        source=edited,
                        destination=normalized,
                        analysis=session.image_analysis.get(reference.media_id, {}),
                        stages={"prepare", "crop", "resize", "export"},
                    )
                except Exception as exc:
                    raise ImageProcessingError(f"Edited image normalization failed: {exc}") from exc
                edited = normalized
            storage_uri = self.object_storage.put(
                edited,
                f"{session.session_id}/processed/{edited.name}",
            )
            edited_size = edited.stat().st_size
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
            operations.extend(str(value) for value in normalization.get("operations", []))
            processed_images.append(
                {
                    **item,
                    **{
                        key: normalization[key]
                        for key in (
                            "size_bytes", "width", "height", "format", "quality",
                            "target_bytes", "target_reached", "warnings",
                        )
                        if key in normalization
                    },
                    "path": storage_uri,
                    "output": storage_uri,
                    "size_bytes": edited_size,
                    "operations": operations[-20:],
                    "image_optimization": {
                        "prompt": prompt,
                        "applied_instruction_ids": [row.instruction_id for row in edit_instructions],
                        "applied_instructions": [
                            {
                                "instruction_id": row.instruction_id,
                                "instruction": row.instruction_de,
                                "expected_behavior": row.expected_behavior,
                            }
                            for row in edit_instructions
                        ],
                        "effective_prompt": effective_prompt,
                        "pillow_normalized": bool(normalization),
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

    def recrop_image_with_vision(
        self,
        session_id: str,
        *,
        filename: str,
        expected_version: int,
    ) -> ContentSession:
        if self.vision is None or self.image_processor is None or self.object_storage is None:
            raise ImageProcessingError("Vision recropping is not configured.")
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        reference, processed = self._find_image_reference_and_processed(session, filename)
        if processed is None:
            raise ValueError(f"Processed image not found in this session: {filename}")

        image_analysis = dict(session.image_analysis)
        image_analysis.pop(reference.media_id, None)
        working = session.model_copy(
            update={
                "image_analysis": image_analysis,
                "processed_images": [
                    item
                    for item in session.processed_images
                    if item.get("media_id") != reference.media_id
                ],
            }
        )
        working = self._analyze_missing_images(
            snapshot,
            working,
            media_ids={reference.media_id},
        )
        working = self._process_missing_images(
            snapshot,
            working,
            media_ids={reference.media_id},
            aspect_ratio=str(processed.get("aspect_ratio") or "") or None,
        )
        processed_images = []
        for item in working.processed_images:
            if item.get("media_id") != reference.media_id:
                processed_images.append(item)
                continue
            operations = [
                str(operation)
                for operation in item.get("operations", item.get("applied_operations", []))
                if str(operation).strip()
            ]
            operations.append("vision_focal_recrop")
            processed_images.append({
                **item,
                "operations": operations[-20:],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        return self.repository.save(
            working.model_copy(
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
            restored = self._copy_image_for_output_name(original, root / output_name)
            storage_uri = self.object_storage.put(
                restored,
                f"{session.session_id}/processed/{output_name}",
            )
            restored_size = restored.stat().st_size
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
                    "size_bytes": restored_size,
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

    @staticmethod
    def _copy_image_for_output_name(source: Path, destination: Path) -> Path:
        if source == destination:
            return source
        destination.parent.mkdir(parents=True, exist_ok=True)
        if Image is None:
            destination.write_bytes(source.read_bytes())
            return destination
        try:
            with Image.open(source) as opened:
                image = opened.convert("RGB") if opened.mode != "RGB" else opened.copy()
            suffix = destination.suffix.lower()
            if suffix == ".webp":
                image.save(destination, format="WEBP", quality=90, method=6)
            elif suffix in {".jpg", ".jpeg"}:
                image.save(destination, format="JPEG", quality=92, optimize=True, progressive=True)
            elif suffix == ".png":
                image.save(destination, format="PNG", optimize=True)
            else:
                image.save(destination, format="WEBP", quality=90, method=6)
        except Exception:
            destination.write_bytes(source.read_bytes())
        return destination

    def generate(
        self,
        session_id: str,
        *,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
        selected_links: list[dict[str, str]],
        current_url: str | None,
        use_vision_for_image_metadata: bool = True,
        ai_assisted_link_placement: bool = False,
        link_placement_only: bool = False,
        revision_instruction: str | None = None,
        revision_field_ids: list[str] | None = None,
        expected_version: int,
    ) -> ContentSession:
        session = self.repository.get(session_id)
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        is_regeneration = session.state in {"needs_review", "ready_to_publish", "published"}
        if is_regeneration:
            latest_snapshot = self.knowledge.current()
            if latest_snapshot.version.sha256 != session.workbook_hash:
                post_type = latest_snapshot.post_type(session.post_type_key)
                if (
                    post_type is None
                    or not post_type.enabled
                    or not post_type.generation_enabled
                    or not post_type.template_ready
                ):
                    raise UnknownPostTypeError(
                        f"Post type {session.post_type_key!r} is unavailable in the latest workbook."
                    )
                previous_hash = session.workbook_hash
                snapshot = latest_snapshot
                session = session.model_copy(
                    update={
                        "workbook_hash": snapshot.version.sha256,
                        "wordpress_post_type": post_type.wp_post_type,
                        "workflow_steps": {
                            row.step_key: session.workflow_steps.get(row.step_key, "pending")
                            for row in snapshot.workflow_steps
                        },
                        "generation_trace": {
                            **session.generation_trace,
                            "workbook_refresh": {
                                "previous_hash": previous_hash,
                                "current_hash": snapshot.version.sha256,
                            },
                        },
                    }
                )
        targeted_revision = revision_instruction is not None and revision_field_ids is not None
        fresh_generation = not targeted_revision and not shared_fields and not acf_source_fields
        selected_shared_keys = {
            field_id.removeprefix("shared:")
            for field_id in revision_field_ids or []
            if field_id.startswith("shared:")
        }
        selected_acf_keys = {
            field_id.removeprefix("acf:")
            for field_id in revision_field_ids or []
            if field_id.startswith("acf:")
        }
        if targeted_revision:
            available_field_ids = {
                *(f"shared:{key}" for key in session.shared_fields),
                *(f"acf:{key}" for key in session.acf_source_fields),
            }
            invalid_field_ids = set(revision_field_ids or []) - available_field_ids
            if invalid_field_ids:
                raise InvalidUploadError(
                    f"Unknown draft revision fields: {', '.join(sorted(invalid_field_ids))}."
                )
            shared_fields = dict(session.shared_fields)
            acf_source_fields = dict(session.acf_source_fields)
        missing = self.clarification.missing_required_dependencies(snapshot, session)
        if missing:
            raise MissingRequiredFactsError(
                "Required fact dependencies remain unresolved."
            )
        state_machine = SessionStateMachine(snapshot)
        if session.state in {"ready_to_generate", "needs_review"}:
            session = state_machine.transition(session, "generating")
        generation_trace = dict(session.generation_trace)
        generation_trace.pop("humanness_review", None)
        eligible = self.internal_links.eligible(
            snapshot,
            post_type_key=session.post_type_key,
            language=session.language,
            current_url=current_url,
        )
        _, maximum_links = self._internal_link_range(snapshot)
        if not targeted_revision and not selected_links and eligible.candidates:
            self._milestone(session, "deterministic internal link ranking started")
            fact_text = " ".join(
                str(value.value)
                for value in session.confirmed_facts.values()
                if value.confirmed and value.value not in (None, "", [])
            )
            selected_links = self.internal_links.rank(
                eligible,
                source_text=" ".join((session.manual_text, session.transcript, fact_text)),
                context_tags=session.context_tags,
                content_signals=session.content_signals,
                maximum=maximum_links,
            )
            self._milestone(session, "deterministic internal link ranking finished")
        if maximum_links is not None and len(selected_links) > maximum_links:
            selected_links = selected_links[:maximum_links]
        explicitly_requested_link_ids = {
            str(selection.get("link_id") or "")
            for selection in selected_links
            if selection.get("revision_requested") == "true"
        }
        if self.language_model is not None:
            enum_families = {
                row.list_name: tuple(snapshot.validation_family(row.list_name))
                for row in snapshot.validation_values
            }
            should_generate = (
                (targeted_revision and (not link_placement_only or ai_assisted_link_placement))
                or not shared_fields
                or not acf_source_fields
            )
            if should_generate:
                shared_rows = [
                    row for row in snapshot.shared_fields
                    if row.enabled and row.include_in_ai_schema
                    and (not targeted_revision or row.field_key in selected_shared_keys)
                ]
                derived_acf_fields = self._derive_acf_fields_from_facts(snapshot, session)
                acf_rows = [
                    row for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == session.post_type_key
                    and row.field_role != "input_fact"
                    and row.include_in_ai_schema
                    and row.field_key not in derived_acf_fields
                    and self._acf_field_is_eligible(row, session)
                    and (not targeted_revision or row.field_key in selected_acf_keys)
                ]
                if not targeted_revision:
                    acf_source_fields = {**derived_acf_fields, **acf_source_fields}
                records = {row.link_id: row for row in eligible.candidates}
                selected_link_context = [
                    {
                        "link_id": selection.get("link_id"),
                        "preferred_anchor": selection.get("anchor_text"),
                        "approved_anchor_variants": records[selection.get("link_id")].anchor_variants
                        if selection.get("link_id") in records else (),
                        "usage_context": records[selection.get("link_id")].usage_context
                        if selection.get("link_id") in records else "",
                    }
                    for selection in selected_links
                ]
                generation_provider = (
                    self.revision_language_model
                    if targeted_revision
                    else self._session_language_provider(session)
                )
                acf_batches = self._acf_generation_batches(acf_rows)
                generation_groups = (
                    [("content_generation", "GeneratedContent", "single", [*shared_rows, *acf_rows])]
                    if session.generation_mode == "single"
                    else [
                        ("shared_field_generation", "GeneratedSharedFields", "shared", shared_rows),
                        *[
                            ("acf_field_generation", f"GeneratedACFFields{index}", batch_name, rows)
                            for index, (batch_name, rows) in enumerate(acf_batches, start=1)
                        ],
                    ]
                )
                shared_row_keys = {row.field_key for row in shared_rows}

                def run_generation_group(
                    generation_task: str,
                    model_name: str,
                    batch_name: str,
                    rows: list[Any],
                    provider: LanguageModelProvider,
                    shared_values: dict[str, Any],
                ) -> tuple[str, str, dict[str, Any], Any]:
                    if not rows:
                        return generation_task, batch_name, {}, provider
                    field_keys = [row.field_key for row in rows]
                    context = self.context_builder.build(
                        snapshot=snapshot,
                        task="generation",
                        post_type_key=session.post_type_key,
                        session=session,
                        field_keys=field_keys,
                    )
                    context_payload = context.model_dump(by_alias=True)
                    if targeted_revision:
                        context_payload["examples"] = []
                    if not targeted_revision or ai_assisted_link_placement:
                        context_payload["selected_internal_links"] = selected_link_context
                        if targeted_revision and ai_assisted_link_placement and explicitly_requested_link_ids:
                            context_payload["internal_link_output_contract"] = (
                                "Rewrite the selected internal-link-enabled body fields naturally so every "
                                "explicitly requested link is represented by exactly one of its approved anchor "
                                "phrases verbatim. Every requested link is mandatory. Do not add HTML or URLs; "
                                "the application will inject them after generation."
                            )
                        else:
                            context_payload["internal_link_output_contract"] = (
                                "Where natural and relevant, use one approved anchor phrase verbatim in an "
                                "internal-link-enabled body field. Do not add HTML or URLs and never force a phrase."
                            )
                    context_payload["current_shared_fields"] = {
                        key: value
                        for key, value in session.shared_fields.items()
                        if not fresh_generation
                        and (not targeted_revision or key in selected_shared_keys)
                    }
                    context_payload["current_acf_source_fields"] = {
                        key: value
                        for key, value in session.acf_source_fields.items()
                        if not fresh_generation
                        and (not targeted_revision or key in selected_acf_keys)
                    }
                    if generation_task == "acf_field_generation" and shared_fields:
                        context_payload["shared_fields_generated_this_run"] = shared_values
                        context_payload["acf_generation_batch"] = batch_name
                    if revision_instruction:
                        context_payload["draft_revision"] = {
                            "instruction": revision_instruction,
                            "selected_shared_field_keys": sorted(selected_shared_keys),
                            "selected_acf_field_keys": sorted(selected_acf_keys),
                            "unchecked_fields_must_not_change": True,
                        }
                    model = build_generation_model(
                        rows,
                        name=model_name,
                        enum_families=enum_families,
                    )
                    request_task = (
                        f"{generation_task}:{batch_name}"
                        if generation_task == "acf_field_generation"
                        else generation_task
                    )
                    generated = self._structured(
                        task=request_task,
                        messages=structured_task_input(
                            task=request_task,
                            instructions=context.instructions,
                            context=context_payload,
                        ),
                        schema=model,
                        provider=provider,
                    )
                    return generation_task, batch_name, generated.model_dump(exclude_none=True), provider

                for generation_task, model_name, batch_name, rows in generation_groups:
                    if not rows:
                        continue
                    if generation_task == "acf_field_generation" and self._can_parallelize_provider(generation_provider):
                        break
                    field_keys = [row.field_key for row in rows]
                    context = self.context_builder.build(
                        snapshot=snapshot,
                        task="generation",
                        post_type_key=session.post_type_key,
                        session=session,
                        field_keys=field_keys,
                    )
                    generation_trace.update(
                        self._generation_trace_from_context(
                            context,
                            field_keys=field_keys,
                            generation_task=generation_task,
                        )
                    )
                    self._milestone(session, f"{generation_task} batch={batch_name} started")
                    generation_task, batch_name, generated_values, provider_used = run_generation_group(
                        generation_task,
                        model_name,
                        batch_name,
                        rows,
                        generation_provider,
                        shared_fields,
                    )
                    if generation_task == "content_generation":
                        shared_fields = {
                            **shared_fields,
                            **{key: value for key, value in generated_values.items() if key in shared_row_keys},
                        }
                        acf_source_fields = {
                            **acf_source_fields,
                            **{key: value for key, value in generated_values.items() if key not in shared_row_keys},
                        }
                    elif generation_task == "shared_field_generation":
                        shared_fields = {**shared_fields, **generated_values}
                    else:
                        acf_source_fields = {**acf_source_fields, **generated_values}
                    session = self._record_provider_usage(session, provider_used)
                    self._milestone(session, f"{generation_task} batch={batch_name} finished")
                else:
                    generation_groups = ()

                parallel_acf_groups = [
                    group for group in generation_groups
                    if group[0] == "acf_field_generation" and group[3]
                ]
                if parallel_acf_groups and self._can_parallelize_provider(generation_provider):
                    max_workers = max(1, min(len(parallel_acf_groups), int(os.getenv("V2_ACF_GENERATION_WORKERS", "6"))))
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {}
                        for generation_task, model_name, batch_name, rows in parallel_acf_groups:
                            field_keys = [row.field_key for row in rows]
                            context = self.context_builder.build(
                                snapshot=snapshot,
                                task="generation",
                                post_type_key=session.post_type_key,
                                session=session,
                                field_keys=field_keys,
                            )
                            generation_trace.update(
                                self._generation_trace_from_context(
                                    context,
                                    field_keys=field_keys,
                                    generation_task=generation_task,
                                )
                            )
                            self._milestone(session, f"{generation_task} batch={batch_name} started")
                            provider = self._clone_language_provider(generation_provider)
                            future = executor.submit(
                                run_generation_group,
                                generation_task,
                                model_name,
                                batch_name,
                                rows,
                                provider,
                                shared_fields,
                            )
                            futures[future] = batch_name
                        for future in as_completed(futures):
                            generation_task, batch_name, generated_values, provider_used = future.result()
                            acf_source_fields = {**acf_source_fields, **generated_values}
                            session = self._record_provider_usage(session, provider_used)
                            self._milestone(session, f"{generation_task} batch={batch_name} finished")
        routed_shared = dict(shared_fields)
        routed_acf = dict(acf_source_fields)
        plain_acf_source_fields = dict(routed_acf)
        try:
            linkable_fields = self._linkable_acf_fields(snapshot, session)
            if selected_links and linkable_fields:
                minimum_words_between_links = self._minimum_words_between_internal_links(snapshot)
                deterministic_result = self.internal_links.inject_existing_anchors(
                    eligible,
                    selected_links,
                    acf_source_fields=routed_acf,
                    linkable_fields=linkable_fields,
                    minimum_words_between_links=minimum_words_between_links,
                )
                eligible_records = {row.link_id: row for row in eligible.candidates}
                deterministic_content = "\n".join(
                    str(value)
                    for value in deterministic_result.acf_source_fields.values()
                    if isinstance(value, str)
                )
                remaining_selections = [
                    selection
                    for selection in selected_links
                    if str(selection.get("link_id") or "") in eligible_records
                    and eligible_records[str(selection.get("link_id"))].target_url not in deterministic_content
                ]
                skipped = [
                    {
                        "link_id": str(selection.get("link_id") or ""),
                        "field_key": str(selection.get("destination_acf") or ""),
                        "reason": (
                            "approved_anchor_not_found_for_requested_link"
                            if str(selection.get("link_id") or "") in explicitly_requested_link_ids
                            else "approved_anchor_not_found"
                        ),
                    }
                    for selection in remaining_selections
                ]
                injected_links = InternalLinkInjectionResult(
                    shared_fields={},
                    acf_source_fields=deterministic_result.acf_source_fields,
                    injected=deterministic_result.injected,
                    skipped=[*deterministic_result.skipped, *skipped],
                )
            else:
                injected_links = InternalLinkInjectionResult(
                    shared_fields={},
                    acf_source_fields=routed_acf,
                    injected=[],
                    skipped=[
                        {
                            "link_id": str(selection.get("link_id") or ""),
                            "field_key": str(selection.get("destination_acf") or ""),
                            "reason": "no_workbook_linkable_fields",
                        }
                        for selection in selected_links
                    ],
                )
        except ValueError as exc:
            raise InvalidInternalLinksError(str(exc)) from exc
        routed_shared = injected_links.shared_fields or routed_shared
        routed_acf = injected_links.acf_source_fields
        eligible_records = {row.link_id: row for row in eligible.candidates}
        fulfilled_requested_link_ids = {
            link_id
            for link_id in explicitly_requested_link_ids
            if link_id in eligible_records
            and eligible_records[link_id].target_url in "\n".join(
                str(value) for value in routed_acf.values() if isinstance(value, str)
            )
        }
        unfulfilled_link_ids = explicitly_requested_link_ids - fulfilled_requested_link_ids
        if unfulfilled_link_ids:
            reasons = {
                str(item.get("link_id") or ""): str(item.get("reason") or "placement_not_returned")
                for item in injected_links.skipped
                if item.get("link_id") in unfulfilled_link_ids
            }
            details = ", ".join(
                f"{link_id} ({reasons.get(link_id, 'placement_not_returned')})"
                for link_id in sorted(unfulfilled_link_ids)
            )
            raise InvalidInternalLinksError(
                f"Could not place every requested internal link: {details}."
            )
        if targeted_revision:
            injected_acf_keys = {
                str(item.get("field_key") or "") for item in injected_links.injected
            }
            routed_shared = {
                **session.shared_fields,
                **{key: value for key, value in routed_shared.items() if key in selected_shared_keys},
            }
            routed_acf = {
                **session.acf_source_fields,
                **{
                    key: value
                    for key, value in routed_acf.items()
                    if key in selected_acf_keys or key in injected_acf_keys
                },
            }
        session = self._process_missing_images(snapshot, session)
        processed_images = list(session.processed_images)
        post_type = snapshot.post_type(session.post_type_key)
        if post_type is None:
            raise UnknownPostTypeError(session.post_type_key)
        routed_shared.setdefault("status", post_type.default_status)
        routed_shared.setdefault("category", post_type.wp_category_name)
        validation_report = self.draft_validator.validate(
            snapshot,
            post_type_key=session.post_type_key,
            shared_values=routed_shared,
            acf_source_values=routed_acf,
            no_eligible_links=not eligible.candidates,
            session=session,
        )
        image_metadata = list(session.image_metadata)
        payload = self.payload_builder.build(
            snapshot,
            post_type_key=session.post_type_key,
            shared_values=routed_shared,
            acf_source_values=routed_acf,
            confirmed_facts=session.confirmed_facts,
            media=self._publication_media(snapshot, session, images=image_metadata),
        )
        session = session.model_copy(
            update={
                "shared_fields": routed_shared,
                "acf_source_fields": routed_acf,
                "selected_links": [
                    {key: value for key, value in selection.items() if key != "revision_requested"}
                    for selection in selected_links
                ],
                "eligible_link_ids": [row.link_id for row in eligible.candidates],
                "wordpress_payload": payload.model_dump(),
                "processed_images": processed_images,
                "image_metadata": image_metadata,
                "validation_report": validation_report,
                "generation_trace": {
                    **generation_trace,
                    "internal_links": {
                        "plain_acf_source_fields": plain_acf_source_fields,
                        "linked_fields": injected_links.injected,
                        "skipped_placements": injected_links.skipped,
                    },
                },
            }
        )
        if session.state in {"ready_to_publish", "published"}:
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

    def generate_image_metadata(
        self,
        session_id: str,
        *,
        expected_version: int,
    ) -> ContentSession:
        """Generate image and video metadata after the readable draft is available."""

        session = self.repository.get(session_id)
        if session.version != expected_version:
            raise ValueError(
                f"Session version conflict: expected {expected_version}, found {session.version}."
            )
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        vision_media_ids = {
            reference.media_id
            for reference in session.image_refs
            if session.image_metadata_vision.get(reference.media_id) is True
        }
        if vision_media_ids:
            self._milestone(session, "background image Vision analysis started")
            session = self._analyze_missing_images(
                snapshot,
                session,
                media_ids=vision_media_ids,
            )
            self._milestone(session, "background image Vision analysis finished")
        if session.image_refs:
            self._milestone(session, "background image metadata generation started")
            session = self._generate_missing_image_metadata(
                snapshot,
                session,
                overwrite_existing=True,
                metadata_vision_media_ids=vision_media_ids,
            )
            self._milestone(session, "background image metadata generation finished")
        if session.video_refs:
            self._milestone(session, "background video metadata generation started")
            session = self._generate_missing_video_metadata(
                snapshot,
                session,
                overwrite_existing=True,
            )
            self._milestone(session, "background video metadata generation finished")
        latest = self.repository.get(session_id)
        payload = self.payload_builder.build(
            snapshot,
            post_type_key=latest.post_type_key,
            shared_values=latest.shared_fields,
            acf_source_values=latest.acf_source_fields,
            confirmed_facts=latest.confirmed_facts,
            media=self._publication_media(snapshot, session),
        )
        merged_trace = {
            **latest.generation_trace,
            "image_metadata": session.generation_trace.get("image_metadata", {}),
            "video_metadata": session.generation_trace.get("video_metadata", {}),
        }
        merged = latest.model_copy(
            update={
                "image_analysis": session.image_analysis,
                "image_metadata": session.image_metadata,
                "video_metadata": session.video_metadata,
                "ai_usage": session.ai_usage,
                "generation_trace": merged_trace,
                "wordpress_payload": payload.model_dump(),
            }
        )
        return self.repository.save(
            merged,
            expected_version=latest.version,
        )

    def _generate_missing_video_metadata(
        self,
        snapshot: Any,
        session: ContentSession,
        *,
        overwrite_existing: bool = False,
    ) -> ContentSession:
        if not session.video_refs:
            return session
        processed_by_media = {
            str(item.get("media_id")): item for item in session.processed_videos
        }
        existing_as_image_metadata = [
            {
                "media_id": item.get("media_id"),
                "image_title": item.get("video_title"),
                "image_caption": item.get("video_caption"),
                "image_description": item.get("video_description"),
            }
            for item in session.video_metadata
        ]
        poster_images = [
            {
                "media_id": reference.media_id,
                "filename": processed_by_media.get(reference.media_id, {}).get(
                    "poster_filename", reference.filename
                ),
                "path": processed_by_media.get(reference.media_id, {}).get(
                    "poster_path", reference.storage_uri
                ),
            }
            for reference in session.video_refs
        ]
        as_images = session.model_copy(update={
            "image_refs": session.video_refs,
            "processed_images": poster_images,
            "image_metadata": existing_as_image_metadata,
            "image_context_transcripts": session.video_context_transcripts,
            "image_analysis": {},
            "image_metadata_vision": {},
        })
        generated = self._generate_missing_image_metadata(
            snapshot,
            as_images,
            overwrite_existing=overwrite_existing,
            metadata_vision_media_ids=set(),
        )
        generated_by_media = {
            str(item.get("media_id")): item for item in generated.image_metadata
        }
        video_ids = {reference.media_id for reference in session.video_refs}
        video_metadata = [
            item for item in session.video_metadata
            if item.get("media_id") not in video_ids
        ]
        video_metadata.extend(
            {
                "media_id": reference.media_id,
                "video_title": generated_by_media.get(reference.media_id, {}).get("image_title", ""),
                "video_caption": generated_by_media.get(reference.media_id, {}).get("image_caption", ""),
                "video_description": generated_by_media.get(reference.media_id, {}).get(
                    "image_description",
                    generated_by_media.get(reference.media_id, {}).get("image_description_wp", ""),
                ),
            }
            for reference in session.video_refs
            if reference.media_id in generated_by_media
        )
        generated_trace = generated.generation_trace.get("image_metadata", {})
        return session.model_copy(update={
            "video_metadata": video_metadata,
            "ai_usage": generated.ai_usage,
            "generation_trace": {
                **session.generation_trace,
                "video_metadata": {
                    media_id: {**trace, "video_analysis_used": False}
                    for media_id, trace in generated_trace.items()
                    if media_id in video_ids
                },
            },
        })

    def _session_language_provider(self, session: ContentSession) -> LanguageModelProvider | None:
        provider = self.language_model
        if (
            provider is not None
            and session.language_model
            and session.reasoning_effort
            and hasattr(provider, "with_settings")
        ):
            return provider.with_settings(
                model=session.language_model,
                reasoning_effort=session.reasoning_effort,
            )
        return provider

    @staticmethod
    def _can_parallelize_provider(provider: LanguageModelProvider | None) -> bool:
        return (
            provider is not None
            and hasattr(provider, "with_settings")
            and hasattr(provider, "model")
            and hasattr(provider, "reasoning_effort")
        )

    @staticmethod
    def _clone_language_provider(provider: LanguageModelProvider) -> LanguageModelProvider:
        if not ContentSessionService._can_parallelize_provider(provider):
            return provider
        return provider.with_settings(
            model=getattr(provider, "model"),
            reasoning_effort=getattr(provider, "reasoning_effort"),
        )

    @staticmethod
    def _acf_generation_batches(rows: list[Any]) -> list[tuple[str, list[Any]]]:
        batches: dict[str, list[Any]] = {}
        for row in rows:
            batch_name = str(row.section or row.group or "content").strip().lower()
            batches.setdefault(batch_name, []).append(row)
        return list(batches.items())

    @staticmethod
    def _derive_acf_fields_from_facts(
        snapshot: Any,
        session: ContentSession,
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in snapshot.acf_fields:
            if (
                not row.enabled
                or row.post_type_key != session.post_type_key
                or row.field_role == "input_fact"
                or row.source_mode != "derived_from_facts"
                or not row.source_fact_keys
                or not ContentSessionService._acf_field_is_eligible(row, session)
            ):
                continue
            parts = [
                str(session.confirmed_facts[key].value).strip()
                for key in row.source_fact_keys
                if fact_is_usable(session, key)
            ]
            if parts:
                values[row.field_key] = ", ".join(parts)
        return values

    def _structured(
        self,
        *,
        task: str,
        messages: list[dict[str, str]],
        schema: type[Any],
        provider: LanguageModelProvider | None = None,
    ) -> Any:
        provider = provider or self.language_model
        if provider is None:
            raise RuntimeError("A LanguageModelProvider is not configured.")
        current_messages = list(messages)
        validation_errors: list[str] = []
        max_attempts = max(1, int(os.getenv("V2_MODEL_PROVIDER_MAX_ATTEMPTS", "3")))
        max_retry_wait_budget_seconds = max(
            0,
            int(os.getenv("V2_MODEL_PROVIDER_MAX_RETRY_WAIT_BUDGET_SECONDS", "45")),
        )
        waited_seconds = 0
        for attempt in range(1, max_attempts + 1):
            started_at = perf_counter()
            try:
                result = provider.structured(
                    task=task,
                    context={"messages": current_messages},
                    schema=schema,
                )
                print(
                    f"[model timing] task={task} attempt={attempt} "
                    f"seconds={perf_counter() - started_at:.2f} "
                    f"input_chars={sum(len(message.get('content', '')) for message in current_messages)}",
                    flush=True,
                )
                return result
            except (ValidationError, ValueError) as validation_error:
                feedback = self._validation_feedback(validation_error)
                validation_errors.append(feedback)
                print(
                    f"[model retry] task={task} attempt={attempt} "
                    f"seconds={perf_counter() - started_at:.2f} validation={feedback}",
                    flush=True,
                )
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
                if self._is_transient_provider_error(provider_error) and attempt < max_attempts:
                    wait_seconds = self._provider_retry_delay_seconds(provider_error, attempt)
                    remaining_wait_budget = max_retry_wait_budget_seconds - waited_seconds
                    if remaining_wait_budget <= 0:
                        raise ModelProviderError(
                            f"Model provider retry budget exhausted for {task} after "
                            f"{attempt} attempts: {provider_error}"
                        ) from provider_error
                    wait_seconds = min(wait_seconds, remaining_wait_budget)
                    print(
                        f"[model retry] task={task} attempt={attempt} "
                        f"seconds={perf_counter() - started_at:.2f} "
                        f"provider_error={provider_error} wait_seconds={wait_seconds}",
                        flush=True,
                    )
                    sleep(wait_seconds)
                    waited_seconds += wait_seconds
                    continue
                raise ModelProviderError(
                    f"Model provider failed for {task} on attempt {attempt}: "
                    f"{provider_error}"
                ) from provider_error
        raise ModelOutputValidationError(
            f"Structured output failed validation for {task}: {validation_errors}"
        )

    @staticmethod
    def _is_transient_provider_error(error: Exception) -> bool:
        message = str(error).lower()
        return (
            "temporarily unavailable" in message
            or "http 5" in message
            or "rate limit" in message
            or "timed out" in message
            or "connection" in message
        )

    @staticmethod
    def _provider_retry_delay_seconds(error: Exception, attempt: int) -> int:
        max_wait_seconds = max(1, int(os.getenv("V2_MODEL_PROVIDER_MAX_WAIT_SECONDS", "20")))
        # Respect explicit wait hints from provider messages when available.
        message = str(error)
        match = re.search(r"wait at least\s+(\d+)\s+seconds", message, re.IGNORECASE)
        if match:
            hinted = int(match.group(1))
            return max(1, min(hinted, max_wait_seconds))
        return min(max_wait_seconds, 4 * (2 ** (attempt - 1)))

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
        usage["calls"] = [*(usage.get("calls") or []), usage["last_call"]][-500:]
        usage["updated_at"] = usage["last_call"]["updated_at"]
        return session.model_copy(update={"ai_usage": usage})

    def _analyze_missing_images(
        self,
        snapshot: Any,
        session: ContentSession,
        *,
        media_ids: set[str] | None = None,
    ) -> ContentSession:
        if self.vision is None or self.object_storage is None or not session.image_refs:
            return session
        image_analysis = dict(session.image_analysis)
        missing_refs = [
            reference
            for reference in session.image_refs
            if reference.media_id not in image_analysis
            and (media_ids is None or reference.media_id in media_ids)
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
        def analyze_reference(reference: Any) -> tuple[str, Any, dict[str, Any] | None]:
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
                usage = getattr(self.vision, "last_usage", None)
                return reference.media_id, parsed, dict(usage) if isinstance(usage, dict) else None

        max_workers = max(1, min(int(os.getenv("V2_VISION_CONCURRENCY", "3")), len(missing_refs)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(analyze_reference, reference) for reference in missing_refs]
            for future in as_completed(futures):
                media_id, parsed, usage = future.result()
                if usage is not None:
                    self.vision.last_usage = usage
                session = self._record_provider_usage(session, self.vision)
                image_analysis[media_id] = parsed.model_dump()
        return session.model_copy(update={"image_analysis": image_analysis})

    def _process_missing_images(
        self,
        snapshot: Any,
        session: ContentSession,
        *,
        media_ids: set[str] | None = None,
        aspect_ratio: str | None = None,
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
            and (media_ids is None or reference.media_id in media_ids)
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
                        aspect_ratio=aspect_ratio,
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
        metadata_vision_media_ids: set[str] | None = None,
    ) -> ContentSession:
        if self.language_model is None or not session.image_refs:
            return session
        previous_metadata_by_media = {
            str(item.get("media_id")): dict(item)
            for item in session.image_metadata
            if item.get("media_id")
        }
        image_metadata = [] if overwrite_existing else list(session.image_metadata)
        generation_trace = dict(session.generation_trace)
        image_metadata_trace = dict(generation_trace.get("image_metadata") or {})
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
        taxonomy_terms: dict[str, list[str]] = {}
        media_taxonomies: list[str] = []
        if hasattr(snapshot, "post_type") and hasattr(snapshot, "taxonomies"):
            taxonomy_terms, media_taxonomies = self.payload_builder.taxonomy_terms(
                snapshot,
                post_type_key=session.post_type_key,
                shared_values=session.shared_fields,
                acf_source_values=session.acf_source_fields,
                confirmed_facts=session.confirmed_facts,
            )
        taxonomy_candidates = {
            taxonomy: tuple(terms)
            for taxonomy, terms in taxonomy_terms.items()
            if taxonomy in media_taxonomies and terms
        }
        if taxonomy_candidates and self.wordpress is not None:
            registered_candidates = self.wordpress.registered_taxonomy_candidates(
                {
                    taxonomy: list(terms)
                    for taxonomy, terms in taxonomy_candidates.items()
                }
            )
            taxonomy_candidates = {
                taxonomy: tuple(terms)
                for taxonomy, terms in registered_candidates.items()
                if terms
            }
        metadata_model = build_image_metadata_batch_model(
            metadata_rows,
            media_ids=tuple(reference.media_id for reference in missing_metadata_refs),
            taxonomy_candidates=taxonomy_candidates,
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
        metadata_vision_media_ids = (
            metadata_vision_media_ids
            if metadata_vision_media_ids is not None
            else {
                media_id
                for media_id, enabled in session.image_metadata_vision.items()
                if enabled
            }
        )
        metadata_contexts = {
            reference.media_id: {
                "media_id": reference.media_id,
                **self._image_metadata_context(
                    snapshot,
                    session,
                    reference.media_id,
                    metadata_rows,
                    use_vision=reference.media_id in metadata_vision_media_ids,
                ),
            }
            for reference in missing_metadata_refs
        }
        generated_batch = self._structured(
            task="image_metadata_batch",
            messages=structured_task_input(
                task="image_metadata_batch",
                instructions=image_instructions,
                context={
                    "images": list(metadata_contexts.values()),
                    "taxonomy_candidates": taxonomy_candidates,
                    "output_contract": (
                        "Return exactly one images item for every supplied media_id. "
                        "Do not copy visual details from one image to another. "
                        "For visible_taxonomy_terms, use only exact supplied taxonomy "
                        "candidate values that are visibly supported by that image; "
                        "return an empty list for every taxonomy without a visible match. "
                        "Write human-readable German metadata with correct Unicode spelling "
                        "(including ä, ö, ü, Ä, Ö, Ü, and ß); only technical filename or slug "
                        "fields may use ASCII transliteration."
                    ),
                },
            ),
            schema=metadata_model,
            provider=self.metadata_language_model,
        )
        session = self._record_provider_usage(session, self.metadata_language_model)
        generated_by_media = {
            item.media_id: item.model_dump(exclude_none=True, exclude={"media_id"})
            for item in generated_batch.images
        }
        for index, reference in enumerate(session.image_refs, 1):
            if reference.media_id not in generated_by_media:
                continue
            existing = previous_metadata_by_media.get(reference.media_id, {}) or {}
            image_metadata = [
                row for row in image_metadata if row.get("media_id") != reference.media_id
            ]
            generated = generated_by_media[reference.media_id]
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
            image_metadata_trace[reference.media_id] = {
                "fields": metadata_contexts[reference.media_id]["fields"],
                "instructions": image_instructions,
                "vision_used": reference.media_id in metadata_vision_media_ids,
                "taxonomy_candidates": taxonomy_candidates,
                "visible_taxonomy_terms": generated.get(
                    "visible_taxonomy_terms",
                    {},
                ),
            }
            metadata_media_ids.add(reference.media_id)
        generation_trace["image_metadata"] = image_metadata_trace
        return session.model_copy(
            update={
                "image_metadata": sorted(
                    image_metadata,
                    key=lambda row: (
                        0 if row.get("image_usage") == "featured" else 1,
                        int(row.get("image_priority") or 999),
                    ),
                ),
                "generation_trace": generation_trace,
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
        *,
        use_vision: bool = False,
    ) -> dict[str, Any]:
        image_analysis = session.image_analysis.get(media_id, {}) if use_vision else {}
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
        transcript_match_rules = [
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
            for rule in snapshot.image_metadata_rules
            if not image_analysis
            and rule.enabled
            and rule.post_type_key in {"*", session.post_type_key}
            and rule.workflow_stage in {"all", "image_metadata"}
            and rule.trigger_type == "image_analysis_contains"
            and rule.usage_mode != "exclude"
        ]
        approved_context_facts = {
            row.field_key: session.confirmed_facts[row.field_key].model_dump()
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == session.post_type_key
            and row.include_in_image_metadata_context is True
            and row.field_key in session.confirmed_facts
            and session.confirmed_facts[row.field_key].confirmed
            and session.confirmed_facts[row.field_key].value not in (None, "", [])
        }
        return {
            "image_context_transcript": session.image_context_transcripts.get(media_id, ""),
            "image_analysis": image_analysis,
            "approved_context_facts": approved_context_facts,
            "must_use_when_natural": must_use_when_natural,
            "transcript_match_rules": transcript_match_rules,
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
            for reusable_guidance in field.prompt_guidance:
                text = str(reusable_guidance.get("instruction_de") or "").strip()
                if text:
                    rules.append({
                        "source": "prompt_guidance",
                        "scope": "field",
                        "shared": False,
                        "rule_id": reusable_guidance.get("guidance_key"),
                        "text": text,
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
    def _minimum_words_between_internal_links(snapshot: Any) -> int:
        for row in snapshot.internal_link_rules:
            if (
                row.enabled
                and row.applies_to == "internal_links"
                and row.operator == "min"
                and row.value_type == "integer"
            ):
                return max(0, int(row.value or 0))
        return 0

    @classmethod
    def _linkable_acf_fields(cls, snapshot: Any, session: ContentSession) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for row in snapshot.acf_fields:
            if (
                row.enabled
                and row.post_type_key == session.post_type_key
                and getattr(row, "allow_internal_links", False)
                and cls._acf_field_is_eligible(row, session)
            ):
                fields[row.field_key] = row
        priority = {"high": 0, "medium": 1, "low": 2}
        return dict(
            sorted(
                fields.items(),
                key=lambda item: (
                    priority.get(str(getattr(item[1], "internal_link_priority", "") or "").lower(), 9),
                    item[0],
                ),
            )
        )

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

        def add(link_id: str, anchor_text: str, destination_acf: str = "") -> None:
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
            selection = {"link_id": record.link_id, "anchor_text": anchor}
            if destination_acf:
                selection["destination_acf"] = destination_acf
            completed.append(selection)

        for selection in selected_links:
            add(
                str(selection.get("link_id") or ""),
                str(selection.get("anchor_text") or ""),
                str(selection.get("destination_acf") or ""),
            )
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
        # Manual edits are a field-scoped merge. Operation logs and background
        # metadata may legitimately advance the whole-session version.
        del expected_version
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
            confirmed_facts=session.confirmed_facts,
            media=self._publication_media(snapshot, session),
        )
        generation_trace = dict(session.generation_trace)
        generation_trace.pop("humanness_review", None)
        updated = session.model_copy(
            update={
                "shared_fields": updated_shared,
                "acf_source_fields": updated_acf,
                "wordpress_payload": payload.model_dump(),
                "generation_trace": generation_trace,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._milestone(updated, "manual draft fields saved")
        return self.repository.save(updated, expected_version=session.version)

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
            overwrite_existing=False,
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
        if shared_fields or acf_source_fields or refined.image_refs or refined.video_refs:
            publication_media = [
                *refined.image_metadata,
                *self._video_publication_media(snapshot, refined),
            ]
            payload = self.payload_builder.build(
                snapshot,
                post_type_key=refined.post_type_key,
                shared_values=refined.shared_fields,
                acf_source_values=refined.acf_source_fields,
                confirmed_facts=refined.confirmed_facts,
                media=publication_media,
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
                # Keep the canonical payload. Materialized local paths are an
                # upload implementation detail, not a content change.
                "published_wordpress_payload": publishing.wordpress_payload,
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
        if dict(current.get("taxonomies") or {}) != dict(previous.get("taxonomies") or {}):
            fields["wordpress"].add("taxonomies")
        def comparable_media(payload: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {key: value for key, value in dict(item).items() if key != "output"}
                for item in list(payload.get("media") or [])
            ]

        if comparable_media(current) != comparable_media(previous):
            fields["wordpress"].add("media")
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
    def _publication_media(
        snapshot: Any,
        session: ContentSession,
        *,
        images: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        processed_by_media = {
            str(item.get("media_id")): item
            for item in session.processed_images
            if item.get("media_id")
        }
        analysis_by_media = {
            str(media_id): analysis
            for media_id, analysis in session.image_analysis.items()
        }
        image_rows = []
        for image in session.image_metadata if images is None else images:
            row = dict(image)
            media_id = str(row.get("media_id") or "")
            processed = processed_by_media.get(str(row.get("media_id") or ""))
            if processed:
                row["binary_revision"] = ContentSessionService._media_binary_revision(processed)
            if media_id in analysis_by_media:
                row["image_analysis"] = analysis_by_media[media_id]
            image_rows.append(row)
        return [
            *image_rows,
            *ContentSessionService._video_publication_media(snapshot, session),
        ]

    @staticmethod
    def _media_binary_revision(processed: dict[str, Any]) -> str:
        payload = {
            key: processed.get(key)
            for key in (
                "path",
                "filename",
                "size_bytes",
                "width",
                "height",
                "format",
                "operations",
                "quality",
                "updated_at",
            )
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]

    @staticmethod
    def _video_publication_media(snapshot: Any, session: ContentSession) -> list[dict[str, Any]]:
        """Map the first remaining video to the shared WordPress video ACFs."""
        if not session.video_refs:
            return []
        destinations = {
            row.acf_field_name
            for row in snapshot.acf_fields
            if row.enabled
            and row.include_in_payload
            and row.post_type_key == session.post_type_key
            and row.field_role == "direct_acf"
            and row.acf_field_name in {"video_url", "video_poster"}
        }
        video_field = "video_url" if "video_url" in destinations else None
        poster_field = "video_poster" if "video_poster" in destinations else None
        if not video_field and not poster_field:
            return []
        reference = session.video_refs[0]
        processed = next(
            (
                item for item in session.processed_videos
                if item.get("media_id") == reference.media_id
            ),
            {},
        )
        metadata = next(
            (
                item for item in session.video_metadata
                if item.get("media_id") == reference.media_id
            ),
            {},
        )
        common = {
            "source_video_media_id": reference.media_id,
            "binary_revision": ContentSessionService._media_binary_revision(processed),
            "video_title": metadata.get("video_title"),
            "video_caption": metadata.get("video_caption"),
            "video_description": metadata.get("video_description"),
        }
        media: list[dict[str, Any]] = []
        if video_field:
            media.append({
                **common,
                "media_kind": "video",
                "path": processed.get("path") or reference.storage_uri,
                "acf_field_name": video_field,
            })
        if poster_field and processed.get("poster_path"):
            media.append({
                **common,
                "media_kind": "video_poster",
                "path": processed["poster_path"],
                "acf_field_name": poster_field,
            })
        return media

    @staticmethod
    def _filename_from_uri(uri: str) -> str:
        value = str(uri or "").rstrip("/")
        if not value:
            return ""
        return value.rsplit("/", 1)[-1]
