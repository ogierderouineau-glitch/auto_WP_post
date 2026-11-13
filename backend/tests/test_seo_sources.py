from datetime import date
import unittest

from backend.app.providers.step_04_seo_sources import (
    SearchConsoleProvider,
    WordPressSiteScanner,
)


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload, self.status_code, self.headers = payload, status, headers or {}

    def json(self):
        return self._payload


class FakeWordPress:
    """Serves two pages of 'workshop' entries, then a 400 like WordPress does."""

    def __init__(self):
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/types"):
            return FakeResponse(
                {
                    "post": {"slug": "post", "rest_base": "posts", "viewable": True},
                    "workshop": {"slug": "workshop", "rest_base": "workshops", "viewable": True},
                    "page": {"slug": "page", "rest_base": "pages", "viewable": True},
                    "media": {"slug": "attachment", "rest_base": "media", "viewable": False},
                }
            )
        if url.endswith("/categories"):
            return FakeResponse(
                [{"id": 5, "name": "Events"}, {"id": 6, "name": "auto event post"}, {"id": 8, "name": "Eventually"}]
            )
        if url.endswith("/pages"):
            if params.get("slug") == "tax-advice":
                return FakeResponse(
                    [{"id": 7, "type": "page", "slug": "tax-advice", "title": {"raw": "Tax advice"},
                      "link": "https://www.example.com/tax-advice/", "meta": {}}]
                )
            return FakeResponse([])
        if "slug" in params:
            return FakeResponse([])
        page = params["page"]
        if page > 2:
            return FakeResponse({"code": "rest_post_invalid_page_number"}, 400)
        meta = {"_yoast_wpseo_focuskw": "pottery class"} if page == 1 else {}
        return FakeResponse(
            [{"id": page, "slug": f"w-{page}", "title": {"raw": f"Workshop {page}"},
              "link": f"https://www.example.com/w-{page}/", "meta": meta}],
            headers={"X-WP-TotalPages": "2"},
        )


class SynonymTests(unittest.TestCase):
    def test_json_list_is_flattened_and_blanks_dropped(self):
        from backend.app.providers.step_04_seo_sources import _synonyms
        self.assertEqual(_synonyms('["mobile Bar Berlin",""]'), "mobile Bar Berlin")
        self.assertEqual(_synonyms("plain text"), "plain text")
        self.assertEqual(_synonyms(""), "")


class WordPressSiteScannerTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeWordPress()
        self.scanner = WordPressSiteScanner(
            "https://www.example.com/", "user", "secret", session=self.session
        )

    def test_scan_follows_pagination_and_prefers_yoast_keyphrase(self):
        entries = self.scanner.scan_collection("workshop")
        self.assertEqual([entry.slug for entry in entries], ["w-1", "w-2"])
        self.assertEqual(entries[0].source, "yoast")
        self.assertEqual(entries[0].focus_keyphrase, "pottery class")
        self.assertEqual(entries[1].source, "slug_title")
        self.assertTrue(self.session.calls[1][0].endswith("/workshops"))

    def test_post_type_post_uses_posts_collection(self):
        self.scanner.scan_collection("post")
        self.assertTrue(self.session.calls[1][0].endswith("/posts"))

    def test_category_filter_and_lookup(self):
        self.scanner.scan_collection("post", category_ids=[5, 9])
        self.assertEqual(self.session.calls[-1][1]["categories"], "5,9")

    def test_category_ids_match_name_exactly_ignoring_case(self):
        self.assertEqual(self.scanner.category_ids("events", "AUTO EVENT POST"), [5, 6])
        self.assertEqual(self.scanner.category_ids("event"), [])

    def test_pages_use_their_plural_rest_base(self):
        self.scanner.scan_collection("page")
        self.assertTrue(self.session.calls[1][0].endswith("/pages"))

    def test_find_by_url_skips_non_viewable_types(self):
        entry = self.scanner.find_by_url("https://staging.example.com/tax-advice")
        self.assertEqual((entry.wp_id, entry.post_type), (7, "page"))
        self.assertFalse(any(url.endswith("/media") for url, _ in self.session.calls))
        self.assertIsNone(self.scanner.find_by_url("https://example.com/unknown"))

    def test_http_error_is_reported(self):
        self.session.get = lambda *a, **k: FakeResponse({}, 401)
        with self.assertRaises(RuntimeError):
            self.scanner.scan_collection("post")

    def test_credentials_are_required(self):
        with self.assertRaises(ValueError):
            WordPressSiteScanner("", "", "")


class FakeSearchConsole:
    def __init__(self):
        self.bodies = []

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        month = json["startDate"][:7]
        rows = {
            "2026-08": [{"keys": ["pottery"], "clicks": 2, "impressions": 10}],
            "2026-09": [{"keys": ["pottery"], "clicks": 5, "impressions": 30},
                        {"keys": ["glaze"], "clicks": 1, "impressions": 4}],
            "2026-10": [{"keys": ["pottery"], "clicks": 4, "impressions": 20}],
        }[month]
        return FakeResponse({"rows": rows})


class SearchConsoleProviderTests(unittest.TestCase):
    def test_complete_months_with_deltas(self):
        session = FakeSearchConsole()
        provider = SearchConsoleProvider("https://example.com/", "key.json", session=session)
        stats = provider.monthly_queries(today=date(2026, 11, 13))
        self.assertEqual(
            [(b["startDate"], b["endDate"]) for b in session.bodies],
            [("2026-08-01", "2026-08-31"), ("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31")],
        )
        by_key = {(s.query, s.month): s for s in stats}
        self.assertIsNone(by_key[("pottery", "2026-08")].clicks_delta)
        self.assertEqual(by_key[("pottery", "2026-09")].clicks_delta, 3)
        self.assertEqual(by_key[("glaze", "2026-09")].clicks_delta, 1)
        self.assertEqual(by_key[("pottery", "2026-10")].clicks_delta, -1)

    def test_error_status_raises(self):
        session = FakeSearchConsole()
        session.post = lambda *a, **k: FakeResponse({}, 403)
        provider = SearchConsoleProvider("https://example.com/", "key.json", session=session)
        with self.assertRaises(RuntimeError):
            provider.monthly_queries(today=date(2026, 11, 13))


if __name__ == "__main__":
    unittest.main()
