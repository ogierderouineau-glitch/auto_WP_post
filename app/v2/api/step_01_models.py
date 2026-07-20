from __future__ import annotations

from typing import Any, Literal

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


class GenerationSettingsRequest(VersionedRequest):
    language_model: Literal[
        "gpt-5-mini",
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6",
    ]
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"]
    generation_mode: Literal["batched", "single"] = "single"


class AnalyzeRequest(VersionedRequest):
    review_fact_keys: list[str] | None = None


class AnswersRequest(VersionedRequest):
    corrections: dict[str, Any]


class GenerateRequest(VersionedRequest):
    shared_fields: dict[str, Any] = Field(default_factory=dict)
    acf_source_fields: dict[str, Any] = Field(default_factory=dict)
    selected_links: list[dict[str, str]] = Field(default_factory=list)
    current_url: str | None = None
    use_vision_for_image_metadata: bool = True
    ai_assisted_link_placement: bool = False
    link_placement_only: bool = False
    revision_instruction: str | None = None


class DraftChatRequest(GenerateRequest):
    message: str
    revision_field_ids: list[str] | None = None


class DraftFieldsUpdateRequest(VersionedRequest):
    shared_fields: dict[str, Any] = Field(default_factory=dict)
    acf_source_fields: dict[str, Any] = Field(default_factory=dict)


class ApproveRequest(VersionedRequest):
    user_id: str


class PublishRequest(VersionedRequest):
    idempotency_key: str
    target_post_id: int | None = None
    force_create_new: bool = False
    partial_update: bool = False
    shared_fields: dict[str, Any] = Field(default_factory=dict)
    acf_source_fields: dict[str, Any] = Field(default_factory=dict)


class ImageMetadataUpdateRequest(VersionedRequest):
    filename: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    use_vision_for_metadata: bool | None = None


class ImageContextTranscriptUpdateRequest(VersionedRequest):
    filename: str
    transcript: str = ""


class FeaturedImageRequest(VersionedRequest):
    filename: str


class ImageOptimizationRequest(VersionedRequest):
    filename: str
    prompt: str


class SessionsDeleteRequest(BaseModel):
    session_ids: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session: ContentSession
