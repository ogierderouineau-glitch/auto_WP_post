from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Sequence

from pydantic import BaseModel, Field

from backend.app.keywords.step_01_models import normalize_phrase
from backend.app.providers.step_04_seo_sources import QueryStat

MAX_RELATED = 3
COMMON_SHARE = 0.05  # a word in more than 5% of all queries is too common to link two phrases
MIN_QUERIES_FOR_COMMON = 50


class RelatedSearch(BaseModel):
    query: str
    clicks: int
    impressions: int


class Measurement(BaseModel):
    """Search Console numbers for one keyword: the exact query plus related queries."""

    clicks: int | None = None
    impressions: int | None = None
    clicks_delta: int | None = None
    period: str | None = None
    related_searches: list[RelatedSearch] = Field(default_factory=list)


def _words(value: str) -> set[str]:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    return {word for word in re.findall(r"\w+", text) if len(word) >= 3}


def measure(keyword: str, stats: Sequence[QueryStat]) -> Measurement:
    key = normalize_phrase(keyword)
    exact: list[QueryStat] = []
    for stat in stats:
        if normalize_phrase(stat.query) == key:  # spacing/hyphen variants add up
            exact.append(stat)
    result = Measurement()
    if exact:
        result = Measurement(
            clicks=sum(s.clicks for s in exact),
            impressions=sum(s.impressions for s in exact),
            clicks_delta=sum(s.clicks_delta or 0 for s in exact),
            period=exact[0].period,
        )

    words = _words(keyword)
    if not words:
        return result
    frequency = Counter(word for stat in stats for word in _words(stat.query))
    common = (
        {word for word, count in frequency.items() if count > COMMON_SHARE * len(stats)}
        if len(stats) >= MIN_QUERIES_FOR_COMMON
        else set()
    )
    needed = max(1, math.ceil(len(words) / 2))
    related = []
    for stat in stats:
        if normalize_phrase(stat.query) == key:
            continue
        shared = words & _words(stat.query)
        if len(shared) >= needed and shared - common:  # not only generic words in common
            related.append(stat)
    related.sort(key=lambda s: (-s.impressions, -s.clicks, s.query))
    result.related_searches = [
        RelatedSearch(query=s.query, clicks=s.clicks, impressions=s.impressions)
        for s in related[:MAX_RELATED]
    ]
    return result
