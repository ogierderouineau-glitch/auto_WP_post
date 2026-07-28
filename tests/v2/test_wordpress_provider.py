from __future__ import annotations

import unittest
from unittest.mock import patch

from app.v2.models.step_01_session import Approval, ContentSession
from app.v2.models.step_02_payload import WordPressFields, WordPressPayload
from app.v2.providers.step_03_wordpress import ExistingWordPressProvider


class WordPressProviderTests(unittest.TestCase):
    @patch("app.v2.providers.step_03_wordpress.update_media_metadata")
    @patch("app.v2.providers.step_03_wordpress.upload_media")
    @patch("app.v2.providers.step_03_wordpress.create_term")
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value=None)
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_assigns_configured_taxonomy_to_post_and_media(
        self,
        request_json,
        _find_term,
        create_term_mock,
        upload_media_mock,
        _update_metadata,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "barkeeper": {},
                        "acf": {"properties": {"video_url": {}}},
                        "meta": {"properties": {}},
                    }
                }
            },
            {"id": 123, "status": "draft", "link": "https://example.test/florent/"},
            {},
        ]
        create_term_mock.return_value = {"id": 44, "name": "Florent"}
        upload_media_mock.return_value = (202, "https://example.test/florent.mp4")
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="bartender",
            wordpress_post_type="post",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Florent"),
            taxonomies={"barkeeper": ["Florent"]},
            media_taxonomies=["barkeeper"],
            media=[{
                "path": "/tmp/florent.mp4",
                "media_kind": "video",
                "acf_field_name": "video_url",
            }],
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
        )

        create_term_mock.assert_called_once_with("barkeeper", "Florent")
        self.assertEqual(
            request_json.call_args_list[1].kwargs["json"]["barkeeper"],
            [44],
        )
        self.assertEqual(
            request_json.call_args_list[2].kwargs["json"],
            {"post": 123, "barkeeper": [44]},
        )
        self.assertEqual(result["taxonomy_terms"], {"barkeeper": [44]})

    @patch("app.v2.providers.step_03_wordpress.update_media_metadata")
    @patch("app.v2.providers.step_03_wordpress.upload_media")
    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_builds_gallery_html_from_uploaded_wordpress_urls(
        self,
        request_json,
        _find_term,
        _resolve_tags,
        upload_media_mock,
        _update_metadata,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "acf": {"properties": {"gallery_html": {}}},
                        "meta": {"properties": {}},
                    }
                }
            },
            {"id": 123, "status": "draft", "link": "https://example.test/post/"},
            {},
        ]
        upload_media_mock.side_effect = [
            (101, "https://example.test/featured.jpg"),
            (102, "https://example.test/gallery.jpg"),
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
                status="draft",
                categories=["auto event post"],
            ),
            media=[
                {"path": "/tmp/featured.jpg", "image_usage": "featured", "image_alt": "Hero"},
                {"path": "/tmp/gallery.jpg", "image_usage": "gallery", "image_alt": "Gallery alt"},
            ],
        )

        ExistingWordPressProvider().publish(session=session, payload=payload, idempotency_key="key-1")

        gallery_html = request_json.call_args_list[1].kwargs["json"]["acf"]["gallery_html"]
        self.assertIn('src="https://example.test/gallery.jpg"', gallery_html)
        self.assertIn('alt="Gallery alt"', gallery_html)
        self.assertNotIn("featured.jpg", gallery_html)

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
        create_call = request_json.call_args_list[1]
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
                "unknown_acf": "",
            },
        )
        report = ExistingWordPressProvider().contract_report(
            session=session,
            payload=payload,
        )
        self.assertFalse(report["ready"])
        self.assertEqual(report["missing_acf_fields"], ["unknown_acf"])
        self.assertEqual(
            report["meta_resolution"]["yoast_wpseo_title"],
            "_yoast_wpseo_title",
        )
        self.assertIsNone(
            report["meta_resolution"]["yoast_wpseo_opengraph_title"]
        )

    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_contract_report_allows_unavailable_optional_shortcode_meta(
        self,
        request_json,
    ) -> None:
        request_json.return_value = {
            "schema": {
                "properties": {
                    "acf": {"properties": {}},
                    "meta": {"properties": {}},
                }
            }
        }
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="bartender",
            wordpress_post_type="bartenders",
            state="ready_to_publish",
            workbook_hash="hash",
            language="de-DE",
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Anna Schmidt"),
            meta={"_generated_variables": {"staff_name": "Anna Schmidt"}},
        )

        report = ExistingWordPressProvider().contract_report(
            session=session,
            payload=payload,
        )

        self.assertTrue(report["ready"])
        self.assertEqual(
            report["missing_optional_meta_fields"],
            ["_generated_variables"],
        )

    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_omits_shortcode_meta_when_optional_plugin_is_unavailable(
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
                        "meta": {"properties": {}},
                    }
                }
            },
            {
                "id": 123,
                "status": "draft",
                "link": "https://example.test/bartender/anna/",
            },
        ]
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="bartender",
            wordpress_post_type="bartenders",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Anna Schmidt"),
            meta={"_generated_variables": {"staff_name": "Anna Schmidt"}},
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
        )

        self.assertEqual(result["post_id"], 123)
        sent_body = request_json.call_args_list[1].kwargs["json"]
        self.assertEqual(sent_body["meta"], {})
        self.assertIn(
            "Optional generated-variable shortcode plugin is unavailable",
            result["warnings"][0],
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
        body = request_json.call_args_list[1].kwargs["json"]
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
    def test_publish_blocks_unexposed_acf_fields(
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
                "unknown_acf": "<div>Links</div>",
            },
        )

        with self.assertRaisesRegex(ValueError, "unknown_acf"):
            ExistingWordPressProvider().publish(
                session=session,
                payload=payload,
                idempotency_key="key-1",
            )

    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_updates_explicit_linked_post_id(
        self,
        request_json,
        _find_term,
        _resolve_tags,
    ) -> None:
        request_json.side_effect = [
            {"schema": {"properties": {"acf": {"properties": {}}, "meta": {"properties": {}}}}},
            {
                "id": 777,
                "status": "draft",
                "link": "https://staging.example/linked-post/",
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
            wordpress=WordPressFields(title="Updated", slug="updated", status="draft"),
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
            target_post_id=777,
        )

        self.assertEqual(result["post_id"], 777)
        self.assertEqual(result["write_mode"], "updated_linked_post")
        self.assertEqual(
            request_json.call_args_list[1].args[:2],
            ("POST", "/wp-json/wp/v2/posts/777"),
        )

    @patch("app.v2.providers.step_03_wordpress.upload_media")
    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids")
    @patch("app.v2.providers.step_03_wordpress.find_term")
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_partial_linked_update_sends_only_changed_destinations(
        self,
        request_json,
        find_term,
        resolve_tag_ids,
        upload_media,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "acf": {"properties": {"hero_h1": {}, "verlauf": {}}},
                        "meta": {"properties": {"_yoast_wpseo_title": {}}},
                    }
                }
            },
            {
                "id": 777,
                "status": "draft",
                "link": "https://staging.example/linked-post/",
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
                title="Updated",
                slug="updated",
                status="draft",
                categories=["Events"],
                tags=["Berlin"],
            ),
            meta={"yoast_wpseo_title": "SEO title"},
            acf={"hero_h1": "Updated hero", "verlauf": "<ul><li>Full list</li></ul>"},
            media=[{"path": "/tmp/unchanged.webp", "image_usage": "featured"}],
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
            target_post_id=777,
            partial_update_fields={
                "wordpress": {"title"},
                "meta": set(),
                "acf": {"hero_h1"},
            },
        )

        body = request_json.call_args_list[1].kwargs["json"]
        self.assertEqual(body, {"title": "Updated", "acf": {"hero_h1": "Updated hero"}})
        self.assertEqual(
            result["sent_fields"],
            {"wordpress": ["title"], "meta": [], "acf": ["hero_h1"]},
        )
        self.assertEqual(result["sent_body"], body)
        find_term.assert_not_called()
        resolve_tag_ids.assert_not_called()
        upload_media.assert_not_called()

    @patch("app.v2.providers.step_03_wordpress.update_media_metadata")
    @patch("app.v2.providers.step_03_wordpress.upload_media")
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_partial_linked_update_replaces_media_before_deleting_previous_attachment(
        self,
        request_json,
        upload_media_mock,
        _update_metadata,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "acf": {"properties": {"video_url": {}}},
                        "meta": {"properties": {}},
                    }
                }
            },
            {
                "id": 777,
                "status": "draft",
                "link": "https://staging.example/linked-post/",
            },
            {},
            {},
        ]
        upload_media_mock.return_value = (202, "https://staging.example/new-video.mp4")
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="bartender",
            wordpress_post_type="bartender",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
            wordpress_result={
                "post_id": 777,
                "media": [{"media_id": 101, "acf_field_name": "video_url"}],
            },
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Updated"),
            media=[
                {
                    "path": "/tmp/new-video.mp4",
                    "media_kind": "video",
                    "acf_field_name": "video_url",
                }
            ],
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
            target_post_id=777,
            partial_update_fields={
                "wordpress": {"media"},
                "meta": set(),
                "acf": set(),
            },
        )

        self.assertEqual(
            request_json.call_args_list[1].kwargs["json"],
            {"acf": {"video_url": 202}},
        )
        self.assertEqual(
            request_json.call_args_list[2].args[:2],
            ("POST", "/wp-json/wp/v2/media/202"),
        )
        self.assertEqual(
            request_json.call_args_list[3].args[:2],
            ("DELETE", "/wp-json/wp/v2/media/101"),
        )
        self.assertEqual(
            request_json.call_args_list[3].kwargs["params"],
            {"force": "true"},
        )
        self.assertEqual(result["deleted_media_ids"], [101])
        self.assertEqual(result["media"][0]["media_id"], 202)

    @patch("app.v2.providers.step_03_wordpress.update_media_metadata")
    @patch("app.v2.providers.step_03_wordpress.upload_media")
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_partial_linked_update_changes_media_metadata_without_reupload(
        self,
        request_json,
        upload_media_mock,
        update_metadata_mock,
    ) -> None:
        request_json.side_effect = [
            {"schema": {"properties": {"acf": {"properties": {}}, "meta": {"properties": {}}}}},
            {"id": 777, "status": "draft", "link": "https://example.test/post/"},
            {},
        ]
        previous = {
            "media_id": "image-1",
            "path": "/stored/image.webp",
            "image_title": "Previous title",
            "image_usage": "gallery",
        }
        current = {**previous, "image_title": "Updated title"}
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            wordpress_post_type="post",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
            wordpress_payload={"wordpress": {}, "media": [current]},
            published_wordpress_payload={"wordpress": {}, "media": [previous]},
            wordpress_result={
                "post_id": 777,
                "media": [{
                    **previous,
                    "media_id": 101,
                    "source_url": "https://example.test/image.webp",
                }],
            },
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(),
            media=[current],
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
            target_post_id=777,
            partial_update_fields={
                "wordpress": {"media"},
                "meta": set(),
                "acf": set(),
            },
        )

        upload_media_mock.assert_not_called()
        update_metadata_mock.assert_called_once_with(
            101,
            alt_text=None,
            title="Updated title",
            caption=None,
            description=None,
        )
        self.assertEqual(result["media"][0]["media_id"], 101)
        self.assertEqual(result["deleted_media_ids"], [])

    @patch("app.v2.providers.step_03_wordpress.update_media_metadata")
    @patch("app.v2.providers.step_03_wordpress.upload_media")
    def test_sync_media_matches_legacy_results_by_path_after_gallery_reordering(
        self,
        upload_media_mock,
        update_metadata_mock,
    ) -> None:
        first = {
            "media_id": "image-1",
            "path": "/stored/first.webp",
            "image_title": "First",
        }
        second = {
            "media_id": "image-2",
            "path": "/stored/second.webp",
            "image_title": "Second",
        }
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="event",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            published_wordpress_payload={"media": [first, second]},
            wordpress_result={
                "media": [
                    {**second, "media_id": 202},
                    {**first, "media_id": 101},
                ],
            },
        )

        synchronized = ExistingWordPressProvider._sync_media(session, [second])

        upload_media_mock.assert_not_called()
        update_metadata_mock.assert_not_called()
        self.assertEqual(synchronized[0]["media_id"], 202)
        self.assertEqual(synchronized[0]["source_media_id"], "media:image-2")

    @patch("app.v2.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("app.v2.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("app.v2.providers.step_03_wordpress.request_json")
    def test_publish_can_force_create_new_post(
        self,
        request_json,
        _find_term,
        _resolve_tags,
    ) -> None:
        request_json.side_effect = [
            {"schema": {"properties": {"acf": {"properties": {}}, "meta": {"properties": {}}}}},
            {
                "id": 778,
                "status": "draft",
                "link": "https://staging.example/new-post/",
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
            wordpress=WordPressFields(title="New", slug="new-post", status="draft"),
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
            force_create_new=True,
        )

        self.assertEqual(result["post_id"], 778)
        self.assertEqual(result["write_mode"], "created")
        self.assertEqual(len(request_json.call_args_list), 2)
        self.assertEqual(
            request_json.call_args_list[1].args[:2],
            ("POST", "/wp-json/wp/v2/posts"),
        )
