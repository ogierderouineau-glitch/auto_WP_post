"""Session labels must remain optional, isolated and independent of industry schemas."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.app.api.step_02_routes import create_router, v2_error_handler
from backend.app.errors import InvalidUploadError, SessionVersionConflictError, V2Error
from backend.app.models.step_01_session import ContentSession
from backend.app.sessions.step_01_repository import FileSessionRepository
from backend.app.sessions.step_03_service import ContentSessionService
from backend.config import DEFAULT_CLIENT_ID, set_active_client


class NamingProvider:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def structured(self, *, task, context, schema):
        self.calls.append((task, json.loads(context["messages"][1]["content"])["context"]))
        if self.fail:
            raise RuntimeError("Naming unavailable")
        return schema(name="Solar battery installation") if task == "session_naming" else schema()


def service_and_session(tmp_path, provider=None, **values):
    repository = FileSessionRepository(tmp_path)
    session = repository.create(ContentSession(
        session_id="solar-session", user_id="solar-client", post_type_key="battery_case_27",
        state="ready_to_generate", workbook_hash="hash", language="en", **values,
    ))
    snapshot = SimpleNamespace(acf_fields=[], agent_instructions=[], application_states=[])
    service = ContentSessionService(
        knowledge=SimpleNamespace(by_hash=lambda _: snapshot), repository=repository,
        language_model=provider,
    )
    return service, session


def test_legacy_session_name_preserves_id_and_arbitrary_fields(tmp_path):
    provider = NamingProvider()
    service, session = service_and_session(tmp_path, provider, shared_fields={"arbitrary_heading": "Solar battery installation"})
    named = service.rename(session.session_id, name=None, expected_version=session.version)
    assert named.name == "Solar battery installation"
    assert named.session_id == session.session_id
    assert named.shared_fields == session.shared_fields
    assert service.get(session.session_id).name == named.name
    assert service.list_recent(user_id="solar-client")[0]["name"] == named.name
    assert service.list_recent(user_id="unrelated-client") == []
    service.rename(session.session_id, name=None, expected_version=named.version)
    assert len(provider.calls) == 1
    assert provider.calls[0][1]["language"] == "en"


def test_manual_name_wins_and_stale_edits_do_not_overwrite(tmp_path):
    provider = NamingProvider()
    service, session = service_and_session(tmp_path, provider, manual_text="Battery details")
    named = service.rename(session.session_id, name="  My custom   name  ", expected_version=session.version)
    assert named.name == "My custom name"
    extracted = service.analyze(session.session_id, expected_version=named.version)
    assert extracted.name == named.name
    assert extracted.facts_extracted
    assert [task for task, _ in provider.calls] == ["fact_extraction"]
    with pytest.raises(SessionVersionConflictError):
        service.rename(session.session_id, name="Stale name", expected_version=session.version)
    assert service.get(session.session_id).name == named.name
    with pytest.raises(InvalidUploadError):
        service.rename(session.session_id, name="   ", expected_version=extracted.version)


def test_first_extraction_names_once_even_with_no_extracted_values(tmp_path):
    provider = NamingProvider()
    service, session = service_and_session(tmp_path, provider, manual_text="Solar battery installation")
    first = service.analyze(session.session_id, expected_version=session.version)
    second = service.analyze(session.session_id, expected_version=first.version)
    assert first.name == second.name == "Solar battery installation"
    assert first.facts_extracted
    assert [task for task, _ in provider.calls].count("session_naming") == 1


def test_failed_naming_is_persisted_without_blocking_session(tmp_path):
    provider = NamingProvider(fail=True)
    service, session = service_and_session(tmp_path, provider, shared_fields={"custom": "Battery"})
    named = service.rename(session.session_id, name=None, expected_version=session.version)
    assert not named.name
    assert named.name_generation_attempted
    service.rename(session.session_id, name=None, expected_version=named.version)
    assert len(provider.calls) == 1
    manual = service.rename(session.session_id, name="Manual recovery", expected_version=named.version)
    assert manual.name == "Manual recovery"


def test_empty_session_waits_for_extraction(tmp_path):
    provider = NamingProvider()
    service, session = service_and_session(tmp_path, provider)
    unchanged = service.rename(session.session_id, name=None, expected_version=session.version)
    assert unchanged == session
    assert not provider.calls


def test_rename_api_enforces_owner_and_name_limits(tmp_path):
    asyncio.run(check_rename_api(tmp_path))


async def check_rename_api(tmp_path):
    service, session = service_and_session(tmp_path)
    app = FastAPI()
    app.add_exception_handler(V2Error, v2_error_handler)
    app.include_router(create_router(lambda: service))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = f"/api/content-sessions/{session.session_id}/name"
            set_active_client("other-client")
            forbidden = await client.put(url, json={"name": "Forbidden", "expected_version": 1})
            assert forbidden.status_code == 403
            set_active_client("solar-client")
            response = await client.put(url, json={"name": "Solar storage", "expected_version": 1})
            assert response.status_code == 200
            assert response.json()["session"]["name"] == "Solar storage"
            invalid = await client.put(url, json={"name": "a" * 81, "expected_version": 2})
            assert invalid.status_code == 422
            stale = await client.put(url, json={"name": "Stale", "expected_version": 1})
            assert stale.status_code == 409
    finally:
        set_active_client(DEFAULT_CLIENT_ID)
