from __future__ import annotations

from typing import Any

from app.v2.knowledge_base.step_01_models import ACFFieldSchema, ImageMetadataField, ImageMetadataRule
from app.v2.models.step_01_session import ContentSession
from app.v2.workflow.step_04_generation_conditions import fact_is_usable


PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
USAGE_MODE_ORDER = {
    "exclude": 0,
    "require_when_visible_and_confirmed": 1,
    "prefer_when_natural": 2,
    "allow": 3,
}


class ImageMetadataFactContextBuilder:
    """Expose only workbook-approved input facts to image metadata generation."""

    def build_base_facts(
        self,
        *,
        session: ContentSession,
        acf_schema: list[ACFFieldSchema],
    ) -> dict[str, Any]:
        allowed_keys = {
            row.field_key
            for row in acf_schema
            if row.enabled
            and row.post_type_key == session.post_type_key
            and row.field_role == "input_fact"
            and row.include_in_image_metadata_context is True
        }
        return {
            key: fact.model_dump()
            for key, fact in session.confirmed_facts.items()
            if key in allowed_keys and fact_is_usable(session, key)
        }


class ImageMetadataRuleMatcher:
    """Select workbook-authored image metadata rules for one image/session."""

    def match(
        self,
        *,
        rules: list[ImageMetadataRule],
        post_type_key: str,
        image_analysis: dict[str, Any],
        content_signals: set[str],
        context_tags: set[str],
    ) -> list[ImageMetadataRule]:
        matched = [
            row
            for row in rules
            if row.enabled
            and row.post_type_key in {"*", post_type_key}
            and self._trigger_matches(
                row,
                image_analysis=image_analysis,
                content_signals=content_signals,
                context_tags=context_tags,
            )
        ]
        return sorted(
            matched,
            key=lambda row: (
                PRIORITY_ORDER.get(row.priority, 99),
                USAGE_MODE_ORDER.get(row.usage_mode, 99),
                row.rule_id,
            ),
        )

    @staticmethod
    def _trigger_matches(
        row: ImageMetadataRule,
        *,
        image_analysis: dict[str, Any],
        content_signals: set[str],
        context_tags: set[str],
    ) -> bool:
        if row.trigger_type == "always":
            return True
        if row.trigger_type == "content_signal":
            return bool(set(row.trigger_value).intersection(content_signals))
        if row.trigger_type == "context_tag":
            return bool(set(row.trigger_value).intersection(context_tags))
        if row.trigger_type == "image_analysis_contains":
            if not row.trigger_key:
                return False
            value = image_analysis.get(row.trigger_key)
            if value in (None, ""):
                return False
            values = set(value) if isinstance(value, (list, tuple, set)) else {value}
            return bool(values.intersection(row.trigger_value))
        return False


class ImageMetadataFieldContextBuilder:
    """Build target-field-specific context for image metadata generation."""

    def build(
        self,
        *,
        metadata_rows: list[ImageMetadataField],
        matching_rules: list[ImageMetadataRule],
        session: ContentSession,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        for metadata_row in metadata_rows:
            if not metadata_row.enabled:
                continue
            field_rules = [
                rule
                for rule in matching_rules
                if metadata_row.field_key in rule.target_field_keys
            ]
            excluded_facts = {
                fact_key
                for rule in field_rules
                if rule.usage_mode == "exclude"
                for fact_key in rule.source_fact_keys
            }
            priority_facts = {
                fact_key: session.confirmed_facts[fact_key].model_dump()
                for rule in field_rules
                if rule.usage_mode != "exclude"
                for fact_key in rule.source_fact_keys
                if fact_key not in excluded_facts and fact_is_usable(session, fact_key)
            }
            fields[metadata_row.field_key] = {
                "schema": metadata_row.model_dump(exclude={"sheet_row"}),
                "matching_rules": [
                    rule.model_dump(exclude={"sheet_row"})
                    for rule in field_rules
                    if rule.usage_mode != "exclude"
                ],
                "priority_facts": priority_facts,
            }
        return fields
