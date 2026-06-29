from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WordPressFields(BaseModel):
    title: str = ""
    slug: str = ""
    excerpt: str = ""
    status: str = "draft"
    categories: list[str | int] = Field(default_factory=list)
    tags: list[str | int] = Field(default_factory=list)


class WordPressPayload(BaseModel):
    wordpress: WordPressFields
    meta: dict[str, Any] = Field(default_factory=dict)
    acf: dict[str, Any] = Field(default_factory=dict)
    media: list[dict[str, Any]] = Field(default_factory=list)
