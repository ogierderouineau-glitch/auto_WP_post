from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from PIL import Image

from app.v2.images.step_02_processor import PillowProcessor
from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.providers.step_01_interfaces import (
    LanguageModelProvider,
    SpeechToTextProvider,
    VisionProvider,
    WordPressProvider,
)
from app.v2.models.step_01_session import ContentSession
from app.v2.models.step_02_payload import WordPressPayload
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.sessions.step_03_service import ContentSessionService
from app.v2.storage.step_01_local import LocalObjectStorageProvider
from pydantic import BaseModel, ConfigDict

WORKBOOK = Path(
    os.getenv(
        "V2_TEST_WORKBOOK",
        "/home/ogier-derouineau/Downloads/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm",
    )
)


class WorkbookFakeLanguageModel(LanguageModelProvider):
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []
        self.contexts: list[dict[str, Any]] = []

    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any:
        self.calls.append(task)
        user_context = json.loads(context["messages"][1]["content"])["context"]
        self.contexts.append({"task": task, "context": user_context})
        self.last_usage = {
            "service": "openai_text",
            "call_name": task,
            "model": "fake-text",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "estimated_cost_usd": None,
        }
        if task == "fact_extraction":
            rows = [
                row for row in self.snapshot.acf_fields
                if row.enabled
                and row.post_type_key == "event"
                and row.field_role == "input_fact"
            ]
            data = {
                row.field_key: (
                    self._value(row.value_type, row.min_words, row.max_words)
                    if row.required_for_analysis
                    else None
                )
                for row in rows
            }
        elif task == "shared_field_generation":
            rows = [
                row for row in self.snapshot.shared_fields
                if row.enabled and row.include_in_ai_schema
            ]
            data = {
                row.field_key: (
                    self._value(
                        row.value_type,
                        row.min_words,
                        row.max_words,
                        row.max_characters,
                    )
                    if row.required_for_output
                    else None
                )
                for row in rows
            }
        elif task == "acf_field_generation":
            allowed_fields = set(schema.model_fields)
            rows = [
                row for row in self.snapshot.acf_fields
                if row.enabled
                and row.post_type_key == "event"
                and row.field_role != "input_fact"
                and row.include_in_ai_schema
                and row.field_key in allowed_fields
            ]
            data = {
                row.field_key: (
                    self._value(row.value_type, row.min_words, row.max_words)
                    if row.required_for_output
                    else None
                )
                for row in rows
            }
        elif task == "internal_link_ranking":
            user = json.loads(context["messages"][1]["content"])
            candidates = user["context"]["candidates"]
            data = {
                "selections": [
                    {
                        "link_id": row["link_id"],
                        "anchor_text": row["anchor_text"],
                    }
                    for row in candidates[:2]
                ]
            }
        elif task == "image_metadata":
            data = {
                "image_alt": "FLAIRLAB Event in Berlin",
                "image_title": "FLAIRLAB Event Berlin",
                "image_caption": "FLAIRLAB beim Event in Berlin.",
                "image_description_wp": "Das Bild zeigt den bestätigten Eventkontext von FLAIRLAB in Berlin.",
                "image_filename": "flairlab-event-berlin-01.webp",
            }
        else:
            raise AssertionError(f"Unexpected fake model task: {task}")
        return schema.model_validate(data)

    @staticmethod
    def _value(
        value_type: str,
        minimum_words: int | None,
        maximum_words: int | None,
        maximum_characters: int | None = None,
    ) -> Any:
        if value_type == "integer":
            return 2026
        if value_type == "float":
            return 1.0
        if value_type == "boolean":
            return True
        if value_type == "list":
            return ["Berlin"]
        if value_type == "date":
            return "2026-06-24"
        if value_type == "enum":
            return "company"
        words = max(minimum_words or 1, 1)
        text = " ".join(["Wort"] * words)
        if maximum_characters is not None:
            text = text[:maximum_characters].rstrip()
        return text


class WorkbookFakeVision(VisionProvider):
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def analyze(
        self,
        image_path: Path,
        schema: type[Any],
        context: dict[str, Any],
    ) -> Any:
        self.calls += 1
        self.last_usage = {
            "service": "openai_vision",
            "call_name": "image_analysis",
            "model": "fake-vision",
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
            "estimated_cost_usd": None,
        }
        data: dict[str, Any] = {}
        for row in self.snapshot.image_analysis_rules:
            if not row.enabled:
                continue
            if row.output_domain:
                data[row.analysis_key] = next(iter(self.snapshot.validation_family(row.output_domain)))
            elif row.expected_output == "short_text":
                data[row.analysis_key] = "Mobile Bar bei einem Event"
            elif row.expected_output == "integer_0_100":
                data[row.analysis_key] = 70
            elif row.expected_output == "normalized_focal_point_or_none":
                data[row.analysis_key] = {"x": 0.5, "y": 0.5}
            elif row.expected_output == "float_or_zero":
                data[row.analysis_key] = 0.0
            elif row.expected_output in {"short_text_or_none", "group_id_or_none"}:
                data[row.analysis_key] = None
            elif row.expected_output == "boolean_with_reason":
                data[row.analysis_key] = {"value": False, "reason": "Pillow genügt."}
        return schema.model_validate(data)


class CaptureWordPressProvider(WordPressProvider):
    def __init__(self) -> None:
        self.payloads: list[WordPressPayload] = []

    def publish(
        self,
        *,
        session: ContentSession,
        payload: WordPressPayload,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        return {
            "post_id": 456,
            "status": payload.wordpress.status,
            "view_url": "https://staging.example/published",
            "edit_url": "https://staging.example/wp-admin/post.php?post=456&action=edit",
            "idempotency_key": idempotency_key,
        }


class FakeSpeechToText(SpeechToTextProvider):
    def transcribe(self, audio_path: Path) -> str:
        return "Bestätigtes Firmenevent in Berlin mit Cocktailcatering."


class RetryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class RetryLanguageModel(LanguageModelProvider):
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages: list[dict[str, str]] = []

    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any:
        self.calls += 1
        self.last_messages = context["messages"]
        if self.calls < 3:
            return schema.model_validate({"text": None})
        return schema.model_validate({"text": "valid"})


@unittest.skipUnless(WORKBOOK.is_file(), f"V2 test workbook not found: {WORKBOOK}")
class StructuredPipelineTests(unittest.TestCase):
    def test_targeted_validation_retry_is_bounded_and_passes_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = RetryLanguageModel()
            service = ContentSessionService(
                knowledge=KnowledgeBaseService(WORKBOOK),
                repository=FileSessionRepository(temporary),
                language_model=model,
            )
            result = service._structured(
                task="retry_test",
                messages=[{"role": "user", "content": "{}"}],
                schema=RetryResponse,
            )
            self.assertEqual(result.text, "valid")
            self.assertEqual(model.calls, 3)
            self.assertIn("Validation feedback", model.last_messages[-1]["content"])

    def test_fake_model_runs_separate_structured_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            model = WorkbookFakeLanguageModel(snapshot)
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(temporary),
                language_model=model,
            )
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.add_inputs(
                session.session_id,
                manual_text="Ausdrücklich bestätigte Eventdaten.",
                confirmed_facts={
                    row.field_key: WorkbookFakeLanguageModel._value(
                        row.value_type,
                        row.min_words,
                        row.max_words,
                    )
                    for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == "event"
                    and row.field_role == "input_fact"
                    and row.required_for_analysis
                },
                expected_version=session.version,
            )
            session = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            self.assertEqual(session.state, "ready_to_generate")
            date_fact_keys = [
                row.field_key
                for row in snapshot.acf_fields
                if row.enabled
                and row.post_type_key == "event"
                and row.field_role == "input_fact"
                and row.value_type == "date"
            ]
            self.assertTrue(date_fact_keys)
            for field_key in date_fact_keys:
                self.assertEqual(session.confirmed_facts[field_key].value, "24.06.2026")
                self.assertEqual(session.extracted_facts[field_key].value, "24.06.2026")
            session = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            self.assertEqual(session.state, "needs_review")
            self.assertEqual(
                model.calls,
                [
                    "fact_extraction",
                    "shared_field_generation",
                    "acf_field_generation",
                    "internal_link_ranking",
                ],
            )
            self.assertTrue(session.wordpress_payload["meta"])
            self.assertTrue(session.wordpress_payload["acf"])
            self.assertEqual(session.ai_usage["call_count"], 4)
            self.assertEqual(session.ai_usage["total_tokens"], 60)
            self.assertEqual(session.ai_usage["services"]["openai_text"]["call_count"], 4)

    def test_generated_session_can_be_regenerated_after_review_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(temporary),
                language_model=WorkbookFakeLanguageModel(snapshot),
            )
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.add_inputs(
                session.session_id,
                manual_text="Ausdrücklich bestätigte Eventdaten.",
                confirmed_facts={
                    row.field_key: WorkbookFakeLanguageModel._value(
                        row.value_type,
                        row.min_words,
                        row.max_words,
                    )
                    for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == "event"
                    and row.field_role == "input_fact"
                    and row.required_for_analysis
                },
                expected_version=session.version,
            )
            session = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            generated = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            regenerated = service.generate(
                generated.session_id,
                shared_fields=generated.shared_fields,
                acf_source_fields=generated.acf_source_fields,
                selected_links=generated.selected_links,
                current_url=None,
                expected_version=generated.version,
            )
            self.assertEqual(regenerated.state, "needs_review")
            self.assertEqual(regenerated.version, generated.version + 1)

    def test_draft_revision_instruction_is_passed_to_structured_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            model = WorkbookFakeLanguageModel(snapshot)
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(temporary),
                language_model=model,
            )
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.add_inputs(
                session.session_id,
                manual_text="Ausdrücklich bestätigte Eventdaten.",
                confirmed_facts={
                    row.field_key: WorkbookFakeLanguageModel._value(
                        row.value_type,
                        row.min_words,
                        row.max_words,
                    )
                    for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == "event"
                    and row.field_role == "input_fact"
                    and row.required_for_analysis
                },
                expected_version=session.version,
            )
            session = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            generated = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            revised = service.generate(
                generated.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=generated.selected_links,
                current_url=None,
                revision_instruction="Bitte den Text wärmer und persönlicher machen.",
                expected_version=generated.version,
            )

            self.assertEqual(revised.state, "needs_review")
            revision_contexts = [
                item["context"]
                for item in model.contexts
                if item["task"] in {"shared_field_generation", "acf_field_generation"}
                and "draft_revision" in item["context"]
            ]
            self.assertTrue(revision_contexts)
            self.assertEqual(
                revision_contexts[-1]["draft_revision"]["instruction"],
                "Bitte den Text wärmer und persönlicher machen.",
            )
            self.assertEqual(
                revision_contexts[-1]["draft_revision"]["current_shared_fields"],
                generated.shared_fields,
            )

    def test_image_session_runs_vision_pillow_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            model = WorkbookFakeLanguageModel(snapshot)
            storage = LocalObjectStorageProvider(root / "objects")
            vision = WorkbookFakeVision(snapshot)
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(root / "sessions"),
                language_model=model,
                vision=vision,
                object_storage=storage,
                image_processor=PillowProcessor(),
            )
            image = root / "upload.png"
            Image.new("RGB", (640, 480), "navy").save(image)
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.add_inputs(
                session.session_id,
                manual_text="Ausdrücklich bestätigte Eventdaten.",
                confirmed_facts={
                    row.field_key: WorkbookFakeLanguageModel._value(
                        row.value_type,
                        row.min_words,
                        row.max_words,
                    )
                    for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == "event"
                    and row.field_role == "input_fact"
                    and row.required_for_analysis
                },
                expected_version=session.version,
            )
            session = service.attach_upload(
                session.session_id,
                source=image,
                kind="image",
                filename="event.png",
                content_type="image/png",
                expected_version=session.version,
            )
            self.assertEqual(vision.calls, 1)
            self.assertEqual(len(session.image_analysis), 1)
            self.assertEqual(len(session.processed_images), 1)
            self.assertEqual(len(session.image_metadata), 0)
            session = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            self.assertEqual(vision.calls, 1)
            session = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            self.assertEqual(session.state, "needs_review")
            self.assertEqual(vision.calls, 1)
            self.assertEqual(len(session.image_analysis), 1)
            self.assertEqual(len(session.processed_images), 1)
            self.assertEqual(len(session.image_metadata), 1)
            self.assertTrue(Path(session.image_metadata[0]["path"]).is_file())
            self.assertEqual(session.image_metadata[0]["image_usage"], "featured")
            self.assertGreaterEqual(session.ai_usage["services"]["openai_vision"]["call_count"], 1)

    def test_image_upload_can_skip_immediate_vision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            vision = WorkbookFakeVision(snapshot)
            storage = LocalObjectStorageProvider(root / "objects")
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(root / "sessions"),
                language_model=WorkbookFakeLanguageModel(snapshot),
                vision=vision,
                object_storage=storage,
                image_processor=PillowProcessor(),
            )
            image = root / "upload-no-vision.png"
            Image.new("RGB", (640, 480), "navy").save(image)
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.attach_upload(
                session.session_id,
                source=image,
                kind="image",
                filename="event-no-vision.png",
                content_type="image/png",
                expected_version=session.version,
                use_vision=False,
            )
            self.assertEqual(vision.calls, 0)
            self.assertEqual(len(session.image_analysis), 0)
            self.assertEqual(len(session.processed_images), 1)
            self.assertEqual(len(session.image_metadata), 0)
            analyzed = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            self.assertEqual(vision.calls, 0)
            self.assertEqual(len(analyzed.image_analysis), 0)

    def test_publish_refines_image_metadata_with_final_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            model = WorkbookFakeLanguageModel(snapshot)
            storage = LocalObjectStorageProvider(root / "objects")
            vision = WorkbookFakeVision(snapshot)
            wordpress = CaptureWordPressProvider()
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(root / "sessions"),
                language_model=model,
                vision=vision,
                object_storage=storage,
                image_processor=PillowProcessor(),
                wordpress=wordpress,
            )
            image = root / "bartender-show.png"
            Image.new("RGB", (900, 600), "navy").save(image)
            session = service.create(user_id="user-1", post_type_key="event")
            confirmed_facts = {
                row.field_key: WorkbookFakeLanguageModel._value(
                    row.value_type,
                    row.min_words,
                    row.max_words,
                )
                for row in snapshot.acf_fields
                if row.enabled
                and row.post_type_key == "event"
                and row.field_role == "input_fact"
                and row.required_for_analysis
            }
            confirmed_facts.update(
                {
                    "bartender": "Barkeeper Max",
                    "service_type": "Cocktailshow",
                    "additional_services": "Show-Bartending mit Flair-Einlage",
                }
            )
            session = service.add_inputs(
                session.session_id,
                manual_text="Event mit Barkeeper Max und Cocktailshow.",
                confirmed_facts=confirmed_facts,
                expected_version=session.version,
            )
            session = service.attach_upload(
                session.session_id,
                source=image,
                kind="image",
                filename="bartender-show.png",
                content_type="image/png",
                expected_version=session.version,
            )
            self.assertEqual(model.calls.count("image_metadata"), 0)

            session = service.analyze(session.session_id, expected_version=session.version)
            session = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            session = service.approve(
                session.session_id,
                user_id="user-1",
                expected_version=session.version,
            )
            published = service.publish(
                session.session_id,
                idempotency_key="publish-with-refined-media",
                expected_version=session.version,
            )

            self.assertEqual(published.state, "published")
            self.assertEqual(model.calls.count("image_metadata"), 2)
            image_contexts = [
                item["context"]
                for item in model.contexts
                if item["task"] == "image_metadata"
            ]
            final_context = image_contexts[-1]
            self.assertEqual(
                final_context["image_metadata_priority_facts"]["bartender"],
                "Barkeeper Max",
            )
            self.assertEqual(
                final_context["image_metadata_priority_facts"]["service_type"],
                "Cocktailshow",
            )
            self.assertEqual(
                final_context["image_metadata_priority_facts"]["additional_services"],
                "Show-Bartending mit Flair-Einlage",
            )
            self.assertIn("shared_fields", final_context)
            self.assertIn("acf_source_fields", final_context)
            self.assertIn("wordpress_payload", final_context)
            rules = " ".join(final_context["image_metadata_usage_rules"])
            self.assertIn("bartender", rules)
            self.assertIn("show", rules)
            self.assertEqual(len(wordpress.payloads), 1)
            self.assertEqual(len(wordpress.payloads[0].media), 1)
            self.assertEqual(
                wordpress.payloads[0].media[0]["media_id"],
                published.image_refs[0].media_id,
            )

    def test_image_added_after_draft_is_processed_on_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            storage = LocalObjectStorageProvider(root / "objects")
            vision = WorkbookFakeVision(snapshot)
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(root / "sessions"),
                language_model=WorkbookFakeLanguageModel(snapshot),
                vision=vision,
                object_storage=storage,
                image_processor=PillowProcessor(),
            )
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.add_inputs(
                session.session_id,
                manual_text="Ausdrücklich bestätigte Eventdaten.",
                confirmed_facts={
                    row.field_key: WorkbookFakeLanguageModel._value(
                        row.value_type,
                        row.min_words,
                        row.max_words,
                    )
                    for row in snapshot.acf_fields
                    if row.enabled
                    and row.post_type_key == "event"
                    and row.field_role == "input_fact"
                    and row.required_for_analysis
                },
                expected_version=session.version,
            )
            session = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            generated = service.generate(
                session.session_id,
                shared_fields={},
                acf_source_fields={},
                selected_links=[],
                current_url=None,
                expected_version=session.version,
            )
            self.assertEqual(generated.state, "needs_review")
            self.assertFalse(generated.processed_images)

            image = root / "late-upload.png"
            Image.new("RGB", (640, 480), "navy").save(image)
            with_image = service.attach_upload(
                generated.session_id,
                source=image,
                kind="image",
                filename="late-upload.png",
                content_type="image/png",
                expected_version=generated.version,
            )
            self.assertEqual(vision.calls, 1)
            self.assertEqual(len(with_image.processed_images), 1)
            self.assertEqual(len(with_image.image_metadata), 0)
            self.assertEqual(with_image.ai_usage["services"]["openai_vision"]["call_count"], 1)
            regenerated = service.generate(
                with_image.session_id,
                shared_fields=with_image.shared_fields,
                acf_source_fields=with_image.acf_source_fields,
                selected_links=with_image.selected_links,
                current_url=None,
                expected_version=with_image.version,
            )

            self.assertEqual(vision.calls, 1)
            self.assertEqual(regenerated.state, "needs_review")
            self.assertEqual(len(regenerated.image_refs), 1)
            self.assertEqual(len(regenerated.processed_images), 1)
            self.assertEqual(len(regenerated.image_metadata), 1)
            self.assertEqual(
                regenerated.processed_images[0]["media_id"],
                regenerated.image_refs[0].media_id,
            )

    def test_voice_only_session_transcribes_before_fact_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            knowledge = KnowledgeBaseService(WORKBOOK)
            snapshot = knowledge.current()
            storage = LocalObjectStorageProvider(root / "objects")
            service = ContentSessionService(
                knowledge=knowledge,
                repository=FileSessionRepository(root / "sessions"),
                language_model=WorkbookFakeLanguageModel(snapshot),
                speech_to_text=FakeSpeechToText(),
                object_storage=storage,
            )
            audio = root / "voice.mp3"
            audio.write_bytes(b"fake audio fixture")
            session = service.create(user_id="user-1", post_type_key="event")
            session = service.attach_upload(
                session.session_id,
                source=audio,
                kind="audio",
                filename="voice.mp3",
                content_type="audio/mpeg",
                expected_version=session.version,
            )
            session = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            self.assertIn("Firmenevent", session.transcript)
            self.assertEqual(session.state, "ready_to_generate")
            self.assertTrue(session.extracted_facts)
            self.assertTrue(
                all(not fact.confirmed for fact in session.extracted_facts.values())
            )
            self.assertTrue(session.confirmed_facts)
            self.assertTrue(
                all(fact.confirmed for fact in session.confirmed_facts.values())
            )

            repeated = service.analyze(
                session.session_id,
                expected_version=session.version,
            )
            self.assertEqual(repeated.state, "ready_to_generate")
            self.assertEqual(repeated.version, session.version + 1)
            self.assertFalse(repeated.clarification_questions)
