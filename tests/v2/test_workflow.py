from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.models.step_01_session import ContentSession
from app.v2.models.step_02_payload import WordPressPayload
from app.v2.providers.step_01_interfaces import WordPressProvider
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.sessions.step_03_service import ContentSessionService

WORKBOOK = Path(
    os.getenv(
        "V2_TEST_WORKBOOK",
        "/home/ogier-derouineau/Downloads/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm",
    )
)


class FakeWordPressProvider(WordPressProvider):
    def __init__(self) -> None:
        self.calls = 0

    def publish(
        self,
        *,
        session: ContentSession,
        payload: WordPressPayload,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.calls += 1
        return {
            "post_id": 123,
            "status": payload.wordpress.status,
            "view_url": "https://staging.example/posts/123",
            "edit_url": "https://staging.example/wp-admin/post.php?post=123&action=edit",
            "idempotency_key": idempotency_key,
        }


@unittest.skipUnless(WORKBOOK.is_file(), f"V2 test workbook not found: {WORKBOOK}")
class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.wordpress = FakeWordPressProvider()
        self.knowledge = KnowledgeBaseService(WORKBOOK)
        self.service = ContentSessionService(
            knowledge=self.knowledge,
            repository=FileSessionRepository(self.temporary.name),
            wordpress=self.wordpress,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_complete_image_free_lifecycle_requires_approval(self) -> None:
        session = self.service.create(user_id="user-1", post_type_key="event")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        facts = {
            row.field_key: self._value(row.value_type, row.min_words)
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role == "input_fact"
            and row.required_for_analysis
        }
        session = self.service.add_inputs(
            session.session_id,
            manual_text="Confirmed event details.",
            confirmed_facts=facts,
            expected_version=session.version,
        )
        session = self.service.analyze(
            session.session_id,
            expected_version=session.version,
        )
        self.assertEqual(session.state, "ready_to_generate")

        shared = {
            row.field_key: self._value(
                row.value_type,
                row.min_words,
                row.min_characters,
            )
            for row in snapshot.shared_fields
            if row.enabled
            and row.include_in_ai_schema
        }
        acf = {
            row.field_key: self._value(row.value_type, row.min_words)
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role != "input_fact"
            and row.required_for_output
        }
        eligible = self.service.internal_links.eligible(
            snapshot,
            post_type_key="event",
            language="de-DE",
            current_url=None,
        )
        selected = [
            {"link_id": row.link_id, "anchor_text": row.anchor_text}
            for row in eligible.candidates[:2]
        ]
        session = self.service.generate(
            session.session_id,
            shared_fields=shared,
            acf_source_fields=acf,
            selected_links=selected,
            current_url=None,
            expected_version=session.version,
        )
        self.assertEqual(session.state, "needs_review")
        self.assertFalse(session.image_refs)
        self.assertFalse(session.processed_images)
        self.assertEqual(session.wordpress_payload["acf"]["hero_h1"], acf["hero_h1"])
        self.assertEqual(session.wordpress_payload["acf"]["verlauf_h2"], acf["verlauf_h2"])

        session = self.service.approve(
            session.session_id,
            user_id="user-1",
            expected_version=session.version,
        )
        self.assertEqual(session.state, "ready_to_publish")
        session = self.service.publish(
            session.session_id,
            idempotency_key="publish-1",
            expected_version=session.version,
        )
        self.assertEqual(session.state, "published")
        self.assertEqual(session.wordpress_result["post_id"], 123)
        self.assertEqual(self.wordpress.calls, 1)
        repeated = self.service.publish(
            session.session_id,
            idempotency_key="publish-1",
            expected_version=session.version,
        )
        self.assertEqual(repeated.version, session.version)
        self.assertEqual(self.wordpress.calls, 1)

    def test_generation_caps_selected_internal_links_to_workbook_maximum(self) -> None:
        session = self.service.create(user_id="user-1", post_type_key="event")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        facts = {
            row.field_key: self._value(row.value_type, row.min_words)
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role == "input_fact"
            and row.required_for_analysis
        }
        session = self.service.add_inputs(
            session.session_id,
            manual_text="Confirmed event details.",
            confirmed_facts=facts,
            expected_version=session.version,
        )
        session = self.service.analyze(
            session.session_id,
            expected_version=session.version,
        )
        shared = {
            row.field_key: self._value(
                row.value_type,
                row.min_words,
                row.min_characters,
            )
            for row in snapshot.shared_fields
            if row.enabled
            and row.include_in_ai_schema
        }
        acf = {
            row.field_key: self._value(row.value_type, row.min_words)
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role != "input_fact"
            and row.required_for_output
        }
        eligible = self.service.internal_links.eligible(
            snapshot,
            post_type_key="event",
            language="de-DE",
            current_url=None,
        )
        _, maximum_links = self.service._internal_link_range(snapshot)
        self.assertIsNotNone(maximum_links)
        selected: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        seen_anchors: set[str] = set()
        for row in eligible.candidates:
            if row.target_url in seen_urls or row.anchor_text.casefold() in seen_anchors:
                continue
            selected.append({"link_id": row.link_id, "anchor_text": row.anchor_text})
            seen_urls.add(row.target_url)
            seen_anchors.add(row.anchor_text.casefold())
            if len(selected) > maximum_links:
                break
        self.assertGreater(len(selected), maximum_links)

        generated = self.service.generate(
            session.session_id,
            shared_fields=shared,
            acf_source_fields=acf,
            selected_links=selected,
            current_url=None,
            expected_version=session.version,
        )

        self.assertLessEqual(len(generated.selected_links), maximum_links)
        self.assertEqual(generated.selected_links, selected[:maximum_links])

    def test_generation_tops_up_too_few_internal_links(self) -> None:
        session = self.service.create(user_id="user-1", post_type_key="event")
        snapshot = self.knowledge.by_hash(session.workbook_hash)
        facts = {
            row.field_key: self._value(row.value_type, row.min_words)
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role == "input_fact"
            and row.required_for_analysis
        }
        session = self.service.add_inputs(
            session.session_id,
            manual_text="Confirmed event details.",
            confirmed_facts=facts,
            expected_version=session.version,
        )
        session = self.service.analyze(
            session.session_id,
            expected_version=session.version,
        )
        shared = {
            row.field_key: self._value(
                row.value_type,
                row.min_words,
                row.min_characters,
            )
            for row in snapshot.shared_fields
            if row.enabled
            and row.include_in_ai_schema
        }
        acf = {
            row.field_key: self._value(row.value_type, row.min_words)
            for row in snapshot.acf_fields
            if row.enabled
            and row.post_type_key == "event"
            and row.field_role != "input_fact"
            and row.required_for_output
        }
        eligible = self.service.internal_links.eligible(
            snapshot,
            post_type_key="event",
            language="de-DE",
            current_url=None,
        )
        minimum_links, _ = self.service._internal_link_range(snapshot)
        self.assertGreaterEqual(len(eligible.candidates), minimum_links)
        selected = [
            {
                "link_id": eligible.candidates[0].link_id,
                "anchor_text": eligible.candidates[0].anchor_text,
            }
        ]

        generated = self.service.generate(
            session.session_id,
            shared_fields=shared,
            acf_source_fields=acf,
            selected_links=selected,
            current_url=None,
            expected_version=session.version,
        )

        self.assertGreaterEqual(len(generated.selected_links), minimum_links)
        self.assertEqual(generated.selected_links[0], selected[0])

    @staticmethod
    def _value(
        value_type: str,
        min_words: int | None = None,
        min_characters: int | None = None,
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
        word_count = max(min_words or 1, 1)
        value = " ".join(["Wort"] * word_count)
        if min_characters and len(value) < min_characters:
            value += " x" * min_characters
        return value
