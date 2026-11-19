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


def test_workbook_upload_message_lists_every_problem_with_sheet_and_row() -> None:
    from backend.app.errors import ErrorDetail, InvalidWorkbookError, workbook_upload_message

    errors = [
        ErrorDetail("sheet_a", 14, "col_x", "bad_value", "Value does not resolve."),
        ErrorDetail("sheet_b", None, None, "missing", "Sheet is required."),
    ]
    text = workbook_upload_message(InvalidWorkbookError("Workbook validation failed with 2 error(s).", details=errors))

    assert text.startswith("The workbook was not loaded")
    assert "• sheet_a, row 14, column col_x: Value does not resolve. (bad_value)" in text
    assert "• sheet_b: Sheet is required. (missing)" in text


def test_invalid_workbook_error_carries_its_problem_list_in_the_message() -> None:
    from backend.app.errors import ErrorDetail, InvalidWorkbookError

    exc = InvalidWorkbookError(
        "Workbook validation failed with 1 error(s).",
        details=[ErrorDetail("sheet_a", 3, "col_x", "bad_value", "Value does not resolve.")],
    )
    assert "• sheet_a, row 3, column col_x: Value does not resolve." in exc.as_dict()["message"]


def test_workbook_status_reports_an_invalid_workbook_instead_of_failing() -> None:
    import asyncio
    from types import SimpleNamespace

    from backend.app.api.step_02_routes import create_router
    from backend.app.errors import ErrorDetail, InvalidWorkbookError

    def broken():
        raise InvalidWorkbookError("bad", details=[ErrorDetail("s", 1, "c", "x", "Problem.")])

    service = SimpleNamespace(knowledge=SimpleNamespace(current=broken))
    router = create_router(lambda *a, **k: service, lambda: None, lambda: {})
    status = next(r.endpoint for r in router.routes if getattr(r, "path", "").endswith("/_workbook") and "GET" in r.methods)

    result = asyncio.run(status(post_type_key=None))

    assert result["post_types"] == [] and "• s, row 1, column c: Problem." in result["workbook_error"]
