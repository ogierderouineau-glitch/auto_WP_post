"""The dev-only usage report aggregates stored calls per client and is generic across industries."""
import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from backend.app.api.step_02_routes import create_router
from backend.app.models.step_01_session import ContentSession
from backend.app.sessions.step_01_repository import FileSessionRepository
from backend.app.sessions.step_03_service import ContentSessionService
from backend.config import set_active_client


def call(day, tokens, cost, name="arbitrary_task"):
    return {"service": "openai_text", "model": "model-x", "call_name": name, "prompt_tokens": tokens,
            "completion_tokens": 1, "total_tokens": tokens + 1, "estimated_cost_usd": cost,
            "updated_at": f"{day}T10:00:00+00:00"}


def make_service(tmp_path):
    repository = FileSessionRepository(tmp_path)
    for session_id, client, calls in [
        ("s1", "bakery-client", [call("2026-11-02", 10, 0.5), call("2026-11-03", 5, None), {"call_name": "old"}]),
        ("s2", "bakery-client", [call("2026-11-02", 20, 1.0)]),
        ("s3", "other-client", [call("2026-11-02", 99, 9.0)]),
    ]:
        repository.create(ContentSession(session_id=session_id, user_id=client, post_type_key="any_key",
                                         state="ready_to_generate", workbook_hash="h", language="en", ai_usage={"calls": calls}))
    return ContentSessionService(knowledge=SimpleNamespace(), repository=repository)


def test_usage_report_groups_periods_and_isolates_clients(tmp_path):
    report = make_service(tmp_path).usage_report(user_id="bakery-client")
    day = {(r["period"], r["call_name"]): r for r in report["day"]}
    assert day[("2026-11-02", "arbitrary_task")]["call_count"] == 2
    assert day[("2026-11-02", "arbitrary_task")]["estimated_cost_usd"] == 1.5
    assert day[("2026-11-03", "arbitrary_task")]["unknown_usage_calls"] == 1
    assert ("undated", "old") in day
    assert {r["period"] for r in report["week"]} == {"2026-W45", "undated"}
    assert {r["period"] for r in report["month"]} == {"2026-11", "undated"}
    assert sum(r["total_tokens"] for r in report["month"]) == 11 + 6 + 21


def test_usage_report_route_is_hidden_on_render(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    set_active_client("bakery-client")

    async def fetch():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            return await client.get("/api/content-sessions/_usage-report")

    monkeypatch.delenv("RENDER", raising=False)
    assert asyncio.run(fetch()).status_code == 200
    monkeypatch.setenv("RENDER", "1")
    assert asyncio.run(fetch()).status_code == 404
