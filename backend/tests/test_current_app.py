from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI

from backend import config
from backend import main as backend_main
from backend.main import app, clients, lifespan
from backend.app.api.step_02_routes import create_router
from backend.app.api.step_03_container import get_v2_service
from backend.app.models.step_01_session import ContentSession
from backend.app.sessions.step_01_repository import FileSessionRepository
from backend.app.sessions.step_03_service import ContentSessionService


class CurrentAppCompositionTests(unittest.TestCase):
    def test_current_routes_are_registered(self) -> None:
        paths = set(app.openapi()["paths"])

        self.assertIn("/health", paths)
        self.assertIn("/clients", paths)
        self.assertIn("/app/knowledge/workbook", paths)
        self.assertIn("/api/content-sessions", paths)
        self.assertIn("/api/content-sessions/_workbook", paths)

    def test_retired_routes_are_not_registered(self) -> None:
        paths = set(app.openapi()["paths"])

        self.assertNotIn("/", paths)
        self.assertNotIn("/app", paths)
        self.assertNotIn("/event-posts/from-zip", paths)
        self.assertFalse(any(path.startswith("/app/sessions") for path in paths))
        self.assertFalse(any(path.startswith("/action") for path in paths))

    def test_clients_response_matches_the_frontend_contract(self) -> None:
        response = clients(config.get_client_config())

        self.assertIn("clients", response)
        self.assertTrue(response["clients"])
        self.assertIn("client_id", response["clients"][0])
        self.assertEqual(
            response["clients"][0]["name"],
            config.get_client_config().name,
        )
        self.assertEqual(
            response["clients"][0]["language"],
            config.get_client_config().language,
        )

    def test_lifespan_does_not_initialize_v2_services_on_startup(self) -> None:
        async def run() -> None:
            with patch(
                "backend.main.get_v2_service",
                side_effect=AssertionError("startup should not initialize workbook"),
            ):
                async with lifespan(None):
                    pass

        asyncio.run(run())

    def test_dev_auth_accepts_any_non_empty_key_and_uses_a_configured_client(self) -> None:
        async def run() -> None:
            with patch.dict(config.CLIENTS, {
                "flairlab": config.WordPressClientConfig(
                    client_id="flairlab",
                    name="FLAIRLAB",
                    country="DE",
                    language="de-DE",
                    import_api_key="configured-key",
                    wp_base_url="https://flairlab.example",
                    wp_username="flairlab-user",
                    wp_app_password="flairlab-password",
                    session_prefix="clients/flairlab/v2-sessions",
                    knowledge_workbook="clients/flairlab/knowledge/current.xlsm",
                )
            }, clear=True):
                with patch.dict(os.environ, {"RENDER": ""}, clear=False):
                    client = await backend_main.verify_api_key("totally-random-password")
                    self.assertEqual(client.client_id, "flairlab")
                    self.assertEqual(config.get_active_client_id(), "flairlab")

        asyncio.run(run())

    def test_authenticated_router_uses_the_active_client_for_session_creation(self) -> None:
        async def run() -> None:
            with patch.dict(config.CLIENTS, {
                "alpha": config.WordPressClientConfig(
                    client_id="alpha",
                    name="Alpha",
                    country="DE",
                    language="de-DE",
                    import_api_key="alpha-key",
                    wp_base_url="https://alpha.example",
                    wp_username="alpha-user",
                    wp_app_password="alpha-password",
                    session_prefix="clients/alpha/v2-sessions",
                    knowledge_workbook="clients/alpha/knowledge/current.xlsm",
                )
            }, clear=True):
                service = get_v2_service("alpha")
                test_app = FastAPI()
                test_app.include_router(create_router(lambda: service, backend_main.verify_api_key))
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=test_app),
                    base_url="http://testserver",
                ) as client:
                    response = await client.post(
                        "/api/content-sessions",
                        json={"user_id": "ignored", "post_type_key": "event"},
                        headers={"x-api-key": "alpha-key"},
                    )
                    self.assertEqual(response.status_code, 201)
                    session = response.json()["session"]
                    self.assertEqual(session["user_id"], "alpha")

        asyncio.run(run())

    def test_legacy_sessions_with_client_aliases_are_visible_in_recent_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config.set_active_client("flairlab")
            repository_root = Path(tmpdir) / "flairlab"
            legacy_root = Path(tmpdir)
            repository = FileSessionRepository(repository_root, extra_roots=[legacy_root])
            legacy_session = ContentSession(
                session_id="legacy-session",
                user_id="flairlab-user",
                post_type_key="event",
                state="created",
                workbook_hash="abc123",
                language="de",
            )
            repository._write(legacy_root / "legacy-session" / "state.json", legacy_session)

            service = ContentSessionService(
                knowledge=MagicMock(),
                repository=repository,
            )
            sessions = service.list_recent(user_id="flairlab", limit=5)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_id"], legacy_session.session_id)

            config.set_active_client("default")


if __name__ == "__main__":
    unittest.main()
