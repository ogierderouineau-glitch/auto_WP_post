from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.models.step_01_session import Approval, ContentSession
from backend.app.models.step_02_payload import WordPressFields, WordPressPayload
from backend.app.providers.step_03_wordpress import ExistingWordPressProvider
from backend.wordpress_api import (
    find_term,
    match_registered_term,
    taxonomy_terms_endpoint,
)


class WordPressTaxonomyEndpointTests(unittest.TestCase):
    def test_registered_term_matching_ignores_accents(self) -> None:
        term = match_registered_term(
            [{"id": 7, "name": "João", "slug": "joao"}],
            "Joao",
        )

        self.assertEqual(term["id"], 7)

    @patch("backend.wordpress_api.request_json")
    def test_discovers_custom_taxonomy_rest_base(self, request_json) -> None:
        request_json.return_value = {
            "cocktails": {
                "slug": "cocktails",
                "rest_base": "cocktail",
                "rest_namespace": "wp/v2",
            }
        }

        endpoint = taxonomy_terms_endpoint("cocktails")

        self.assertEqual(endpoint, "/wp-json/wp/v2/cocktail")
        request_json.assert_called_once_with(
            "GET",
            "/wp-json/wp/v2/taxonomies",
        )

    @patch("backend.wordpress_api.request_json")
    def test_matches_taxonomy_by_exposed_rest_base(self, request_json) -> None:
        request_json.return_value = {
            "internal_cocktail_taxonomy": {
                "slug": "internal_cocktail_taxonomy",
                "rest_base": "cocktails",
                "rest_namespace": "wp/v2",
            }
        }

        self.assertEqual(
            taxonomy_terms_endpoint("cocktails"),
            "/wp-json/wp/v2/cocktails",
        )

    @patch("backend.wordpress_api.request_json")
    def test_term_lookup_accepts_a_discovered_endpoint(self, request_json) -> None:
        request_json.return_value = [{"id": 7, "name": "Mojito", "slug": "mojito"}]

        term = find_term("/wp-json/wp/v2/cocktail", "Mojito")

        self.assertEqual(term["id"], 7)
        request_json.assert_called_once_with(
            "GET",
            "/wp-json/wp/v2/cocktail",
            params={"search": "Mojito", "per_page": 100},
        )


class WordPressProviderTests(unittest.TestCase):
    @patch(
        "backend.app.providers.step_03_wordpress.registered_terms",
        return_value=[{"id": 12, "name": "João", "slug": "joao"}],
    )
    @patch(
        "backend.app.providers.step_03_wordpress.taxonomy_terms_endpoint",
        return_value="/wp-json/wp/v2/barkeepers",
    )
    def test_registered_candidates_use_canonical_wordpress_spelling(
        self,
        _taxonomy_endpoint,
        _registered_terms,
    ) -> None:
        candidates = ExistingWordPressProvider.registered_taxonomy_candidates(
            {"barkeeper": ["Joao"]}
        )

        self.assertEqual(candidates, {"barkeeper": ["João"]})

    def test_media_taxonomies_match_only_terms_visible_in_metadata(self) -> None:
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Event"),
            taxonomies={
                "cocktails": ["Mojito", "Negroni"],
                "barkeeper": ["Florent"],
            },
            media_taxonomies=["cocktails", "barkeeper"],
        )

        matched = ExistingWordPressProvider._media_taxonomy_ids(
            {
                "image_alt": "Ein Negroni auf der mobilen Bar",
                "image_analysis": {"main_subject": "Negroni Cocktail"},
            },
            payload=payload,
            taxonomy_ids={
                "cocktails": [11, 12],
                "barkeeper": [21],
            },
        )

        self.assertEqual(
            matched,
            {
                "cocktails": [12],
                "barkeeper": [],
            },
        )

    def test_structured_visible_terms_override_prose_matching(self) -> None:
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Event"),
            taxonomies={"cocktails": ["Mojito", "Negroni"]},
            media_taxonomies=["cocktails"],
        )

        matched = ExistingWordPressProvider._media_taxonomy_ids(
            {
                "image_alt": "Ein Negroni und ein Mojito",
                "visible_taxonomy_terms": {"cocktails": ["Mojito"]},
            },
            payload=payload,
            taxonomy_ids={"cocktails": [11, 12]},
        )

        self.assertEqual(matched, {"cocktails": [11]})

    def test_structured_visible_terms_match_accent_variants(self) -> None:
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Event"),
            taxonomies={"barkeeper": ["Joao"]},
            media_taxonomies=["barkeeper"],
        )

        matched = ExistingWordPressProvider._media_taxonomy_ids(
            {"visible_taxonomy_terms": {"barkeeper": ["João"]}},
            payload=payload,
            taxonomy_ids={"barkeeper": [77]},
        )

        self.assertEqual(matched, {"barkeeper": [77]})

    @patch(
        "backend.app.providers.step_03_wordpress.taxonomy_terms_endpoint",
        return_value="/wp-json/wp/v2/cocktails",
    )
    @patch(
        "backend.app.providers.step_03_wordpress.registered_terms",
        return_value=[{"id": 90, "name": "Mojito", "slug": "mojito"}],
    )
    def test_missing_custom_taxonomy_term_is_never_created(
        self,
        _registered_terms,
        _taxonomy_endpoint,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "automatic term creation is disabled",
        ):
            ExistingWordPressProvider._taxonomy_term_ids(
                "cocktails",
                ["Unknown cocktail"],
            )

    @patch(
        "backend.app.providers.step_03_wordpress.taxonomy_terms_endpoint",
        return_value="/wp-json/wp/v2/barkeepers",
    )
    @patch("backend.app.providers.step_03_wordpress.update_media_metadata")
    @patch("backend.app.providers.step_03_wordpress.upload_media")
    @patch(
        "backend.app.providers.step_03_wordpress.registered_terms",
        return_value=[{"id": 44, "name": "Florent", "slug": "florent"}],
    )
    @patch("backend.app.providers.step_03_wordpress.request_json")
    def test_publish_assigns_configured_taxonomy_to_post_and_media(
        self,
        request_json,
        _registered_terms,
        upload_media_mock,
        _update_metadata,
        _taxonomy_endpoint,
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
                "video_title": "Florent",
            }],
        )

        result = ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
        )

        self.assertEqual(
            request_json.call_args_list[1].kwargs["json"]["barkeeper"],
            [44],
        )
        self.assertEqual(
            request_json.call_args_list[2].kwargs["json"],
            {"post": 123, "barkeeper": [44]},
        )
        self.assertEqual(result["taxonomy_terms"], {"barkeeper": [44]})

    @patch(
        "backend.app.providers.step_03_wordpress.taxonomy_terms_endpoint",
        return_value="/wp-json/wp/v2/barkeepers",
    )
    @patch(
        "backend.app.providers.step_03_wordpress.registered_terms",
        return_value=[{"id": 44, "name": "Florent", "slug": "florent"}],
    )
    @patch("backend.app.providers.step_03_wordpress.request_json")
    def test_partial_update_applies_taxonomies_to_existing_session_media(
        self,
        request_json,
        _registered_terms,
        _taxonomy_endpoint,
    ) -> None:
        request_json.side_effect = [
            {
                "schema": {
                    "properties": {
                        "barkeeper": {},
                        "acf": {"properties": {}},
                        "meta": {"properties": {}},
                    }
                }
            },
            {
                "id": 123,
                "status": "draft",
                "link": "https://example.test/florent/",
            },
            {},
        ]
        session = ContentSession(
            session_id="session-1",
            user_id="user-1",
            post_type_key="bartender",
            wordpress_post_type="post",
            state="publishing",
            workbook_hash="hash",
            language="de-DE",
            approval=Approval(approved=True),
            wordpress_result={
                "post_id": 123,
                "media": [{
                    "media_id": 202,
                    "image_usage": "featured",
                    "image_alt": "Florent mixt einen Cocktail",
                }],
            },
        )
        payload = WordPressPayload(
            wordpress=WordPressFields(title="Florent"),
            taxonomies={"barkeeper": ["Florent"]},
            media_taxonomies=["barkeeper"],
        )

        ExistingWordPressProvider().publish(
            session=session,
            payload=payload,
            idempotency_key="key-1",
            target_post_id=123,
            partial_update_fields={
                "wordpress": {"title"},
                "meta": set(),
                "acf": set(),
            },
        )

        self.assertEqual(
            request_json.call_args_list[2].args[:2],
            ("POST", "/wp-json/wp/v2/media/202"),
        )
        self.assertEqual(
            request_json.call_args_list[2].kwargs["json"],
            {"post": 123, "barkeeper": [44]},
        )

    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids", return_value=[20])
    @patch("backend.app.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("backend.app.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("backend.app.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("backend.app.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("backend.app.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.upload_media")
    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids")
    @patch("backend.app.providers.step_03_wordpress.find_term")
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.update_media_metadata")
    @patch("backend.app.providers.step_03_wordpress.upload_media")
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.update_media_metadata")
    @patch("backend.app.providers.step_03_wordpress.upload_media")
    @patch("backend.app.providers.step_03_wordpress.request_json")
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

    @patch("backend.app.providers.step_03_wordpress.update_media_metadata")
    @patch("backend.app.providers.step_03_wordpress.upload_media")
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

    @patch("backend.app.providers.step_03_wordpress.resolve_tag_ids", return_value=[])
    @patch("backend.app.providers.step_03_wordpress.find_term", return_value={"id": 10})
    @patch("backend.app.providers.step_03_wordpress.request_json")
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
