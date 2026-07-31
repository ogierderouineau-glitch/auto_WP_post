from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend import main as current_app


class ProductionAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_auth_fails_closed_when_required_key_is_missing(self) -> None:
        with (
            patch("backend.config.configured_import_keys", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                await current_app.verify_api_key(None)
        self.assertEqual(raised.exception.status_code, 503)

    async def test_main_auth_accepts_the_configured_key(self) -> None:
        client = current_app.config.get_client_config()
        with (
            patch("backend.config.configured_import_keys", return_value=True),
            patch("backend.config.client_from_import_key", return_value=client),
        ):
            authenticated = await current_app.verify_api_key("showcase-key")
        self.assertEqual(authenticated.client_id, client.client_id)
        self.assertEqual(authenticated.language, client.language)

    async def test_main_auth_rejects_an_unknown_key(self) -> None:
        with (
            patch("backend.config.configured_import_keys", return_value=True),
            patch("backend.config.client_from_import_key", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                await current_app.verify_api_key("wrong-key")
        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
