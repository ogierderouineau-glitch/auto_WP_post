from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from io import BytesIO

import httpx
from fastapi import FastAPI
from PIL import Image

from app.v2.api.step_02_routes import create_router, v2_error_handler
from app.v2.errors import V2Error
from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.sessions.step_03_service import ContentSessionService
from app.v2.storage.step_01_local import LocalObjectStorageProvider

WORKBOOK = Path(
    os.getenv(
        "V2_TEST_WORKBOOK",
        "/home/ogier-derouineau/Downloads/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm",
    )
)


@unittest.skipUnless(WORKBOOK.is_file(), f"V2 test workbook not found: {WORKBOOK}")
class ApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        service = ContentSessionService(
            knowledge=KnowledgeBaseService(WORKBOOK),
            repository=FileSessionRepository(self.temporary.name),
            object_storage=LocalObjectStorageProvider(Path(self.temporary.name) / "objects"),
        )
        app = FastAPI()
        app.add_exception_handler(V2Error, v2_error_handler)
        app.include_router(
            create_router(
                lambda: service,
                readiness_provider=lambda: {
                    "ready": True,
                    "providers": {"object_storage": True},
                },
            )
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-User-ID": "user-1"},
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.temporary.cleanup()

    async def test_create_and_get_session(self) -> None:
        created = await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )
        self.assertEqual(created.status_code, 201)
        session = created.json()["session"]
        self.assertEqual(session["state"], "created")
        fetched = await self.client.get(f"/api/content-sessions/{session['session_id']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["session"]["workbook_hash"], session["workbook_hash"])

    async def test_save_inputs_after_session_creation(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        response = await self.client.post(
            f"/api/content-sessions/{created['session_id']}/inputs",
            json={
                "expected_version": created["version"],
                "manual_text": "Synthetischer Eventtext.",
                "confirmed_facts": {"city": "Berlin"},
            },
        )
        self.assertEqual(response.status_code, 200)
        session = response.json()["session"]
        self.assertEqual(session["state"], "uploading")
        self.assertEqual(session["manual_text"], "Synthetischer Eventtext.")
        self.assertEqual(session["confirmed_facts"]["city"]["value"], "Berlin")
        self.assertTrue(session["confirmed_facts"]["city"]["confirmed"])

    async def test_recent_sessions_and_delete_use_v2_repository(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        recent = await self.client.get("/api/content-sessions/recent?limit=10")
        self.assertEqual(recent.status_code, 200)
        sessions = recent.json()["sessions"]
        self.assertTrue(any(item["session_id"] == created["session_id"] for item in sessions))
        self.assertEqual(sessions[0]["storage"], "v2")

        deleted = await self.client.post(
            "/api/content-sessions/delete",
            json={"session_ids": [created["session_id"]]},
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted"], 1)
        missing = await self.client.get(f"/api/content-sessions/{created['session_id']}")
        self.assertEqual(missing.status_code, 404)

    async def test_generate_job_start_returns_before_generation_result(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        response = await self.client.post(
            f"/api/content-sessions/{created['session_id']}/generate-job",
            json={
                "expected_version": created["version"],
                "shared_fields": {},
                "acf_source_fields": {},
                "selected_links": [],
                "current_url": None,
            },
        )
        self.assertEqual(response.status_code, 200)
        job = response.json()
        self.assertEqual(job["session_id"], created["session_id"])
        self.assertEqual(job["operation"], "generate")
        self.assertIn(job["status"], {"queued", "running", "failed", "complete"})
        polled = await self.client.get(f"/api/content-sessions/jobs/{job['job_id']}")
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["job_id"], job["job_id"])

    async def test_workbook_status_exposes_version_hash(self) -> None:
        response = await self.client.get("/api/content-sessions/_workbook")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["sha256"],
            "6db9ba5d8ff8a43d20d8749076e33c9908a69d4a9b046bd95124671d7baac040",
        )

    async def test_workbook_status_exposes_legacy_acf_mapping(self) -> None:
        response = await self.client.get("/api/content-sessions/_workbook")
        self.assertEqual(response.status_code, 200)
        mapping = response.json()["acf_guidance_list"]
        hero = next(item for item in mapping if item["user_field"] == "hero_h1")
        self.assertEqual(hero["acf_field"], "hero_h1")
        self.assertEqual(hero["acf_field_name"], "hero_h1")
        self.assertTrue(hero["guidance"])
        self.assertTrue(
            any(item["user_field"] == "event_story" for item in mapping),
        )

    async def test_readiness_endpoint_is_typed_and_non_secret(self) -> None:
        response = await self.client.get("/api/content-sessions/_readiness")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertNotIn("api_key", response.text.lower())

    async def test_valid_image_upload_is_stored(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        buffer = BytesIO()
        Image.new("RGB", (32, 32), "red").save(buffer, format="PNG")
        response = await self.client.post(
            f"/api/content-sessions/{created['session_id']}/uploads",
            data={
                "expected_version": str(created["version"]),
                "kind": "image",
            },
            files={"upload": ("photo.png", buffer.getvalue(), "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        images = response.json()["session"]["image_refs"]
        self.assertEqual(len(images), 1)
        self.assertTrue(Path(images[0]["storage_uri"]).is_file())

    async def test_invalid_image_upload_returns_stable_error(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        response = await self.client.post(
            f"/api/content-sessions/{created['session_id']}/uploads",
            data={
                "expected_version": str(created["version"]),
                "kind": "image",
            },
            files={"upload": ("photo.png", b"not-an-image", "image/png")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "invalid_upload")

    async def test_oversized_upload_returns_stable_error(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        with patch.dict(os.environ, {"V2_MAX_AUDIO_BYTES": "2"}):
            response = await self.client.post(
                f"/api/content-sessions/{created['session_id']}/uploads",
                data={
                    "expected_version": str(created["version"]),
                    "kind": "audio",
                },
                files={"upload": ("voice.mp3", b"too large", "audio/mpeg")},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "invalid_upload")

    async def test_unknown_post_type_returns_stable_error(self) -> None:
        response = await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "unknown"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "unknown_post_type")

    async def test_session_owner_is_enforced(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        response = await self.client.get(
            f"/api/content-sessions/{created['session_id']}",
            headers={"X-User-ID": "other-user"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error_code"], "session_ownership_mismatch")

    async def test_create_rejects_mismatched_user_header(self) -> None:
        response = await self.client.post(
            "/api/content-sessions",
            headers={"X-User-ID": "other-user"},
            json={"user_id": "user-1", "post_type_key": "event"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error_code"], "session_ownership_mismatch")

    async def test_invalid_transition_returns_conflict(self) -> None:
        created = (await self.client.post(
            "/api/content-sessions",
            json={"user_id": "user-1", "post_type_key": "event"},
        )).json()["session"]
        response = await self.client.post(
            f"/api/content-sessions/{created['session_id']}/approve",
            json={"expected_version": created["version"], "user_id": "user-1"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "invalid_state_transition")
