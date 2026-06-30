from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app.v2.errors import ErrorDetail, InvalidWorkbookError
from app.v2.knowledge_base.step_01_models import WorkbookSnapshot
from app.v2.workflow.step_03_registry import WORKFLOW_HANDLER_METHODS
from app.v2.images.step_01_conditions import IMAGE_CONDITION_HANDLERS
from app.v2.payloads.step_01_transforms import TRANSFORMS


class WorkbookValidator:
    """Validate exact workbook relationships without fuzzy namespace fallback."""

    def validate(self, snapshot: WorkbookSnapshot) -> WorkbookSnapshot:
        errors: list[ErrorDetail] = []
        families = {
            name: snapshot.validation_family(name)
            for name in {value.list_name for value in snapshot.validation_values}
        }
        self._unique(errors, "post_types", snapshot.post_types, "post_type_key")
        self._unique(errors, "shared_fields_schema", snapshot.shared_fields, "field_key")
        self._unique(errors, "ACF_fields_schema", snapshot.acf_fields, "field_key")
        self._unique(errors, "post_examples", snapshot.post_examples, "example_id")
        self._unique(errors, "image_rules_pillow", snapshot.pillow_rules, "rule_key")
        self._unique(errors, "image_metadata_rules", snapshot.image_metadata_rules, "rule_id")
        self._unique(errors, "agent_workflow", snapshot.workflow_steps, "step_key")
        self._unique_validation_values(errors, snapshot)

        post_types = {row.post_type_key: row for row in snapshot.post_types}
        enabled_acf = tuple(row for row in snapshot.acf_fields if row.enabled)
        input_facts: dict[str, set[str]] = defaultdict(set)
        acf_names: dict[str, set[str]] = defaultdict(set)
        aggregation_groups: dict[str, set[str]] = defaultdict(set)
        groups: dict[str, set[str]] = defaultdict(set)
        sections: dict[str, set[str]] = defaultdict(set)
        field_keys: dict[str, set[str]] = defaultdict(set)
        for row in enabled_acf:
            field_keys[row.post_type_key].add(row.field_key)
            if row.field_role == "input_fact":
                input_facts[row.post_type_key].add(row.field_key)
            if row.acf_field_name:
                acf_names[row.post_type_key].add(row.acf_field_name)
            if row.aggregation_group:
                aggregation_groups[row.post_type_key].add(row.aggregation_group)
            if row.group:
                groups[row.post_type_key].add(row.group)
            if row.section:
                sections[row.post_type_key].add(row.section)

        shared_keys = {row.field_key for row in snapshot.shared_fields if row.enabled}
        shared_groups = {row.group for row in snapshot.shared_fields if row.enabled}
        image_metadata_keys = {row.field_key for row in snapshot.image_metadata_fields if row.enabled}

        for row in snapshot.post_types:
            if row.enabled and (not row.generation_enabled or not row.template_ready):
                errors.append(self._error("post_types", row.sheet_row, "enabled", "enabled_post_type_not_ready",
                                          "Enabled post types must be generation-enabled and template-ready."))
            if row.enabled and (not row.wp_post_type or not row.wp_category_name):
                errors.append(self._error("post_types", row.sheet_row, "wp_post_type",
                                          "missing_wordpress_routing", "Enabled post type is missing WordPress routing."))

        for row in snapshot.post_examples:
            if row.enabled and row.post_type_key not in post_types:
                errors.append(self._error("post_examples", row.sheet_row, "post_type_key",
                                          "unknown_post_type", "Example post type does not resolve."))

        for row in enabled_acf:
            if row.post_type_key not in post_types:
                errors.append(self._error("ACF_fields_schema", row.sheet_row, "post_type_key",
                                          "unknown_post_type", "ACF post type does not resolve."))
            if row.field_role == "input_fact" and (
                row.acf_field_name or row.aggregation_group or row.include_in_payload
            ):
                errors.append(self._error("ACF_fields_schema", row.sheet_row, "field_role",
                                          "invalid_input_fact_contract",
                                          "Input facts cannot have ACF/aggregation destinations or direct payload output."))
            if row.field_role == "direct_acf" and (not row.acf_field_name or not row.include_in_payload):
                errors.append(self._error("ACF_fields_schema", row.sheet_row, "field_role",
                                          "invalid_direct_acf_contract",
                                          "Direct ACF fields require a destination and payload inclusion."))
            if row.field_role == "aggregation_source" and not all(
                (row.acf_field_name, row.aggregation_group, row.aggregation_order, row.transform_key)
            ):
                errors.append(self._error("ACF_fields_schema", row.sheet_row, "field_role",
                                          "invalid_aggregation_source_contract",
                                          "Aggregation sources require destination, group, order and transform."))
            if row.field_role == "aggregation_source" and row.transform_key not in TRANSFORMS:
                errors.append(self._error(
                    "ACF_fields_schema",
                    row.sheet_row,
                    "transform_key",
                    "unknown_transform",
                    "Aggregation transform has no registered Python handler.",
                ))
            if row.source_mode == "derived_from_facts":
                if row.required_for_output and not row.source_fact_keys:
                    errors.append(self._error("ACF_fields_schema", row.sheet_row, "source_fact_keys",
                                              "missing_source_fact_keys",
                                              "Required derived fields need at least one source fact."))
                for source_key in row.source_fact_keys:
                    if source_key not in input_facts[row.post_type_key]:
                        errors.append(self._error("ACF_fields_schema", row.sheet_row, "source_fact_keys",
                                                  "unknown_source_fact_key",
                                                  "Source fact does not resolve for the same post type."))
            if row.min_words is not None and row.max_words is not None and row.min_words > row.max_words:
                errors.append(self._error("ACF_fields_schema", row.sheet_row, "min_words",
                                          "invalid_word_range", "min_words cannot exceed max_words."))
            self._validate_generation_condition(errors, row, input_facts, families)
            self._validate_image_metadata_context_flag(errors, row)
            self._enum_reference(errors, "ACF_fields_schema", row.sheet_row, row.value_type,
                                 row.format_or_enum, families)
        self._validate_aggregation_groups(errors, enabled_acf)

        for row in snapshot.shared_fields:
            if not row.enabled:
                continue
            if row.source_mode == "configured" and row.include_in_ai_schema:
                errors.append(self._error("shared_fields_schema", row.sheet_row, "include_in_ai_schema",
                                          "configured_field_exposed_to_ai",
                                          "Configured fields must be excluded from AI schemas."))
            if row.min_words is not None and row.max_words is not None and row.min_words > row.max_words:
                errors.append(self._error("shared_fields_schema", row.sheet_row, "min_words",
                                          "invalid_word_range", "min_words cannot exceed max_words."))
            if (
                row.min_characters is not None
                and row.max_characters is not None
                and row.min_characters > row.max_characters
            ):
                errors.append(self._error("shared_fields_schema", row.sheet_row, "min_characters",
                                          "invalid_character_range",
                                          "min_characters cannot exceed max_characters."))
            self._enum_reference(errors, "shared_fields_schema", row.sheet_row, row.value_type,
                                 row.format_or_enum, families)

        for row in snapshot.blueprint:
            if not row.enabled:
                continue
            namespace: set[str]
            if row.target_type == "acf_field":
                namespace = acf_names[row.post_type_key]
            elif row.target_type == "aggregation_group":
                namespace = aggregation_groups[row.post_type_key]
            elif row.target_type == "group":
                namespace = groups[row.post_type_key]
            elif row.target_type == "section":
                namespace = sections[row.post_type_key]
            elif row.target_type == "shared_field":
                namespace = shared_keys
            elif row.target_type == "image_metadata_field":
                namespace = image_metadata_keys
            elif row.target_type == "layout_marker":
                namespace = {row.target_key} if row.target_key.strip() else set()
            else:
                namespace = set()
            if row.target_key not in namespace:
                errors.append(self._error("post_blueprint", row.sheet_row, "target_key",
                                          "unresolved_blueprint_target",
                                          "Blueprint target does not resolve in its declared namespace."))
            if row.display_condition not in families.get("display_condition", frozenset()):
                errors.append(self._error("post_blueprint", row.sheet_row, "display_condition",
                                          "unknown_display_condition",
                                          "Blueprint display condition is not registered."))
            if row.display_condition != "always" and row.required:
                errors.append(self._error("post_blueprint", row.sheet_row, "required",
                                          "conditional_blueprint_required",
                                          "Conditional blueprint rows must be optional."))

        for row in snapshot.workflow_steps:
            if row.step_key not in WORKFLOW_HANDLER_METHODS:
                errors.append(self._error("agent_workflow", row.sheet_row, "step_key",
                                          "unknown_workflow_step",
                                          "Enabled workflow step has no registered Python handler."))
            if row.run_condition not in families.get("run_condition", frozenset()):
                errors.append(self._error("agent_workflow", row.sheet_row, "run_condition",
                                          "unknown_run_condition",
                                          "Workflow run condition is not registered."))
            if row.run_condition != "always" and row.required:
                errors.append(self._error("agent_workflow", row.sheet_row, "required",
                                          "conditional_workflow_step_required",
                                          "Conditional workflow steps must be optional."))

        for row in snapshot.pillow_rules:
            if not row.enabled:
                continue
            if row.value_type == "enum":
                if not row.value_domain or row.value_domain not in families:
                    errors.append(self._error("image_rules_pillow", row.sheet_row, "value_domain",
                                              "unknown_pillow_enum_domain",
                                              "Enum Pillow rule must reference a validation-list family."))
                elif row.value not in families[row.value_domain]:
                    errors.append(self._error("image_rules_pillow", row.sheet_row, "value",
                                              "invalid_pillow_enum_value",
                                              "Pillow enum value is not allowed by its domain."))
            if row.condition not in IMAGE_CONDITION_HANDLERS:
                errors.append(self._error("image_rules_pillow", row.sheet_row, "condition",
                                          "unknown_image_condition",
                                          "Pillow condition has no registered Python handler."))
            if isinstance(row.value, (int, float)) and not isinstance(row.value, bool):
                if row.min_value is not None and row.value < row.min_value:
                    errors.append(self._error("image_rules_pillow", row.sheet_row, "value",
                                              "pillow_value_below_minimum", "Pillow value is below min_value."))
                if row.max_value is not None and row.value > row.max_value:
                    errors.append(self._error("image_rules_pillow", row.sheet_row, "value",
                                              "pillow_value_above_maximum", "Pillow value exceeds max_value."))

        for row in snapshot.image_analysis_rules:
            if row.enabled and row.expected_output not in families.get("image_analysis_output", frozenset()):
                errors.append(self._error("image_analysis_rules", row.sheet_row, "expected_output",
                                          "unknown_image_analysis_output",
                                          "Image-analysis output type is not registered."))
            if row.enabled and row.output_domain and row.output_domain not in families:
                errors.append(self._error("image_analysis_rules", row.sheet_row, "output_domain",
                                          "unknown_image_output_domain",
                                          "Image-analysis output domain is not registered."))

        self._validate_rule_targets(
            errors,
            snapshot,
            shared_keys,
            shared_groups,
            field_keys,
            groups,
            sections,
            image_metadata_keys,
            families,
            input_facts,
        )
        self._validate_image_metadata_rules(errors, snapshot, post_types, input_facts, image_metadata_keys, families)
        self._validate_internal_links(errors, snapshot)
        self._validate_state_machine(errors, snapshot)
        self._validate_output_specification(errors, snapshot)

        if errors:
            raise InvalidWorkbookError(
                f"Workbook validation failed with {len(errors)} error(s).",
                details=errors,
            )
        return snapshot

    @staticmethod
    def _unique(
        errors: list[ErrorDetail],
        sheet: str,
        rows: Iterable[Any],
        attribute: str,
    ) -> None:
        seen: dict[Any, int] = {}
        for row in rows:
            value = getattr(row, attribute)
            if value in seen:
                errors.append(WorkbookValidator._error(
                    sheet, row.sheet_row, attribute, f"duplicate_{attribute}",
                    f"{attribute} must be unique; first seen on row {seen[value]}.",
                ))
            seen[value] = row.sheet_row

    @staticmethod
    def _unique_validation_values(errors: list[ErrorDetail], snapshot: WorkbookSnapshot) -> None:
        seen: dict[tuple[str, Any], int] = {}
        for row in snapshot.validation_values:
            key = (row.list_name, row.allowed_value)
            if key in seen:
                errors.append(WorkbookValidator._error(
                    "validation_lists", row.sheet_row, "allowed_value",
                    "duplicate_validation_value",
                    f"Validation-list pair was first declared on row {seen[key]}.",
                ))
            seen[key] = row.sheet_row

    @staticmethod
    def _enum_reference(
        errors: list[ErrorDetail],
        sheet: str,
        row: int,
        value_type: str,
        domain: str | None,
        families: dict[str, frozenset[Any]],
    ) -> None:
        if value_type == "enum" and (not domain or domain not in families):
            errors.append(WorkbookValidator._error(
                sheet, row, "format_or_enum", "unknown_enum_domain",
                "Enum field does not resolve to validation_lists.",
            ))

    def _validate_rule_targets(
        self,
        errors: list[ErrorDetail],
        snapshot: WorkbookSnapshot,
        shared_keys: set[str],
        shared_groups: set[str],
        field_keys: dict[str, set[str]],
        groups: dict[str, set[str]],
        sections: dict[str, set[str]],
        image_metadata_keys: set[str],
        families: dict[str, frozenset[Any]],
        input_facts: dict[str, set[str]],
    ) -> None:
        all_field_keys = shared_keys.union(*(values for values in field_keys.values()))
        all_groups = shared_groups.union(*(values for values in groups.values()))
        all_sections = set().union(*(values for values in sections.values()))
        internal_targets = {
            "internal_link_primary",
            "internal_link_secondary",
            "internal_link_contextual",
            "internal_link_count",
        }
        draft_targets = {"all_content", "seo"}
        for row in snapshot.style_rules:
            if not row.enabled:
                continue
            namespace = {
                "global": {row.match_value},
                "field": all_field_keys,
                "section": all_sections,
                "event_context": set(families.get("context_tag", ())),
                "content_signal": set(families.get("content_signal", ())),
                "post_type": {item.post_type_key for item in snapshot.post_types},
            }.get(row.match_type, set())
            if row.match_value not in namespace:
                errors.append(self._error("style_rules", row.sheet_row, "match_value",
                                          "unresolved_style_target",
                                          "Style target does not resolve exactly."))
        for row in snapshot.seo_rules:
            if not row.enabled:
                continue
            namespace = {
                "field": all_field_keys,
                "group": all_groups,
                "section": all_sections,
                "image_metadata": image_metadata_keys,
                "internal_links": internal_targets,
                "draft_validation": draft_targets,
            }.get(row.target_type, set())
            if row.target_key not in namespace:
                errors.append(self._error("seo_rules", row.sheet_row, "target_key",
                                          "unresolved_seo_target",
                                          "SEO target does not resolve exactly."))
        for row in snapshot.story_patterns:
            if not row.enabled:
                continue
            for fact in row.required_facts:
                if fact not in input_facts[row.post_type_key]:
                    errors.append(self._error("story_patterns", row.sheet_row, "required_facts",
                                              "unknown_story_required_fact",
                                              "Story required fact does not resolve."))
            for tag in (*row.trigger_tags, *row.excluded_tags):
                if tag not in families.get("context_tag", frozenset()):
                    errors.append(self._error("story_patterns", row.sheet_row, "trigger_tags",
                                              "unknown_context_tag",
                                              "Story context tag is not registered."))
            for signal in row.required_content_signals:
                if signal not in families.get("content_signal", frozenset()):
                    errors.append(self._error("story_patterns", row.sheet_row,
                                              "required_content_signals",
                                              "unknown_content_signal",
                                              "Story content signal is not registered."))

    @staticmethod
    def _validate_generation_condition(
        errors: list[ErrorDetail],
        row: Any,
        input_facts: dict[str, set[str]],
        families: dict[str, frozenset[Any]],
    ) -> None:
        condition = (row.generation_condition or "").strip()
        if not condition:
            return
        if row.field_role not in {"direct_acf", "aggregation_source"}:
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "generation_condition",
                "generation_condition_not_allowed",
                "Generation conditions are only allowed on generated ACF output fields.",
            ))
        if condition.count(":") != 1:
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "generation_condition",
                "invalid_generation_condition_format",
                "Use prefix:value syntax, for example fact_present:challenge.",
            ))
            return
        prefix, raw_values = (part.strip() for part in condition.split(":", 1))
        values = tuple(part.strip() for part in raw_values.split(";") if part.strip())
        allowed_prefixes = {"content_signal", "context_tag", "fact_present", "fact_present_any"}
        if prefix not in allowed_prefixes:
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "generation_condition",
                "unknown_generation_condition_type",
                "Generation condition type is not registered.",
            ))
            return
        if not values:
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "generation_condition",
                "empty_generation_condition_value",
                "Generation condition needs at least one value.",
            ))
            return
        if len(set(values)) != len(values):
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "generation_condition",
                "duplicate_generation_condition_value",
                "Generation condition values must be unique.",
            ))
        if prefix in {"content_signal", "context_tag", "fact_present"} and len(values) != 1:
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "generation_condition",
                "too_many_generation_condition_values",
                "This generation condition type expects exactly one value.",
            ))
        if prefix == "content_signal":
            WorkbookValidator._validate_condition_values(
                errors, row, values, families.get("content_signal", frozenset()), "unknown_content_signal"
            )
        elif prefix == "context_tag":
            WorkbookValidator._validate_condition_values(
                errors, row, values, families.get("context_tag", frozenset()), "unknown_context_tag"
            )
        else:
            known_facts = input_facts[row.post_type_key]
            for value in values:
                if value not in known_facts:
                    errors.append(WorkbookValidator._error(
                        "ACF_fields_schema",
                        row.sheet_row,
                        "generation_condition",
                        "unknown_generation_condition_fact",
                        "Generation condition fact does not resolve for the same post type.",
                    ))

    @staticmethod
    def _validate_condition_values(
        errors: list[ErrorDetail],
        row: Any,
        values: tuple[str, ...],
        allowed_values: frozenset[Any],
        error_code: str,
    ) -> None:
        for value in values:
            if value not in allowed_values:
                errors.append(WorkbookValidator._error(
                    "ACF_fields_schema",
                    row.sheet_row,
                    "generation_condition",
                    error_code,
                    "Generation condition value is not registered.",
                ))

    @staticmethod
    def _validate_image_metadata_context_flag(errors: list[ErrorDetail], row: Any) -> None:
        if row.include_in_image_metadata_context is not True:
            return
        if row.field_role != "input_fact":
            errors.append(WorkbookValidator._error(
                "ACF_fields_schema",
                row.sheet_row,
                "include_in_image_metadata_context",
                "image_metadata_context_flag_not_allowed",
                "Only input facts can be exposed as image-metadata context.",
            ))

    @staticmethod
    def _validate_image_metadata_rules(
        errors: list[ErrorDetail],
        snapshot: WorkbookSnapshot,
        post_types: dict[str, Any],
        input_facts: dict[str, set[str]],
        image_metadata_keys: set[str],
        families: dict[str, frozenset[Any]],
    ) -> None:
        required_families = {
            "image_metadata_trigger_type": "trigger_type",
            "image_metadata_usage_mode": "usage_mode",
        }
        for family, column in required_families.items():
            if family not in families:
                errors.append(WorkbookValidator._error(
                    "validation_lists",
                    1,
                    "list_name",
                    f"missing_{family}",
                    f"Validation-list family {family!r} is required by image_metadata_rules.{column}.",
                ))

        workflow_stages = {row.step_key for row in snapshot.workflow_steps}.union({"all", "image_metadata"})
        enabled_analysis = {row.analysis_key: row for row in snapshot.image_analysis_rules if row.enabled}
        enabled_post_types = {key for key, row in post_types.items() if row.enabled}

        for row in snapshot.image_metadata_rules:
            if not row.enabled:
                continue
            if row.post_type_key != "*" and row.post_type_key not in post_types:
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "post_type_key",
                    "unknown_post_type",
                    "Image metadata rule post type does not resolve.",
                ))
            if row.workflow_stage not in workflow_stages:
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "workflow_stage",
                    "unknown_workflow_stage",
                    "Image metadata rule workflow stage is not registered.",
                ))
            if row.trigger_type not in families.get("image_metadata_trigger_type", frozenset()):
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "trigger_type",
                    "unknown_image_metadata_trigger_type",
                    "Image metadata trigger type is not registered.",
                ))
            if row.usage_mode not in families.get("image_metadata_usage_mode", frozenset()):
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "usage_mode",
                    "unknown_image_metadata_usage_mode",
                    "Image metadata usage mode is not registered.",
                ))
            if row.priority not in families.get("priority", frozenset()):
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "priority",
                    "unknown_priority",
                    "Image metadata rule priority is not registered.",
                ))
            for field_key in row.target_field_keys:
                if field_key not in image_metadata_keys:
                    errors.append(WorkbookValidator._error(
                        "image_metadata_rules",
                        row.sheet_row,
                        "target_field_keys",
                        "unknown_image_metadata_target_field",
                        "Image metadata target field does not resolve.",
                    ))
            applicable_post_types = (
                enabled_post_types
                if row.post_type_key == "*"
                else {row.post_type_key}
            )
            for fact_key in row.source_fact_keys:
                if not any(fact_key in input_facts[post_type_key] for post_type_key in applicable_post_types):
                    errors.append(WorkbookValidator._error(
                        "image_metadata_rules",
                        row.sheet_row,
                        "source_fact_keys",
                        "unknown_image_metadata_source_fact",
                        "Image metadata source fact does not resolve for the rule post type.",
                    ))
            WorkbookValidator._validate_image_metadata_trigger(errors, row, enabled_analysis, families)

    @staticmethod
    def _validate_image_metadata_trigger(
        errors: list[ErrorDetail],
        row: Any,
        enabled_analysis: dict[str, Any],
        families: dict[str, frozenset[Any]],
    ) -> None:
        if row.trigger_type == "always":
            if row.trigger_key or row.trigger_value:
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "trigger_key",
                    "invalid_always_trigger_configuration",
                    "Always-triggered image metadata rules must not define trigger_key or trigger_value.",
                ))
            return
        if row.trigger_type == "image_analysis_contains":
            analysis_rule = enabled_analysis.get(row.trigger_key or "")
            if analysis_rule is None:
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "trigger_key",
                    "unknown_image_analysis_trigger_key",
                    "Image metadata trigger key does not resolve to an enabled image-analysis rule.",
                ))
                return
            if not analysis_rule.output_domain:
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "trigger_key",
                    "image_analysis_trigger_without_domain",
                    "Image-analysis triggers need an output_domain so trigger values can be validated.",
                ))
                return
            for value in row.trigger_value:
                if value not in families.get(analysis_rule.output_domain, frozenset()):
                    errors.append(WorkbookValidator._error(
                        "image_metadata_rules",
                        row.sheet_row,
                        "trigger_value",
                        "unknown_image_analysis_trigger_value",
                        "Image metadata trigger value is not allowed by the image-analysis output domain.",
                    ))
            return
        if row.trigger_type in {"content_signal", "context_tag"}:
            if row.trigger_key:
                errors.append(WorkbookValidator._error(
                    "image_metadata_rules",
                    row.sheet_row,
                    "trigger_key",
                    "unexpected_image_metadata_trigger_key",
                    "Content-signal and context-tag triggers use trigger_value only.",
                ))
            family_name = row.trigger_type
            for value in row.trigger_value:
                if value not in families.get(family_name, frozenset()):
                    errors.append(WorkbookValidator._error(
                        "image_metadata_rules",
                        row.sheet_row,
                        "trigger_value",
                        f"unknown_{family_name}",
                        "Image metadata trigger value is not registered.",
                    ))

    @staticmethod
    def _validate_internal_links(errors: list[ErrorDetail], snapshot: WorkbookSnapshot) -> None:
        seen_urls: dict[str, int] = {}
        for row in snapshot.internal_links:
            if not row.active:
                continue
            if row.target_url == "TBD":
                errors.append(WorkbookValidator._error(
                    "internal_links_database", row.sheet_row, "target_url",
                    "active_tbd_url", "Active internal-link URLs cannot be TBD.",
                ))
            if row.target_url in seen_urls:
                errors.append(WorkbookValidator._error(
                    "internal_links_database", row.sheet_row, "target_url",
                    "duplicate_active_url",
                    f"Active URL was first declared on row {seen_urls[row.target_url]}.",
                ))
            seen_urls[row.target_url] = row.sheet_row

    @staticmethod
    def _validate_state_machine(errors: list[ErrorDetail], snapshot: WorkbookSnapshot) -> None:
        states = {row.state for row in snapshot.application_states}
        for row in snapshot.application_states:
            for next_state in row.allowed_next_states:
                if next_state not in states:
                    errors.append(WorkbookValidator._error(
                        "application_state", row.sheet_row, "allowed_next_states",
                        "unknown_next_state", f"State {next_state!r} does not exist.",
                    ))

    @staticmethod
    def _validate_output_specification(
        errors: list[ErrorDetail],
        snapshot: WorkbookSnapshot,
    ) -> None:
        settings = {
            row.setting_key: row.value
            for row in snapshot.output_specifications
            if row.enabled
        }
        expected = {
            "no_zip_input": True,
            "no_zip_output": True,
            "draft_output": "structured_json",
        }
        for key, value in expected.items():
            if settings.get(key) != value:
                errors.append(WorkbookValidator._error(
                    "output_specification",
                    next(
                        (
                            row.sheet_row
                            for row in snapshot.output_specifications
                            if row.setting_key == key
                        ),
                        1,
                    ),
                    "value",
                    "invalid_v2_output_mode",
                    f"{key} must equal {value!r} for the V2 pipeline.",
                ))

    @staticmethod
    def _validate_aggregation_groups(
        errors: list[ErrorDetail],
        rows: tuple[Any, ...],
    ) -> None:
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for row in rows:
            if row.field_role == "aggregation_source" and row.aggregation_group:
                groups[(row.post_type_key, row.aggregation_group)].append(row)
        for (_post_type, _group), group_rows in groups.items():
            destinations = {row.acf_field_name for row in group_rows}
            if len(destinations) != 1:
                for row in group_rows:
                    errors.append(WorkbookValidator._error(
                        "ACF_fields_schema",
                        row.sheet_row,
                        "acf_field_name",
                        "inconsistent_aggregation_destination",
                        "Rows in one aggregation group must share one ACF destination.",
                    ))
            orders: dict[int | None, int] = {}
            for row in group_rows:
                order = row.aggregation_order
                if order in orders:
                    errors.append(WorkbookValidator._error(
                        "ACF_fields_schema",
                        row.sheet_row,
                        "aggregation_order",
                        "duplicate_aggregation_order",
                        f"Aggregation order was first used on row {orders[order]}.",
                    ))
                orders[order] = row.sheet_row

    @staticmethod
    def _error(sheet: str, row: int, column: str, error_code: str, message: str) -> ErrorDetail:
        return ErrorDetail(
            sheet=sheet,
            row=row,
            column=column,
            error_code=error_code,
            message=message,
        )
