from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Helpers that build user-facing error text: a plain-language sentence first, the raw
# technical error kept after it so it can still be used for debugging.
RELOAD_HINT = "Reload the page (F5) to get the latest version."


def explain(friendly: str, raw: object = "") -> str:
    """Plain sentence + the raw technical error (shortened) for debugging."""
    detail = " ".join(str(raw).split())
    if len(detail) > 600:
        detail = detail[:600] + "…"
    return f"{friendly} (Technical details: {detail})" if detail else friendly


def report_hint() -> str:
    """Where to report a problem the user cannot fix. Set V2_SUPPORT_CONTACT (bug-tracker link or email) on Render."""
    contact = os.getenv("V2_SUPPORT_CONTACT", "").strip()
    if contact.startswith("http"):
        return f"Please add it to the bug tracker ({contact}) and include this message."
    return f"Please report this to {contact or 'the person who runs this app'} and include this message."


def size_label(num_bytes: int) -> str:
    return f"{num_bytes / (1024 * 1024):g} MB"


def ai_failure_message(doing: str, exc: object) -> str:
    """Translate an AI-provider error into what happened and what to do; keeps the raw text."""
    raw = str(exc)
    low = raw.lower()
    status = getattr(exc, "status_code", None)
    if status == 401 or "incorrect api key" in low:
        reason = f"the AI service rejected our access key. {report_hint()}"
    elif "insufficient_quota" in low or "exceeded your current quota" in low or "billing" in low:
        reason = f"the AI account has no credit left. {report_hint()}"
    elif status == 429 or "rate limit" in low:
        reason = "the AI service is busy (too many requests). Wait a minute and try again."
    elif (
        "timed out" in low or "timeout" in low or "connection" in low
        or "temporarily unavailable" in low or (isinstance(status, int) and status >= 500)
    ):
        reason = "the AI service did not answer in time. Wait a minute and try again."
    else:
        reason = f"the AI service reported an error. Try again once; if it repeats, {report_hint()}"
    return explain(f"{doing} failed: {reason}", raw)


@dataclass(frozen=True)
class ErrorDetail:
    sheet: str | None
    row: int | None
    column: str | None
    error_code: str
    message: str
    context: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet": self.sheet,
            "row": self.row,
            "column": self.column,
            "error_code": self.error_code,
            "message": self.message,
            "context": self.context or {},
        }


class V2Error(Exception):
    error_code = "v2_error"
    http_status = 400

    def __init__(self, message: str, *, details: list[ErrorDetail] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": [detail.as_dict() for detail in self.details],
        }


def problem_lines(exc: V2Error, max_lines: int = 30) -> list[str]:
    """One line per detail (sheet, row, column, message) so the user can find each problem."""
    lines = [
        f"• {d.sheet or 'workbook'}" + (f", row {d.row}" if d.row else "") + (f", column {d.column}" if d.column else "")
        + f": {d.message} ({d.error_code})"
        for d in exc.details[:max_lines]
    ]
    if len(exc.details) > max_lines:
        lines.append(f"… and {len(exc.details) - max_lines} more.")
    return lines


class InvalidWorkbookError(V2Error):
    error_code = "invalid_workbook"
    http_status = 500

    def as_dict(self) -> dict[str, Any]:
        # Screens show only "message", so the list of problems must be part of it.
        data = super().as_dict()
        data["message"] = "\n".join([self.message, "Fix these rows in the workbook file and upload it again:", *problem_lines(self)])
        return data


def workbook_upload_message(exc: V2Error) -> str:
    """Rejected workbook upload: what to do, then one line per problem."""
    intro = "The workbook was not loaded because it contains errors. The previous workbook is still active. Fix the rows below in the Excel file and upload it again."
    return "\n".join([intro, *problem_lines(exc)]) if exc.details else f"{intro} {exc.message}"


class UnknownPostTypeError(V2Error):
    error_code = "unknown_post_type"
    http_status = 400


class InvalidStateTransitionError(V2Error):
    error_code = "invalid_state_transition"
    http_status = 409


class SessionNotFoundError(V2Error):
    error_code = "session_not_found"
    http_status = 404


class SessionVersionConflictError(V2Error):
    """The screen is older than the saved session (changed in another tab or by a background job)."""

    error_code = "session_version_conflict"
    http_status = 409

    def __init__(self, what_happened: str, *, technical: object = "", **kwargs: Any) -> None:
        super().__init__(explain(f"{what_happened} {RELOAD_HINT}", technical), **kwargs)


class SessionBusyError(V2Error):
    error_code = "session_busy"
    http_status = 409


class MissingRequiredFactsError(V2Error):
    error_code = "missing_required_facts"
    http_status = 409


class PublishingNotApprovedError(V2Error):
    error_code = "publishing_not_approved"
    http_status = 409


class UnknownTransformError(V2Error):
    error_code = "unknown_transform"
    http_status = 500


class InvalidUploadError(V2Error):
    error_code = "invalid_upload"
    http_status = 400


class ModelOutputValidationError(V2Error):
    error_code = "model_output_validation_failed"
    http_status = 502


class ImageProcessingError(V2Error):
    error_code = "image_processing_failed"
    http_status = 500


class VideoProcessingError(V2Error):
    error_code = "video_processing_unavailable"
    http_status = 503


class DraftValidationError(V2Error):
    error_code = "draft_validation_failed"
    http_status = 422


class ModelProviderError(V2Error):
    error_code = "model_provider_failed"
    http_status = 502


class TranscriptionProviderError(V2Error):
    error_code = "transcription_provider_failed"
    http_status = 502


class VisionProviderError(V2Error):
    error_code = "vision_provider_failed"
    http_status = 502


class WordPressRequestError(V2Error):
    error_code = "wordpress_request_failed"
    http_status = 502


class SessionOwnershipError(V2Error):
    error_code = "session_ownership_mismatch"
    http_status = 403


class InvalidInternalLinksError(V2Error):
    error_code = "invalid_internal_links"
    http_status = 422
