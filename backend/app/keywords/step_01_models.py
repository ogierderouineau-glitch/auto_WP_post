from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

KeywordStatus = Literal["free", "focus_elsewhere", "mentioned_elsewhere"]


def normalize_phrase(value: str) -> str:
    """Compare phrases ignoring case, spaces, hyphens and punctuation, so compound
    spellings match ("Kaffee-Catering" == "Kaffeecatering")."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value or "").casefold())


class KeywordCandidate(BaseModel):
    """One proposed keyword as returned by the language model."""

    keyword: str
    alternatives: list[str] = Field(default_factory=list)
    status: KeywordStatus
    related_refs: list[str] = Field(
        default_factory=list,
        description="Refs of existing pages that use or mention this keyword.",
    )
    rationale: str


class KeywordProposalOutput(BaseModel):
    candidates: list[KeywordCandidate]


class KeywordProposalRow(BaseModel):
    """A candidate after the application verified and enriched it."""

    keyword: str
    alternatives: list[str]
    status: KeywordStatus
    related_urls: list[str]
    rationale: str
    clicks: int | None = None
    impressions: int | None = None
    clicks_delta: int | None = None
    month: str | None = None
