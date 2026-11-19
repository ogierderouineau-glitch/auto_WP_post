import unittest
from unittest.mock import patch

from backend.wordpress_api import find_linked_posts


def post(post_id: int, title: str) -> dict:
    return {"id": post_id, "title": {"rendered": title}}


class FindLinkedPostsTests(unittest.TestCase):
    @patch("backend.wordpress_api.request_json")
    def test_title_match_prefers_exact_over_first_name(self, request_json) -> None:
        request_json.return_value = [post(1, "Markus Müller"), post(2, "Markus")]
        self.assertEqual([m["id"] for m in find_linked_posts({"rest_base": "posts"}, "Markus")[0]], [2])

    @patch("backend.wordpress_api.request_json")
    def test_first_name_matches_title_ignoring_accents_and_entities(self, request_json) -> None:
        request_json.return_value = [post(3, "Jo&#227;o Silva"), post(4, "Joaquin")]
        self.assertEqual([m["id"] for m in find_linked_posts({"rest_base": "posts"}, "João")[0]], [3])

    @staticmethod
    def wordpress(posts_by_collection: dict[str, list[dict]]):
        """Fake request_json: the post-type registry plus the post collections."""
        types = {"post": {"rest_base": "posts"}, "location": {"rest_base": "locations"}, "attachment": {"rest_base": "media"}}

        def respond(method, path, **kwargs):
            if path.endswith("/types"):
                return types
            return posts_by_collection.get(path.rsplit("/", 1)[-1], [])

        return respond

    def lookup(self, spec, name, posts_by_collection, *, term_types=("post", "attachment"), terms=None, category=None):
        terms = [{"id": 44, "name": "João", "slug": "joao"}] if terms is None else terms
        with patch("backend.wordpress_api.request_json", side_effect=self.wordpress(posts_by_collection)) as request_json, \
             patch("backend.wordpress_api.taxonomy_definition", return_value={"types": list(term_types)}), \
             patch("backend.wordpress_api.taxonomy_terms_endpoint", return_value="/wp-json/wp/v2/barkeeper"), \
             patch("backend.wordpress_api.registered_terms", return_value=terms), \
             patch("backend.wordpress_api.find_term", return_value=category):
            return find_linked_posts(spec, name), request_json

    def test_taxonomy_term_and_category_select_the_profile(self) -> None:
        spec = {"taxonomy": "barkeeper", "category": "auto bartender post"}
        (posts, reason), request_json = self.lookup(
            spec, "Joao", {"posts": [post(9, "Showbartender in Hannover buchen – João")]}, category={"id": 7}
        )
        self.assertEqual(([m["id"] for m in posts], reason), ([9], ""))
        params = request_json.call_args.kwargs["params"]
        self.assertEqual((params["categories"], params["barkeeper"]), (7, 44))
        self.assertNotIn("search", params)

    def test_several_posts_with_the_term_narrow_to_the_one_titled_with_the_name(self) -> None:
        both = {"posts": [post(1, "Ana Silva"), post(2, "Garden party in Lyon")]}
        (posts, _), _ = self.lookup({"taxonomy": "barkeeper"}, "Ana", both, terms=[{"id": 5, "name": "Ana", "slug": "ana"}])
        self.assertEqual([m["id"] for m in posts], [1])

    def test_several_posts_without_a_title_match_are_all_kept(self) -> None:
        both = {"posts": [post(1, "Roof party in Rome"), post(2, "Garden party in Lyon")]}
        (posts, _), _ = self.lookup({"taxonomy": "barkeeper"}, "Ana", both, terms=[{"id": 5, "name": "Ana", "slug": "ana"}])
        self.assertEqual([m["id"] for m in posts], [1, 2])

    def test_posts_of_the_published_kind_are_excluded(self) -> None:
        spec = {"taxonomy": "barkeeper", "exclude_category": "auto video post"}
        (posts, _), request_json = self.lookup(spec, "João", {"posts": [post(8, "Dampf-Highlight")]}, category={"id": 3})
        self.assertEqual([m["id"] for m in posts], [8])
        params = request_json.call_args.kwargs["params"]
        self.assertEqual((params["categories_exclude"], params["barkeeper"]), (3, 44))
        self.assertNotIn("categories", params)

    def test_post_types_come_from_the_taxonomy_and_skip_attachments(self) -> None:
        # The taxonomy belongs to a custom post type: "posts" must not be the only place searched.
        (posts, _), _ = self.lookup(
            {"taxonomy": "barkeeper"}, "João",
            {"locations": [post(20, "Engelnest Berlin")], "posts": []},
            term_types=("location", "attachment"),
        )
        self.assertEqual([m["id"] for m in posts], [20])

    def test_reason_tells_which_step_found_nothing(self) -> None:
        (posts, reason), _ = self.lookup({"taxonomy": "barkeeper"}, "Zed", {}, terms=[])
        self.assertEqual((posts, reason), ([], "no term 'Zed' in taxonomy 'barkeeper'"))
        (posts, reason), _ = self.lookup({"taxonomy": "barkeeper"}, "João", {"posts": []})
        self.assertEqual((posts, reason), ([], "term found, but no published post in 'posts' carries it"))

    @patch("backend.wordpress_api.request_json")
    def test_rest_base_in_the_rule_overrides_the_taxonomy_post_types(self, request_json) -> None:
        request_json.return_value = [post(1, "Ana")]
        posts, _ = find_linked_posts({"rest_base": "team"}, "Ana")
        self.assertEqual(request_json.call_args.args[1], "/wp-json/wp/v2/team")
        self.assertEqual(len(posts), 1)
