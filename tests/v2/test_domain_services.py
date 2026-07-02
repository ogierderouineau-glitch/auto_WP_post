from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.v2.context.step_01_builder import GenerationContextBuilder
from app.v2.internal_links.step_01_service import InternalLinkService
from app.v2.knowledge_base.step_01_models import ImageMetadataField
from app.v2.knowledge_base.step_02_loader import WorkbookLoader
from app.v2.knowledge_base.step_03_validator import WorkbookValidator
from app.v2.models.step_01_session import ContentSession, FactValue, MediaReference
from app.v2.payloads.step_02_builder import PayloadBuilder
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.workflow.step_01_conditions import condition_matches
from app.v2.workflow.step_02_clarification import ClarificationService
from app.v2.sessions.step_03_service import ContentSessionService

WORKBOOK = Path(
    os.getenv(
        "V2_TEST_WORKBOOK",
        "/home/ogier-derouineau/Documents/FLAIRLAB_Knowledge_Base_Revised_V6.xlsm",
    )
)


class StaticKnowledge:
    def __init__(self, snapshot: object) -> None:
        self.snapshot = snapshot

    def current(self) -> object:
        return self.snapshot

    def by_hash(self, workbook_hash: str) -> object:
        self.assert_hash = workbook_hash
        return self.snapshot


class MetadataOnlyLanguageModel:
    last_usage: dict[str, Any] | None = None

    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any:
        if task != "image_metadata":
            raise AssertionError(f"Unexpected fake model task: {task}")
        self.last_usage = {
            "service": "openai_text",
            "call_name": task,
            "model": "fake-text",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "estimated_cost_usd": None,
        }
        return schema.model_validate(
            {
                field_key: f"generated {field_key}"
                for field_key in schema.model_fields
            }
        )


class FakeObjectStorage:
    def __init__(self) -> None:
        self.downloads: list[tuple[str, Path]] = []

    def put(self, source: Path, key: str) -> str:
        return f"gs://bucket/{key}"

    def get(self, uri: str, destination: Path) -> Path:
        self.downloads.append((uri, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image")
        return destination


class PartialUpdateDiffTests(unittest.TestCase):
    def test_post_title_edit_maps_to_wordpress_title_only(self) -> None:
        snapshot = SimpleNamespace(
            shared_fields=(
                SimpleNamespace(
                    field_key="post_title",
                    enabled=True,
                    include_in_payload=True,
                    destination_type="wordpress",
                    destination_key="title",
                ),
                SimpleNamespace(
                    field_key="seo_title",
                    enabled=True,
                    include_in_payload=True,
                    destination_type="yoast",
                    destination_key="_yoast_wpseo_title",
                ),
            ),
            acf_fields=(),
        )

        fields = ContentSessionService._wordpress_partial_update_fields(
            snapshot,
            "event",
            shared_fields={"post_title": "Updated title"},
            acf_source_fields={},
        )

        self.assertEqual(fields["wordpress"], {"title"})
        self.assertEqual(fields["meta"], set())
        self.assertEqual(fields["acf"], set())

    def test_missing_previous_payload_does_not_infer_all_fields_changed(self) -> None:
        fields = ContentSessionService._wordpress_payload_diff_fields(
            {
                "wordpress": {
                    "title": "Updated title",
                    "status": "draft",
                },
                "meta": {"yoast_wpseo_title": "SEO"},
                "acf": {"hero_h1": "Hero"},
            },
            {},
        )

        self.assertEqual(fields["wordpress"], set())
        self.assertEqual(fields["meta"], set())
        self.assertEqual(fields["acf"], set())


class FeaturedImageMetadataRegressionTests(unittest.TestCase):
    def test_metadata_overwrite_preserves_selected_featured_image(self) -> None:
        snapshot = SimpleNamespace(
            image_metadata_fields=(
                ImageMetadataField(
                    sheet_row=1,
                    field_key="image_alt",
                    destination_type="meta",
                    destination_key="alt",
                    description_de="Alternativtext",
                    required=True,
                    value_type="text",
                    generation_stage="draft",
                    source_mode="generated",
                    enabled=True,
                ),
            ),
            agent_instructions=(),
            image_metadata_rules=(),
            acf_fields=(),
        )
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            state="needs_review",
            workbook_hash="hash",
            language="de-DE",
            image_refs=[
                MediaReference(
                    media_id="image-1",
                    filename="first.png",
                    storage_uri="local://first.png",
                    content_type="image/png",
                    size_bytes=1,
                ),
                MediaReference(
                    media_id="image-2",
                    filename="second.png",
                    storage_uri="local://second.png",
                    content_type="image/png",
                    size_bytes=1,
                ),
            ],
            processed_images=[
                {"media_id": "image-1", "filename": "first.webp", "path": "local://first.webp"},
                {"media_id": "image-2", "filename": "second.webp", "path": "local://second.webp"},
            ],
            image_metadata=[
                {"media_id": "image-2", "image_usage": "featured", "image_priority": 1},
                {"media_id": "image-1", "image_usage": "gallery", "image_priority": 2},
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = ContentSessionService(
                knowledge=StaticKnowledge(snapshot),
                repository=FileSessionRepository(temporary),
                language_model=MetadataOnlyLanguageModel(),
            )

            updated = service._generate_missing_image_metadata(
                snapshot,
                session,
                overwrite_existing=True,
            )

        featured = [
            row for row in updated.image_metadata
            if row.get("image_usage") == "featured"
        ]
        self.assertEqual(len(featured), 1)
        self.assertEqual(featured[0]["media_id"], "image-2")
        self.assertEqual(featured[0]["image_priority"], 1)

    def test_media_path_materializes_gcs_uri_before_file_response(self) -> None:
        storage = FakeObjectStorage()
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            state="uploading",
            workbook_hash="hash",
            language="de-DE",
            image_refs=[
                MediaReference(
                    media_id="image-1",
                    filename="first.png",
                    storage_uri="gs://bucket/session/originals/first.png",
                    content_type="image/png",
                    size_bytes=1,
                ),
            ],
            processed_images=[
                {
                    "media_id": "image-1",
                    "filename": "first.webp",
                    "path": "gs://bucket/session/processed/first.webp",
                },
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            repository = FileSessionRepository(temporary)
            repository.create(session)
            service = ContentSessionService(
                knowledge=StaticKnowledge(SimpleNamespace()),
                repository=repository,
                object_storage=storage,
            )

            path = service.media_path(
                session.session_id,
                kind="image",
                filename="first.webp",
            )

        self.assertTrue(path.is_file())
        self.assertNotEqual(path.parts[0], "gs:")
        self.assertEqual(storage.downloads[0][0], "gs://bucket/session/processed/first.webp")

    def test_publication_media_materializes_gcs_uri_before_wordpress_upload(self) -> None:
        storage = FakeObjectStorage()
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            state="ready_to_publish",
            workbook_hash="hash",
            language="de-DE",
            processed_images=[
                {
                    "media_id": "image-1",
                    "filename": "first.webp",
                    "path": "gs://bucket/session/processed/first.webp",
                },
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = ContentSessionService(
                knowledge=StaticKnowledge(SimpleNamespace()),
                repository=FileSessionRepository(temporary),
                object_storage=storage,
            )

            media = service._materialize_publication_media(
                session,
                [
                    {
                        "media_id": "image-1",
                        "path": "gs://bucket/session/processed/first.webp",
                        "image_usage": "featured",
                    }
                ],
            )

        self.assertTrue(Path(media[0]["path"]).is_file())
        self.assertFalse(media[0]["path"].startswith("gs:"))
        self.assertEqual(media[0]["output"], media[0]["path"])
        self.assertEqual(storage.downloads[0][0], "gs://bucket/session/processed/first.webp")


@unittest.skipUnless(WORKBOOK.is_file(), f"V2 test workbook not found: {WORKBOOK}")
class DomainServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = WorkbookValidator().validate(WorkbookLoader().load(WORKBOOK))

    def session(self, **updates: object) -> ContentSession:
        base = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            state="created",
            workbook_hash=self.snapshot.version.sha256,
            language="de-DE",
        )
        return base.model_copy(update=updates)

    def test_manual_text_only_skips_transcription(self) -> None:
        session = self.session(manual_text="Event in Berlin")
        self.assertFalse(condition_matches("audio_count_gt_0", session))

    def test_image_free_session_omits_image_blueprint_rows(self) -> None:
        context = GenerationContextBuilder().build(
            snapshot=self.snapshot,
            task="content_generation",
            post_type_key="event",
            session=self.session(),
        )
        target_keys = {row["target_key"] for row in context.blueprint}
        self.assertNotIn("image_caption", target_keys)
        self.assertNotIn("event_gallery", target_keys)

    def test_image_session_includes_image_blueprint_rows(self) -> None:
        image = MediaReference(
            media_id="image-1",
            filename="image.jpg",
            storage_uri="gs://bucket/image.jpg",
            content_type="image/jpeg",
            size_bytes=10,
        )
        context = GenerationContextBuilder().build(
            snapshot=self.snapshot,
            task="content_generation",
            post_type_key="event",
            session=self.session(image_refs=[image]),
        )
        target_keys = {row["target_key"] for row in context.blueprint}
        self.assertIn("image_caption", target_keys)
        self.assertIn("event_gallery", target_keys)

    def test_context_is_field_addressable_and_excludes_unrelated_rules(self) -> None:
        context = GenerationContextBuilder().build(
            snapshot=self.snapshot,
            task="seo_generation",
            post_type_key="event",
            session=self.session(),
            field_keys=["seo_title"],
        )
        self.assertEqual(set(context.fields), {"seo_title"})
        exact_targets = {
            row["target_key"] for row in context.fields["seo_title"].exact_rules
        }
        self.assertEqual(exact_targets, {"seo_title"})

    def test_generation_context_includes_source_text_for_optional_semantic_fields(self) -> None:
        context = GenerationContextBuilder().build(
            snapshot=self.snapshot,
            task="generation",
            post_type_key="event",
            session=self.session(
                manual_text=(
                    "Die Besonderheit war die alkoholfreie Signature-Auswahl. "
                    "Der Fokus lag auf kurzer Wartezeit. "
                    "Die Herausforderung war ein enger Aufbau."
                )
            ),
            field_keys=["fact_speciality", "fact_focus", "fact_challenge", "event_challenge"],
        )

        self.assertIn("Herausforderung", context.source_text["manual_text"])
        challenge_guidance = context.fields["fact_challenge"].schema_data["guidance_de"]
        self.assertIn("Herausforderung", challenge_guidance)
        self.assertIn("source_text", challenge_guidance)
        self.assertNotIn("Fokus oder Besonderheit", challenge_guidance)
        self.assertIn("raw_text_without_html", context.fields["fact_challenge"].schema_data["model_output_contract"])

    def test_missing_required_facts_are_bundled(self) -> None:
        service = ClarificationService()
        missing = service.missing_required_dependencies(self.snapshot, self.session())
        self.assertTrue(missing)
        questions = service.bundled_questions(missing)
        self.assertEqual(len(questions), 1)

    def test_optional_dependency_does_not_create_a_question(self) -> None:
        required_keys = {
            row.field_key
            for row in self.snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role == "input_fact"
            and row.required_for_analysis
        }
        facts = {
            key: FactValue(
                value=f"value-{key}",
                source="user_correction",
                confidence=1,
                confirmed=True,
            )
            for key in required_keys
        }
        missing = ClarificationService().missing_required_dependencies(
            self.snapshot,
            self.session(confirmed_facts=facts),
        )
        missing_fields = {item.output_field_key for item in missing}
        self.assertNotIn("fact_bar", missing_fields)
        self.assertNotIn("fact_bartender", missing_fields)

    def test_optional_derived_field_is_not_exposed_without_confirmed_dependency(self) -> None:
        row = next(
            item for item in self.snapshot.acf_fields
            if item.field_key == "fact_bartender"
        )
        self.assertFalse(
            ContentSessionService._acf_field_is_eligible(row, self.session())
        )
        confirmed = self.session(
            confirmed_facts={
                "bartender": FactValue(
                    value=["Florent"],
                    source="user_correction",
                    confidence=1,
                    confirmed=True,
                )
            }
        )
        self.assertTrue(
            ContentSessionService._acf_field_is_eligible(row, confirmed)
        )

    def test_optional_challenge_field_requires_confirmed_fact_condition(self) -> None:
        row = next(
            item for item in self.snapshot.acf_fields
            if item.field_key == "event_challenge"
        )
        self.assertEqual(row.generation_condition, "fact_present:challenge")
        self.assertFalse(
            ContentSessionService._acf_field_is_eligible(row, self.session())
        )
        confirmed = self.session(
            confirmed_facts={
                "challenge": FactValue(
                    value="enger Aufbau",
                    source="user_correction",
                    confidence=1,
                    confirmed=True,
                )
            }
        )
        self.assertTrue(
            ContentSessionService._acf_field_is_eligible(row, confirmed)
        )

    def test_user_correction_overrides_extracted_fact(self) -> None:
        original = FactValue(
            value="Hamburg",
            source="transcript",
            confidence=0.8,
            confirmed=False,
        )
        corrected = ClarificationService().apply_corrections(
            self.session(confirmed_facts={"city": original}),
            {"city": "Berlin"},
        )
        self.assertEqual(corrected.confirmed_facts["city"].value, "Berlin")
        self.assertEqual(corrected.confirmed_facts["city"].source, "user_correction")

    def test_internal_links_are_filtered_and_urls_are_resolved_in_python(self) -> None:
        service = InternalLinkService()
        eligible = service.eligible(
            self.snapshot,
            post_type_key="event",
            language="de-DE",
            current_url="https://staging.flairlab.de/mobile-cocktailbar/",
        )
        self.assertNotIn(
            "https://staging.flairlab.de/mobile-cocktailbar/",
            {row.target_url for row in eligible.candidates},
        )
        first = eligible.candidates[0]
        rendered = service.render(
            eligible,
            [{"link_id": first.link_id, "anchor_text": first.anchor_text}],
        )
        self.assertIn(first.target_url, rendered)

    def test_zero_internal_link_candidates_produces_empty_html_with_evidence(self) -> None:
        eligible = InternalLinkService().eligible(
            self.snapshot,
            post_type_key="event",
            language="fr-FR",
            current_url=None,
        )
        self.assertEqual(eligible.candidates, ())
        self.assertIsNotNone(eligible.empty_reason)
        self.assertEqual(InternalLinkService().render(eligible, []), "")

    def test_payload_routes_workbook_destinations_and_aggregations(self) -> None:
        shared = {
            "post_title": "Test Event",
            "slug": "test-event",
            "excerpt": "Kurztext",
            "status": "draft",
            "category": "auto event post",
            "tags": ["Berlin"],
            "focus_keyword": "Event Berlin",
            "seo_title": "Event Berlin",
            "meta_description": "Event in Berlin",
            "social_title": "Event Berlin",
            "social_description": "Event in Berlin",
            "related_links_html": "",
        }
        acf = {
            "hero_h1": "Event Berlin",
            "verlauf_h2": "Der Ablauf",
            "fact_event": "Sommerfest",
            "fact_service": "Cocktailcatering",
        }
        payload = PayloadBuilder().build(
            self.snapshot,
            post_type_key="event",
            shared_values=shared,
            acf_source_values=acf,
        )
        self.assertEqual(payload.wordpress.title, "Test Event")
        self.assertEqual(payload.meta["yoast_wpseo_title"], "Event Berlin")
        self.assertEqual(payload.acf["hero_h1"], "Event Berlin")
        self.assertEqual(payload.acf["verlauf_h2"], "Der Ablauf")
        self.assertIn("<ul>", payload.acf["fakten"])
        self.assertIn("<strong>Event:</strong> Sommerfest", payload.acf["fakten"])
        self.assertNotIn("&lt;li&gt;", payload.acf["fakten"])

    def test_file_repository_uses_optimistic_versioning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = FileSessionRepository(temporary)
            session = repository.create(self.session())
            saved = repository.save(
                session.model_copy(update={"manual_text": "hello"}),
                expected_version=1,
            )
            self.assertEqual(saved.version, 2)

    def test_featured_image_selection_is_stored_in_v2_image_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = FileSessionRepository(temporary)
            session = self.session(
                state="uploading",
                image_refs=[
                    MediaReference(
                        media_id="image-1",
                        filename="first.png",
                        storage_uri="local://first.png",
                        content_type="image/png",
                        size_bytes=1,
                    ),
                    MediaReference(
                        media_id="image-2",
                        filename="second.png",
                        storage_uri="local://second.png",
                        content_type="image/png",
                        size_bytes=1,
                    ),
                ],
                processed_images=[
                    {"media_id": "image-1", "filename": "first.webp", "path": "local://first.webp"},
                    {"media_id": "image-2", "filename": "second.webp", "path": "local://second.webp"},
                ],
            )
            repository.create(session)
            service = ContentSessionService(
                knowledge=StaticKnowledge(self.snapshot),
                repository=repository,
            )

            updated = service.set_featured_image(
                session.session_id,
                filename="second.webp",
                expected_version=session.version,
            )

            featured = [
                row for row in updated.image_metadata
                if row.get("image_usage") == "featured"
            ]
            self.assertEqual(len(featured), 1)
            self.assertEqual(featured[0]["media_id"], "image-2")
            self.assertEqual(featured[0]["image_priority"], 1)
