from __future__ import annotations

import asyncio
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config
from backend import main as backend_main
from backend.app.api import step_03_container


def client_record(client_id: str, import_key: str) -> dict[str, object]:
    return {
        "name": client_id.upper(),
        "country": "DE",
        "language": "de-DE",
        "import_api_key": import_key,
        "wordpress": {
            "base_url": f"https://{client_id}.example",
            "username": f"{client_id}-user",
            "app_password": f"{client_id}-password",
        },
        "storage": {
            "session_prefix": f"clients/{client_id}/v2-sessions",
            "knowledge_workbook": f"clients/{client_id}/knowledge/current.xlsm",
        },
    }


class ClientConfigurationTests(unittest.TestCase):
    def load(self, records: dict[str, object]):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clients.json"
            path.write_text(json.dumps(records), encoding="utf-8")
            with patch.object(config, "CLIENT_CONFIG_PATHS", (path,)):
                return config._load_clients()

    def test_clients_file_loads_multiple_isolated_clients(self) -> None:
        clients, path = self.load({
            "alpha": client_record("alpha", "alpha-key"),
            "beta": client_record("beta", "beta-key"),
        })

        self.assertIsNotNone(path)
        self.assertEqual(set(clients), {"alpha", "beta"})
        self.assertEqual(clients["beta"].session_prefix, "clients/beta/v2-sessions")
        self.assertEqual(clients["beta"].wp_username, "beta-user")

    def test_duplicate_import_keys_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Duplicate import_api_key"):
            self.load({
                "alpha": client_record("alpha", "same-key"),
                "beta": client_record("beta", "same-key"),
            })

    def test_client_paths_use_global_buckets_and_relative_client_paths(self) -> None:
        acme = config.WordPressClientConfig(
            client_id="acme",
            name="ACME",
            country="DE",
            language="de-DE",
            import_api_key="acme-key",
            wp_base_url="https://acme.example",
            wp_username="acme-user",
            wp_app_password="acme-password",
            session_prefix="clients/acme/v2-sessions",
            knowledge_workbook="clients/acme/knowledge/current.xlsm",
        )
        with (
            patch.dict(config.CLIENTS, {"acme": acme}, clear=True),
            patch.object(step_03_container, "GCS_DATA_BUCKET", "project-speech2post-data"),
            patch.object(
                step_03_container,
                "GCS_KNOWLEDGE_BUCKET",
                "project-speech2post-knowledge",
            ),
        ):
            self.assertEqual(
                step_03_container.client_session_gcs_prefix("acme"),
                "gs://project-speech2post-data/clients/acme/v2-sessions",
            )
            self.assertEqual(
                step_03_container.client_knowledge_gcs_uri("acme"),
                "gs://project-speech2post-knowledge/clients/acme/knowledge/current.xlsm",
            )

    def test_import_key_resolves_client_and_uses_client_storage_paths(self) -> None:
        clients, _ = self.load({
            "alpha": client_record("alpha", "alpha-key"),
            "beta": client_record("beta", "beta-key"),
        })
        with (
            patch.dict(config.CLIENTS, clients, clear=True),
            patch.object(step_03_container, "GCS_DATA_BUCKET", "project-speech2post-data"),
            patch.object(
                step_03_container,
                "GCS_KNOWLEDGE_BUCKET",
                "project-speech2post-knowledge",
            ),
        ):
            resolved = config.client_from_import_key("beta-key")
            self.assertIsNotNone(resolved)
            self.assertEqual(resolved.client_id, "beta")
            self.assertEqual(
                step_03_container.client_session_gcs_prefix("beta"),
                "gs://project-speech2post-data/clients/beta/v2-sessions",
            )
            self.assertEqual(
                step_03_container.client_knowledge_gcs_uri("beta"),
                "gs://project-speech2post-knowledge/clients/beta/knowledge/current.xlsm",
            )

    def test_verify_api_key_sets_active_client_from_header(self) -> None:
        clients, _ = self.load({
            "alpha": client_record("alpha", "alpha-key"),
            "beta": client_record("beta", "beta-key"),
        })
        with patch.dict(config.CLIENTS, clients, clear=True):
            async def run() -> None:
                client = await backend_main.verify_api_key("beta-key")
                self.assertEqual(client.client_id, "beta")
                self.assertEqual(config.get_active_client_id(), "beta")

            asyncio.run(run())

    def test_gcs_buckets_are_inferred_from_google_cloud_project(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "demo-project"}, clear=False):
            reloaded = importlib.reload(config)
            self.assertEqual(reloaded.GCS_DATA_BUCKET, "demo-project-speech2post-data")
            self.assertEqual(reloaded.GCS_KNOWLEDGE_BUCKET, "demo-project-speech2post-knowledge")
            importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
