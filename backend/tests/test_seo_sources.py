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
            if "tax-advice" in str(params.get("slug", "")).split(","):
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

    def test_many_urls_use_one_request_per_type(self):
        self.session.calls.clear()
        found = self.scanner.find_by_urls(
            ["https://a.example/tax-advice", "https://a.example/missing", "https://a.example/x/"]
        )
        self.assertEqual(found["https://a.example/tax-advice"].wp_id, 7)
        self.assertIsNone(found["https://a.example/missing"])
        slug_calls = [c for c in self.session.calls if "slug" in c[1]]
        self.assertEqual(len(slug_calls), 3)  # post, workshop, page; media is not viewable
        self.assertEqual(sum(1 for c in self.session.calls if c[0].endswith("/types")), 1)

    def test_http_error_is_reported(self):
        self.session.get = lambda *a, **k: FakeResponse({}, 401)
        with self.assertRaises(RuntimeError):
            self.scanner.scan_collection("post")

    def test_credentials_are_required(self):
        with self.assertRaises(ValueError):
            WordPressSiteScanner("", "", "")


class FakeSearchConsole:
    """Answers by date window: the current 3 months, then the 3 months before."""

    def __init__(self):
        self.bodies = []

    def post(self, url, json=None, timeout=None):
        self.bodies.append(json)
        if json["startDate"] >= "2026-08-14":  # current window
            rows = [
                {"keys": ["pottery"], "clicks": 5, "impressions": 70},
                {"keys": ["glaze"], "clicks": 1, "impressions": 4},
                {"keys": ["kiln"], "clicks": 0, "impressions": 9},
            ]
        else:
            rows = [{"keys": ["pottery"], "clicks": 2, "impressions": 30},
                    {"keys": ["kiln"], "clicks": 3, "impressions": 3}]
        return FakeResponse({"rows": rows})


class SearchConsoleProviderTests(unittest.TestCase):
    def test_three_month_totals_with_change_versus_previous_three_months(self):
        session = FakeSearchConsole()
        provider = SearchConsoleProvider("https://example.com/", "key.json", session=session)
        stats = {s.query: s for s in provider.period_queries(today=date(2026, 11, 13))}
        self.assertEqual(
            [(b["startDate"], b["endDate"]) for b in session.bodies],
            [("2026-08-14", "2026-11-13"), ("2026-05-14", "2026-08-13")],
        )
        self.assertEqual({b["rowLimit"] for b in session.bodies}, {25000})
        self.assertEqual(stats["pottery"].period, "2026-08-14..2026-11-13")
        self.assertEqual((stats["pottery"].clicks, stats["pottery"].impressions), (5, 70))
        self.assertEqual(stats["pottery"].clicks_delta, 3)
        self.assertEqual(stats["glaze"].clicks_delta, 1)  # absent before counts as 0
        self.assertEqual(stats["kiln"].clicks_delta, -3)

    def test_month_end_dates_do_not_overflow(self):
        from backend.app.providers.step_04_seo_sources import _months_before

        self.assertEqual(_months_before(date(2026, 5, 31), 3), date(2026, 2, 28))
        self.assertEqual(_months_before(date(2026, 1, 15), 3), date(2025, 10, 15))

    def test_error_status_raises(self):
        session = FakeSearchConsole()
        session.post = lambda *a, **k: FakeResponse({}, 403)
        provider = SearchConsoleProvider("https://example.com/", "key.json", session=session)
        with self.assertRaises(RuntimeError):
            provider.period_queries(today=date(2026, 11, 13))


if __name__ == "__main__":
    unittest.main()


class YoastScoreTests(unittest.TestCase):
    def test_stored_scores_are_numbers_or_none(self):
        class Session:
            def get(self, url, params=None, headers=None, timeout=None):
                if url.endswith("/types"):
                    return FakeResponse({"post": {"slug": "post", "rest_base": "posts"}})
                return FakeResponse({"status": "draft", "meta": {
                    "_yoast_wpseo_linkdex": "75", "_yoast_wpseo_content_score": "0",
                    "_yoast_wpseo_focuskw": "pottery class"}})

        scanner = WordPressSiteScanner("https://a.example", "u", "p", session=Session())
        scores = scanner.yoast_scores("post", 5)
        self.assertEqual((scores["seo"], scores["readability"]), (75, None))
        self.assertEqual(scores["focus_keyphrase"], "pottery class")
