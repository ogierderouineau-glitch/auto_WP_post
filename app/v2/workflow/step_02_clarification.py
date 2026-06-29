from __future__ import annotations

from dataclasses import dataclass

from app.v2.knowledge_base.step_01_models import WorkbookSnapshot
from app.v2.models.step_01_session import ContentSession, FactValue


@dataclass(frozen=True)
class MissingDependency:
    output_field_key: str
    source_fact_keys: tuple[str, ...]


class ClarificationService:
    """Determine missing dependencies in Python; wording may be delegated later."""

    def missing_required_dependencies(
        self,
        snapshot: WorkbookSnapshot,
        session: ContentSession,
    ) -> tuple[MissingDependency, ...]:
        usable = {
            key
            for key, fact in session.confirmed_facts.items()
            if fact.confirmed and fact.value not in (None, "", [])
        }
        missing: list[MissingDependency] = []
        for field in snapshot.acf_fields:
            if (
                field.enabled
                and field.post_type_key == session.post_type_key
                and field.field_role == "input_fact"
                and field.required_for_analysis
                and field.field_key not in usable
            ):
                missing.append(MissingDependency(field.field_key, (field.field_key,)))
        for field in snapshot.acf_fields:
            if (
                field.enabled
                and field.post_type_key == session.post_type_key
                and field.source_mode == "derived_from_facts"
                and field.required_for_output
                and field.source_fact_keys
                and not usable.intersection(field.source_fact_keys)
            ):
                missing.append(MissingDependency(field.field_key, field.source_fact_keys))
        return tuple(missing)

    @staticmethod
    def bundled_questions(missing: tuple[MissingDependency, ...]) -> list[str]:
        fact_keys = sorted({key for dependency in missing for key in dependency.source_fact_keys})
        if not fact_keys:
            return []
        return ["Bitte ergänzen oder bestätigen Sie: " + ", ".join(fact_keys) + "."]

    @staticmethod
    def apply_corrections(
        session: ContentSession,
        corrections: dict[str, object],
    ) -> ContentSession:
        confirmed = dict(session.confirmed_facts)
        for key, value in corrections.items():
            confirmed[key] = FactValue(
                value=value,
                source="user_correction",
                confidence=1.0,
                confirmed=True,
            )
        return session.model_copy(update={"confirmed_facts": confirmed})
