from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.v2.models.step_01_session import ContentSession


class CreateSessionRequest(BaseModel):
    user_id: str
    post_type_key: str


class InputsRequest(BaseModel):
    expected_version: int
    manual_text: str | None = None
    confirmed_facts: dict[str, Any] = Field(default_factory=dict)


class VersionedRequest(BaseModel):
    expected_version: int


class AnswersRequest(VersionedRequest):
    corrections: dict[str, Any]


class GenerateRequest(VersionedRequest):
    shared_fields: dict[str, Any] = Field(default_factory=dict)
    acf_source_fields: dict[str, Any] = Field(default_factory=dict)
    selected_links: list[dict[str, str]] = Field(default_factory=list)
    current_url: str | None = None
    use_vision_for_image_metadata: bool = True
    revision_instruction: str | None = None


class DraftChatRequest(GenerateRequest):
    message: str


class ApproveRequest(VersionedRequest):
    user_id: str


class PublishRequest(VersionedRequest):
    idempotency_key: str


class ImageMetadataUpdateRequest(VersionedRequest):
    filename: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeaturedImageRequest(VersionedRequest):
    filename: str


class ImageOptimizationRequest(VersionedRequest):
    filename: str
    prompt: str


class SessionsDeleteRequest(BaseModel):
    session_ids: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session: ContentSession
