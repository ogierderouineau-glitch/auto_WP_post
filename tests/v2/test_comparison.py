from __future__ import annotations

import unittest

from tools.v2_compare_payloads import compare


class ComparisonTests(unittest.TestCase):
    def test_comparison_allows_different_text_but_requires_destinations(self) -> None:
        v1 = {
            "title": "Old title",
            "slug": "event",
            "excerpt": "Old excerpt",
            "meta": {
                "yoast_wpseo_title": "Old SEO",
                "yoast_wpseo_metadesc": "Old description",
            },
            "acf": {
                "hero_h1": "Old hero",
                "verlauf_h2": "Old flow",
                "related_links_html": "",
            },
        }
        v2 = {
            "wordpress": {
                "title": "New title",
                "slug": "event-v2",
                "excerpt": "New excerpt",
            },
            "meta": {
                "yoast_wpseo_title": "New SEO",
                "yoast_wpseo_metadesc": "New description",
            },
            "acf": {
                "hero_h1": "New hero",
                "verlauf_h2": "New flow",
                "related_links_html": "",
            },
        }
        report = compare(v1, v2)
        self.assertTrue(report["pass"])
        self.assertTrue(any(not row["identical"] for row in report["rows"]))
