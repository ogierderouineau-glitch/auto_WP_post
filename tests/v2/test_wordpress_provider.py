from __future__ import annotations

import unittest
from unittest.mock import patch

from app.v2.models.step_01_session import Approval, ContentSession
from app.v2.models.step_02_payload import WordPressFields, WordPressPayload
from app.v2.providers.step_03_wordpress import ExistingWordPressProvider


class WordPressProviderTests(unittest.TestCase):
    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[20])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_direct_publish_routes_meta_and_acf_without_legacy_import(
        self,
        request_json,
        _find_term,
        _resolve_tags,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "acf": {
                            "properties": {
                                "hero_h1": {},
                                "verlauf_h2": {},
                            }
                        },
                        "meta": {
                            "properties": {
                                "_yoast_wpseo_title": {},
                            }
                        },
                    }
                }
            },
            [],
            {
                "id": 123,
                "status": "draft",
                "link": "https://staging.example/test-event/",
            },
        ]
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            wordpress_post_type="post",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(
                title="Test Event",
                slug="test-event",
                excerpt="Excerpt",
                status="draft",
                categories=["auto event post"],
                tags=["Berlin"],
            ),
            meta={"yoast_wpseo_title": "SEO title"},
            acf={"hero_h1": "Hero", "verlauf_h2": "Ablauf"},
        )
        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
        )
        self.assertEqual(result["post_id"], 123)
        create_call = request_json.call_args_list[2]
        self.assertEqual(create_call.args[:2], ("POST", "/wp-json/wp/v2/posts"))
        body = create_call.kwargs["json"]
        self.assertEqual(body["meta"]["_yoast_wpseo_title"], "SEO title")
        self.assertEqual(body["acf"]["hero_h1"], "Hero")
        self.assertEqual(body["acf"]["verlauf_h2"], "Ablauf")

    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_contract_report_identifies_unexposed_destinations(self, request_json) -> None:
        request_json.return_value = {
            "schema": {
                "properties": {
                    "acf": {"properties": {"hero_h1": {}}},
                    "meta": {"properties": {"_yoast_wpseo_title": {}}},
                }
            }
        }
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            wordpress_post_type="post",
            state="ready_to_publish",
            workbook_hash="hash",
            language="de-DE",
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Title"),
            meta={
                "yoast_wpseo_title": "SEO title",
                "yoast_wpseo_opengraph_title": "Social title",
            },
            acf={
                "hero_h1": "Hero",
                "related_links_html": "",
            },
        )
        report = ExistingWordPressProvider().contract_report(
            session=session,
            payload=payload,
        )
        self.assertFalse(report["ready"])
        self.assertEqual(report["missing_acf_fields"], ["related_links_html"])
        self.assertEqual(
            report["meta_resolution"]["yoast_wpseo_title"],
            "_yoast_wpseo_title",
        )
        self.assertIsNone(
            report["meta_resolution"]["yoast_wpseo_opengraph_title"]
        )

    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_routes_open_graph_to_yoast_native_hyphen_keys(
        self,
        request_json,
        _find_term,
        _resolve_tags,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "acf": {"properties": {}},
                        "meta": {
                            "properties": {
                                "_yoast_wpseo_opengraph-title": {},
                                "_yoast_wpseo_opengraph-description": {},
                            }
                        },
                    }
                }
            },
            [],
            {
                "id": 123,
                "status": "draft",
                "link": "https://staging.example/test-event/",
            },
        ]
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            wordpress_post_type="post",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(
                title="Test Event",
                slug="test-event",
                status="draft",
                categories=["auto event post"],
            ),
            meta={
                "yoast_wpseo_opengraph_title": "Social title",
                "yoast_wpseo_opengraph_description": "Social description",
            },
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
        )

        self.assertEqual(result["post_id"], 123)
        body = request_json.call_args_list[2].kwargs["json"]
        self.assertEqual(
            body["meta"]["_yoast_wpseo_opengraph-title"],
            "Social title",
        )
        self.assertEqual(
            body["meta"]["_yoast_wpseo_opengraph-description"],
            "Social description",
        )

    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_omits_non_blocking_related_links_when_rest_schema_lacks_field(
        self,
        request_json,
        _find_term,
        _resolve_tags,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "acf": {"properties": {"hero_h1": {}}},
                        "meta": {"properties": {}},
                    }
                }
            },
            [],
            {
                "id": 123,
                "status": "draft",
                "link": "https://staging.example/test-event/",
            },
        ]
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            wordpress_post_type="post",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(
                title="Test Event",
                slug="test-event",
                status="draft",
                categories=["auto event post"],
            ),
            acf={
                "hero_h1": "Hero",
                "related_links_html": "<div>Links</div>",
            },
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
        )

        body = request_json.call_args_list[2].kwargs["json"]
        self.assertEqual(body["acf"], {"hero_h1": "Hero"})
        self.assertIn("related_links_html", result["warnings"][0])
