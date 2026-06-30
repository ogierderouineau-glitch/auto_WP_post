from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkbookRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    sheet_row: int = Field(exclude=True)


class PostTypeConfig(WorkbookRow):
    post_type_key: str
    display_name_de: str
    enabled: bool
    development_status: str
    wp_post_type: str
    wp_category_name: str
    single_template_url: str | None = None
    default_language: str
    default_status: str
    template_ready: bool
    generation_enabled: bool
    image_rules_profile: str
    seo_profile: str
    description_de: str
    user_selectable: bool


class SharedFieldSchema(WorkbookRow):
    field_key: str
    group: str
    destination_type: str
    destination_key: str
    description_de: str
    required_for_output: bool
    value_type: str
    format_or_enum: str | None = None
    min_words: int | None = None
    max_words: int | None = None
    min_characters: int | None = None
    max_characters: int | None = None
    generation_stage: str
    source_mode: str
    include_in_ai_schema: bool
    include_in_payload: bool
    example: Any = None
    validation_rule: str | None = None
    enabled: bool


class ACFFieldSchema(WorkbookRow):
    post_type_key: str
    field_key: str
    field_role: str
    acf_field_name: str | None = None
    aggregation_group: str | None = None
    aggregation_order: int | None = None
    transform_key: str | None = None
    group: str | None = None
    section: str | None = None
    description_de: str
    required_for_analysis: bool
    required_for_output: bool
    value_type: str
    format_or_enum: str | None = None
    min_words: int | None = None
    max_words: int | None = None
    generation_stage: str
    source_mode: str
    source_fact_keys: tuple[str, ...] = ()
    guidance_de: str | None = None
    example: Any = None
    generation_condition: str | None = None
    include_in_image_metadata_context: bool | None = None
    validation_rule: str | None = None
    include_in_ai_schema: bool
    include_in_payload: bool
    enabled: bool


class BlueprintRow(WorkbookRow):
    post_type_key: str
    section_order: int
    target_type: str
    target_key: str
    page_area: str
    purpose: str
    required: bool
    display_condition: str
    source_type: str
    content_role: str
    target_paragraphs: int | None = None
    example: Any = None
    enabled: bool


class SEORule(WorkbookRow):
    rule_id: str
    enabled: bool
    post_type_key: str
    target_type: str
    target_key: str
    stage: str
    action_type: str
    instruction_de: str
    value: Any = None
    value_type: str
    condition: str
    priority: str
    example: Any = None
    source: str
    context_tags: tuple[str, ...] = ()


class StyleRule(WorkbookRow):
    rule_id: str
    enabled: bool
    post_type_key: str
    match_type: str
    match_value: str
    applies_to: str
    instruction_de: str
    priority: str
    owner: str
    condition: str


class StoryPattern(WorkbookRow):
    pattern_id: str
    enabled: bool
    post_type_key: str
    trigger_tags: tuple[str, ...] = ()
    required_facts: tuple[str, ...] = ()
    required_content_signals: tuple[str, ...] = ()
    excluded_tags: tuple[str, ...] = ()
    angle_de: str
    use_when_de: str
    prompt_fragment_de: str
    semantic_prompt_hints: tuple[str, ...] = ()
    avoid_de: str
    priority: str
    max_patterns: int


class ImageAnalysisRule(WorkbookRow):
    rule_id: str
    enabled: bool
    analysis_key: str
    intent_de: str
    owner: str
    condition: str
    priority: str
    expected_output: str
    output_domain: str | None = None
    used_by: str
    fallback: str


class PillowRule(WorkbookRow):
    rule_key: str
    enabled: bool
    engine: str
    stage: str
    operation: str
    parameter: str
    value: Any
    value_type: str
    value_domain: str | None = None
    unit: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    condition: str
    priority: str
    numeric_priority: int
    fallback_engine: str
    notes: str | None = None


class ImageMetadataField(WorkbookRow):
    field_key: str
    destination_type: str
    destination_key: str
    description_de: str
    required: bool
    value_type: str
    generation_stage: str
    source_mode: str
    validation_rule: str | None = None
    example: Any = None
    enabled: bool


class ImageMetadataRule(WorkbookRow):
    rule_id: str
    enabled: bool
    post_type_key: str
    workflow_stage: str
    trigger_type: str
    trigger_key: str | None = None
    trigger_value: tuple[str, ...] = ()
    source_fact_keys: tuple[str, ...] = ()
    target_field_keys: tuple[str, ...] = ()
    usage_mode: str
    priority: str
    instruction_de: str
    notes_de: str | None = None


class InternalLinkRecord(WorkbookRow):
    link_id: str
    post_type_key: str
    keyword: str
    anchor_text: str
    anchor_variants: tuple[str, ...] = ()
    target_url: str
    link_role: str
    category: str
    priority: str
    active: bool
    usage_context: str
    city: str | None = None
    language: str
    notes: str | None = None


class InternalLinkRule(WorkbookRow):
    rule_id: str
    enabled: bool
    owner: str
    action_type: str
    applies_to: str
    operator: str
    value: Any
    value_type: str
    instruction_de: str
    priority: str


class WorkflowStep(WorkbookRow):
    step_order: int
    step_key: str
    owner: str
    input: str
    action_de: str
    output: str
    required: bool
    run_condition: str
    failure_action_de: str


class ApplicationState(WorkbookRow):
    state: str
    terminal: bool
    allowed_next_states: tuple[str, ...] = ()
    entered_when_de: str
    required_data: tuple[str, ...] = ()
    ui_behavior_de: str


class AgentInstruction(WorkbookRow):
    instruction_id: str
    enabled: bool
    scope: str
    post_type_key: str
    workflow_stage: str
    applies_to: str
    owner: str
    priority: str
    condition: str
    instruction_de: str
    expected_behavior: str
    conflict_policy: str
    source_reference: str
    notes_de: str | None = None


class ContextManifestRow(WorkbookRow):
    context_stage: str
    source_sheet: str
    filter_expression: str
    sort_order: str
    max_items: int | None = None
    output_key: str
    owner: str
    required: bool
    purpose_de: str


class ValidationListValue(WorkbookRow):
    list_name: str
    allowed_value: Any
    description_de: str


class PostExample(WorkbookRow):
    post_type_key: str
    example_id: str
    enabled: bool
    approved: bool
    quality_score: float


class OutputSpecification(WorkbookRow):
    setting_key: str
    enabled: bool
    value: Any
    value_type: str
    required: bool
    description_de: str
    example: Any = None
    validation_rule: str | None = None


class WorkbookVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    sha256: str
    loaded_at: datetime
    schema_version: str | None = None


class WorkbookSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    version: WorkbookVersion
    post_types: tuple[PostTypeConfig, ...]
    shared_fields: tuple[SharedFieldSchema, ...]
    acf_fields: tuple[ACFFieldSchema, ...]
    blueprint: tuple[BlueprintRow, ...]
    seo_rules: tuple[SEORule, ...]
    style_rules: tuple[StyleRule, ...]
    story_patterns: tuple[StoryPattern, ...]
    image_analysis_rules: tuple[ImageAnalysisRule, ...]
    pillow_rules: tuple[PillowRule, ...]
    image_metadata_fields: tuple[ImageMetadataField, ...]
    image_metadata_rules: tuple[ImageMetadataRule, ...]
    internal_links: tuple[InternalLinkRecord, ...]
    internal_link_rules: tuple[InternalLinkRule, ...]
    workflow_steps: tuple[WorkflowStep, ...]
    application_states: tuple[ApplicationState, ...]
    agent_instructions: tuple[AgentInstruction, ...]
    context_manifest: tuple[ContextManifestRow, ...]
    validation_values: tuple[ValidationListValue, ...]
    post_examples: tuple[PostExample, ...]
    output_specifications: tuple[OutputSpecification, ...]

    def validation_family(self, name: str) -> frozenset[Any]:
        return frozenset(row.allowed_value for row in self.validation_values if row.list_name == name)

    def post_type(self, post_type_key: str) -> PostTypeConfig | None:
        return next((row for row in self.post_types if row.post_type_key == post_type_key), None)
