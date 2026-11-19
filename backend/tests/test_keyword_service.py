import unittest

from backend.app.keywords.step_01_models import (
    KeywordCandidate,
    KeywordProposalOutput,
    normalize_phrase,
)
from backend.app.keywords.step_02_service import KeywordService
from backend.app.providers.step_04_seo_sources import QueryStat, SiteEntry


def entry(slug, focus="", post_type="treatment"):
    return SiteEntry(1, post_type, slug, slug.title(), f"https://clinic.example/{slug}/", focus)


class Recorder:
    """Stands in for the session service's structured call."""

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return KeywordProposalOutput(candidates=self.candidates)


def run(candidates, entries=(), stats=()):
    recorder = Recorder(candidates)
    rows = KeywordService(recorder).propose(
        facts={"treatment": "root canal"},
        language="en",
        post_type_name="Treatment",
        entries=list(entries),
        stats=list(stats),
    )
    return rows, recorder


def candidate(keyword, status="free", refs=(), alternatives=()):
    return KeywordCandidate(
        keyword=keyword, alternatives=list(alternatives), status=status,
        related_refs=list(refs), rationale="because",
    )


class MeasureTests(unittest.TestCase):
    def setUp(self):
        from backend.app.keywords.step_04_measure import measure

        self.measure = measure

    def stats(self):
        rows = [("smoothie bikes", 1, 2), ("smoothie fahrrad mieten", 2, 50), ("fahrrad mieten berlin", 1, 90),
                ("mobile bar berlin", 3, 80), ("cocktailbar berlin", 2, 70)]
        # many unrelated "berlin" queries make that word too common to link phrases on its own
        rows += [(f"filler berlin {i}", 0, 1) for i in range(60)]
        return [QueryStat(q, "p", c, i, 0) for q, c, i in rows]

    def test_related_queries_share_meaningful_words_ranked_by_views(self):
        result = self.measure("Smoothie-Fahrrad", self.stats())
        self.assertIsNone(result.clicks)  # no exact query
        self.assertEqual([r.query for r in result.related_searches],
                         ["fahrrad mieten berlin", "smoothie fahrrad mieten", "smoothie bikes"])

    def test_a_very_common_word_alone_does_not_make_queries_related(self):
        result = self.measure("Showbarkeeper Berlin", self.stats())
        self.assertEqual(result.related_searches, [])

    def test_exact_match_ignores_spacing_and_is_not_repeated_as_related(self):
        result = self.measure("Mobile-Bar Berlin", [QueryStat("mobile bar berlin", "p", 3, 80, 1)])
        self.assertEqual((result.clicks, result.impressions, result.clicks_delta), (3, 80, 1))
        self.assertEqual(result.related_searches, [])


class NormalizeTests(unittest.TestCase):
    def test_compounds_hyphens_and_case_match(self):
        self.assertEqual(normalize_phrase("Kaffee-Catering"), normalize_phrase("kaffeecatering"))
        self.assertNotEqual(normalize_phrase("root canal"), normalize_phrase("root canals"))


class KeywordServiceTests(unittest.TestCase):
    def test_exact_focus_keyphrase_overrides_model_status(self):
        pages = [entry("endodontics", focus="Root Canal")]
        rows, _ = run([candidate("root canal", status="free")], pages)
        self.assertEqual(rows[0].status, "focus_elsewhere")
        self.assertEqual(rows[0].related_urls, ["https://clinic.example/endodontics/"])

    def test_unsupported_focus_claim_is_downgraded_and_unknown_refs_dropped(self):
        pages = [entry("whitening")]
        rows, _ = run([candidate("tooth bleaching", "focus_elsewhere", refs=["p1", "p99"])], pages)
        self.assertEqual(rows[0].status, "mentioned_elsewhere")
        self.assertEqual(rows[0].related_urls, ["https://clinic.example/whitening/"])
        rows, _ = run([candidate("tooth bleaching", "focus_elsewhere", refs=["p99"])], pages)
        self.assertEqual((rows[0].status, rows[0].related_urls), ("free", []))

    def test_search_console_numbers_come_from_data_not_model(self):
        stats = [QueryStat("root-canal", "2026-08-14..2026-11-13", 5, 60, 3)]
        rows, _ = run([candidate("Root canal"), candidate("invisible braces")], stats=stats)
        self.assertEqual(
            (rows[0].clicks, rows[0].impressions, rows[0].clicks_delta, rows[0].period),
            (5, 60, 3, "2026-08-14..2026-11-13"),
        )
        self.assertIsNone(rows[1].clicks)  # no measurement: still proposed

    def test_queries_differing_only_in_spacing_are_added_up(self):
        stats = [
            QueryStat("root canal", "p", 2, 20, 1),
            QueryStat("rootcanal", "p", 1, 5, 0),
        ]
        rows, _ = run([candidate("Root-Canal")], stats=stats)
        self.assertEqual((rows[0].clicks, rows[0].impressions, rows[0].clicks_delta), (3, 25, 1))

    def test_blank_and_duplicate_keywords_removed_and_capped(self):
        many = [candidate(f"term {i}") for i in range(20)]
        rows, _ = run([candidate(" "), candidate("Term 0"), *many])
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({r.keyword.lower() for r in rows}), 12)

    def test_model_input_contains_refs_not_secrets(self):
        _, recorder = run([], [entry("whitening", focus="teeth whitening")])
        call = recorder.calls[0]
        self.assertEqual(call["task"], "keyword_proposal")
        self.assertIs(call["schema"], KeywordProposalOutput)
        body = call["messages"][1]["content"]
        self.assertIn('"ref": "p1"', body)
        self.assertIn("teeth whitening", body)
        self.assertIn("root canal", body)


if __name__ == "__main__":
    unittest.main()
