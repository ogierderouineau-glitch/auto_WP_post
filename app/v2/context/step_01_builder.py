from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.v2.knowledge_base.step_01_models import WorkbookSnapshot
from app.v2.models.step_01_session import ContentSession
from app.v2.workflow.step_01_conditions import condition_matches


class FieldContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    schema_data: dict[str, Any] = Field(alias="schema")
    exact_rules: list[dict[str, Any]] = Field(default_factory=list)
    group_rules: list[dict[str, Any]] = Field(default_factory=list)
    section_rules: list[dict[str, Any]] = Field(default_factory=list)
    style_rules: list[dict[str, Any]] = Field(default_factory=list)


class GenerationContext(BaseModel):
    task: str
    post_type: dict[str, Any]
    source_text: dict[str, str] = Field(default_factory=dict)
    confirmed_facts: dict[str, Any]
    fields: dict[str, FieldContext]
    blueprint: list[dict[str, Any]]
    instructions: list[dict[str, Any]]
    story_patterns: list[dict[str, Any]]
    examples: list[dict[str, Any]]


class GenerationContextBuilder:
    """Build filtered, field-addressable context; never expose a raw workbook."""

    def build(
        self,
        *,
        snapshot: WorkbookSnapshot,
        task: str,
        post_type_key: str,
        session: ContentSession,
        field_keys: list[str] | None = None,
        section: str | None = None,
    ) -> GenerationContext:
        post_type = snapshot.post_type(post_type_key)
        if post_type is None:
            raise KeyError(post_type_key)
        schemas = [
            row
            for row in (*snapshot.shared_fields, *snapshot.acf_fields)
            if row.enabled
            and getattr(row, "include_in_ai_schema", False)
            and getattr(row, "post_type_key", post_type_key) == post_type_key
            and (field_keys is None or row.field_key in field_keys)
            and (section is None or getattr(row, "section", None) == section)
        ]
        fields: dict[str, FieldContext] = {}
        for schema in schemas:
            exact = [
                row.model_dump(exclude={"sheet_row"})
                for row in snapshot.seo_rules
                if row.enabled
                and row.stage in {task, "generation" if task.endswith("generation") else task}
                and row.post_type_key in {"*", post_type_key}
                and row.target_type == "field"
                and row.target_key == schema.field_key
            ]
            group = getattr(schema, "group", None)
            group_rules = [
                row.model_dump(exclude={"sheet_row"})
                for row in snapshot.seo_rules
                if row.enabled
                and row.post_type_key in {"*", post_type_key}
                and row.target_type == "group"
                and row.target_key == group
            ]
            schema_section = getattr(schema, "section", None)
            section_rules = [
                row.model_dump(exclude={"sheet_row"})
                for row in snapshot.seo_rules
                if row.enabled
                and row.post_type_key in {"*", post_type_key}
                and row.target_type == "section"
                and row.target_key == schema_section
            ]
            styles = [
                row.model_dump(exclude={"sheet_row"})
                for row in snapshot.style_rules
                if row.enabled
                and row.post_type_key in {"*", post_type_key}
                and (
                    row.match_type == "global"
                    or (row.match_type == "field" and row.match_value == schema.field_key)
                    or (row.match_type == "section" and row.match_value == schema_section)
                    or (row.match_type == "event_context" and row.match_value in session.context_tags)
                    or (row.match_type == "content_signal" and row.match_value in session.content_signals)
                )
            ]
            fields[schema.field_key] = FieldContext(
                schema_data=self._schema_for_model(schema),
                exact_rules=exact,
                group_rules=group_rules,
                section_rules=section_rules,
                style_rules=styles,
            )

        blueprint = [
            row.model_dump(exclude={"sheet_row"})
            for row in sorted(snapshot.blueprint, key=lambda item: item.section_order)
            if row.enabled
            and row.post_type_key == post_type_key
            and condition_matches(row.display_condition, session)
        ]
        instructions = [
            row.model_dump(exclude={"sheet_row"})
            for row in snapshot.agent_instructions
            if row.enabled
            and row.owner == "language_model"
            and row.post_type_key in {"*", post_type_key}
            and row.workflow_stage in {"all", task}
            and (row.condition == "always" or row.condition in session.content_signals)
        ]
        patterns = [
            row
            for row in snapshot.story_patterns
            if row.enabled
            and row.post_type_key == post_type_key
            and set(row.trigger_tags).intersection(session.context_tags)
            and not set(row.excluded_tags).intersection(session.context_tags)
            and set(row.required_facts).issubset(session.confirmed_facts)
            and set(row.required_content_signals).issubset(session.content_signals)
        ]
        priority_order = {"high": 0, "medium": 1, "low": 2}
        patterns.sort(key=lambda row: (priority_order.get(row.priority, 9), row.pattern_id))
        examples = [
            row.model_dump(exclude={"sheet_row"})
            for row in sorted(snapshot.post_examples, key=lambda item: item.quality_score, reverse=True)
            if row.enabled and row.approved and row.post_type_key == post_type_key
        ][:5]
        return GenerationContext(
            task=task,
            post_type=post_type.model_dump(exclude={"sheet_row"}),
            source_text={
                "manual_text": session.manual_text,
                "transcript": session.transcript,
            },
            confirmed_facts={
                key: value.model_dump()
                for key, value in session.confirmed_facts.items()
            },
            fields=fields,
            blueprint=blueprint,
            instructions=instructions,
            story_patterns=[row.model_dump(exclude={"sheet_row"}) for row in patterns[:2]],
            examples=examples,
        )

    @staticmethod
    def _schema_for_model(schema: Any) -> dict[str, Any]:
        payload = schema.model_dump(exclude={"sheet_row"})
        if (
            payload.get("field_role") == "aggregation_source"
            and payload.get("transform_key")
        ):
            original_guidance = payload.get("guidance_de")
            payload["guidance_de"] = (
                (f"{original_guidance} " if original_guidance else "")
                +
                "Nur den semantischen Rohwert ohne HTML zurückgeben. "
                "Python wendet transform_key deterministisch an. "
                "Nutze die Bedeutung aus description_de und guidance_de, um passende "
                "explizite Evidenz aus source_text oder confirmed_facts zu finden."
            )
            payload["example"] = None
            payload["model_output_contract"] = "raw_text_without_html"
        return payload
