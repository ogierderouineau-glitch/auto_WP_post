from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

import app_main
from legacy import action_api_event_import


class ProductionAuthTests(unittest.TestCase):
    def test_main_auth_fails_closed_when_required_key_is_missing(self) -> None:
        with (
            patch("config.REQUIRE_IMPORT_API_KEY", True),
            patch("legacy.action_api_event_import.IMPORT_API_KEY", ""),
        ):
            with self.assertRaises(HTTPException) as raised:
                app_main.verify_api_key(None)
        self.assertEqual(raised.exception.status_code, 503)

    def test_main_auth_accepts_the_configured_key(self) -> None:
        with (
            patch("config.REQUIRE_IMPORT_API_KEY", True),
            patch("legacy.action_api_event_import.IMPORT_API_KEY", "showcase-key"),
        ):
            app_main.verify_api_key("showcase-key")

    def test_legacy_action_auth_also_fails_closed(self) -> None:
        with (
            patch.object(action_api_event_import, "REQUIRE_IMPORT_API_KEY", True),
            patch.object(action_api_event_import, "IMPORT_API_KEY", ""),
        ):
            with self.assertRaises(HTTPException) as raised:
                action_api_event_import.verify_api_key(None)
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
