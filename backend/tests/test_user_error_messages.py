"""Checks that user-facing error text is plain language and still carries the raw error."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.step_02_routes import unexpected_error_handler
from backend.app.errors import (
    RELOAD_HINT,
    SessionVersionConflictError,
    ai_failure_message,
    explain,
    size_label,
)


class FakeApiError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_explain_keeps_raw_error_after_plain_sentence():
    text = explain("Something failed.", "ValueError: boom")
    assert text == "Something failed. (Technical details: ValueError: boom)"


def test_ai_quota_error_is_translated_and_raw_kept():
    raw = "Error code: 429 - insufficient_quota"
    text = ai_failure_message("Analysing picture a.jpg", FakeApiError(raw, 429))
    assert "no credit left" in text and raw in text


def test_ai_rate_limit_and_timeout_say_wait():
    assert "Wait a minute" in ai_failure_message("X", FakeApiError("slow down", 429))
    assert "Wait a minute" in ai_failure_message("X", RuntimeError("Request timed out."))


def test_version_conflict_says_what_to_reload_and_keeps_details():
    error = SessionVersionConflictError("The session was changed elsewhere.", technical="v3 to v4")
    assert RELOAD_HINT in error.message and "v3 to v4" in error.message


def test_size_label_is_in_megabytes():
    assert size_label(250 * 1024 * 1024) == "250 MB"


def test_unexpected_error_returns_reference_and_raw_error():
    app = FastAPI()
    app.add_exception_handler(Exception, unexpected_error_handler)

    @app.get("/boom")
    def boom():
        raise RuntimeError("provider not configured")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    message = response.json()["message"]
    assert response.status_code == 500
    assert "reference" in message and "RuntimeError: provider not configured" in message
