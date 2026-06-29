from __future__ import annotations

import unittest

from tools.v2_live_generation_smoke import (
    CONFIRMED_FACTS,
    SYNTHETIC_EVENT,
    generation_invariant_errors,
)


class LiveSmokeToolTests(unittest.TestCase):
    def test_fixture_is_explicitly_synthetic_and_complete(self) -> None:
        self.assertIn("synthetische Testdaten", SYNTHETIC_EVENT)
        for value in ("24.06.2026", "Berlin", "120", "Cocktailcatering", "company"):
            self.assertIn(value, SYNTHETIC_EVENT)
        self.assertEqual(CONFIRMED_FACTS["event_date"], "24.06.2026")

    def test_generation_invariants_accept_confirmed_facts_only(self) -> None:
        report = {
            "acf_source_field_keys": ["fact_date", "event_story"],
            "payload": {
                "acf": {
                    "fakten": "<ul><li><strong>Datum:</strong> 24.06.2026</li></ul>"
                }
            },
        }
        self.assertEqual(generation_invariant_errors(report), [])

    def test_generation_invariants_reject_optional_fact_leakage(self) -> None:
        report = {
            "acf_source_field_keys": ["fact_date", "fact_bartender", "event_challenge"],
            "payload": {
                "acf": {
                    "fakten": (
                        "&lt;li&gt;<strong>Datum:</strong> 20.06.2026 "
                        "<strong>Barkeeper:</strong> Team von FLAIRLAB"
                    )
                }
            },
        }
        errors = generation_invariant_errors(report)
        self.assertTrue(any("optional fields" in item for item in errors))
        self.assertTrue(any("confirmed event date" in item for item in errors))
        self.assertTrue(any("escaped list markup" in item for item in errors))
        self.assertTrue(any("Barkeeper:" in item for item in errors))
