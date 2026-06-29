from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


class InvalidWorkbookError(V2Error):
    error_code = "invalid_workbook"
    http_status = 500


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
    error_code = "session_version_conflict"
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
