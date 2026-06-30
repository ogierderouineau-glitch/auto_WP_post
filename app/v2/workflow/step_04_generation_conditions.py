from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.v2.models.step_01_session import ContentSession


class GenerationConditionType(StrEnum):
    CONTENT_SIGNAL = "content_signal"
    CONTEXT_TAG = "context_tag"
    FACT_PRESENT = "fact_present"
    FACT_PRESENT_ANY = "fact_present_any"


class ParsedGenerationCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: GenerationConditionType
    values: tuple[str, ...]


def fact_is_usable(session: ContentSession, key: str) -> bool:
    fact = session.confirmed_facts.get(key)
    return bool(fact and fact.confirmed and fact.value not in (None, "", []))


class GenerationConditionEvaluator:
    """Evaluate workbook-authored generation conditions against a session."""

    def parse(self, condition: str | None) -> ParsedGenerationCondition | None:
        text = (condition or "").strip()
        if not text:
            return None
        condition_type, raw_values = (part.strip() for part in text.split(":", 1))
        return ParsedGenerationCondition(
            type=GenerationConditionType(condition_type),
            values=tuple(part.strip() for part in raw_values.split(";") if part.strip()),
        )

    def evaluate(self, condition: str | None, *, session: ContentSession) -> bool:
        parsed = self.parse(condition)
        if parsed is None:
            return True
        if parsed.type == GenerationConditionType.CONTENT_SIGNAL:
            return parsed.values[0] in session.content_signals
        if parsed.type == GenerationConditionType.CONTEXT_TAG:
            return parsed.values[0] in session.context_tags
        if parsed.type == GenerationConditionType.FACT_PRESENT:
            return fact_is_usable(session, parsed.values[0])
        if parsed.type == GenerationConditionType.FACT_PRESENT_ANY:
            return any(fact_is_usable(session, value) for value in parsed.values)
        raise ValueError(f"Unsupported generation condition: {parsed.type}")


def source_fact_dependencies_are_available(row: Any, session: ContentSession) -> bool:
    if row.source_mode != "derived_from_facts":
        return True
    if not row.source_fact_keys:
        return False
    return any(fact_is_usable(session, key) for key in row.source_fact_keys)
