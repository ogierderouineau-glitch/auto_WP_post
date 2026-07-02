from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FactSource = Literal[
    "manual_text",
    "transcript",
    "user_correction",
    "image_analysis",
    "configured",
]


class FactValue(BaseModel):
    value: Any
    source: FactSource
    confidence: float = Field(ge=0, le=1)
    confirmed: bool = False


class MediaReference(BaseModel):
    media_id: str
    filename: str
    storage_uri: str
    content_type: str
    size_bytes: int = Field(ge=0)


class Approval(BaseModel):
    approved: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None


class ContentSession(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    user_id: str
    post_type_key: str
    wordpress_post_type: str = "post"
    state: str
    workbook_hash: str
    language: str
    manual_text: str = ""
    audio_refs: list[MediaReference] = Field(default_factory=list)
    image_refs: list[MediaReference] = Field(default_factory=list)
    transcript: str = ""
    extracted_facts: dict[str, FactValue] = Field(default_factory=dict)
    confirmed_facts: dict[str, FactValue] = Field(default_factory=dict)
    clarification_questions: list[str] = Field(default_factory=list)
    context_tags: set[str] = Field(default_factory=set)
    content_signals: set[str] = Field(default_factory=set)
    image_analysis: dict[str, Any] = Field(default_factory=dict)
    shared_fields: dict[str, Any] = Field(default_factory=dict)
    acf_source_fields: dict[str, Any] = Field(default_factory=dict)
    selected_links: list[dict[str, str]] = Field(default_factory=list)
    eligible_link_ids: list[str] = Field(default_factory=list)
    related_links_html: str = ""
    processed_images: list[dict[str, Any]] = Field(default_factory=list)
    image_metadata: list[dict[str, Any]] = Field(default_factory=list)
    wordpress_payload: dict[str, Any] = Field(default_factory=dict)
    published_wordpress_payload: dict[str, Any] = Field(default_factory=dict)
    validation_report: dict[str, Any] = Field(default_factory=dict)
    generation_trace: dict[str, Any] = Field(default_factory=dict)
    draft_chat: list[dict[str, str]] = Field(default_factory=list)
    approval: Approval = Field(default_factory=Approval)
    wordpress_result: dict[str, Any] = Field(default_factory=dict)
    ai_usage: dict[str, Any] = Field(default_factory=dict)
    publication_idempotency_key: str | None = None
    workflow_steps: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
