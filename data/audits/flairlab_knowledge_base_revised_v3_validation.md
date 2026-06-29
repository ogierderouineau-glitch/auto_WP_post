# FLAIRLAB Knowledge Base Revised V3 Validation

- Workbook: `/home/ogier-derouineau/Downloads/FLAIRLAB_Knowledge_Base_Revised_V3.xlsm`
- SHA-256: `365dbb8b049784077d680042952d1f0afdf2e5399c13846ec70d96de0da71a70`
- Total findings: **77**
- definite_error: **2**
- warning: **0**
- architectural_decision: **10**
- valid_by_design: **65**

## True Blockers

- `missing_example_post_type` — post_examples, row 6, `post_type_key`: Example cannot be partitioned by post type.
- `unresolved_style_section` — style_rules, row 2, `match_value`: Section rule does not resolve to a schema section.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 18, `source_mode`: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 19, `source_mode`: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 20, `source_mode`: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 21, `source_mode`: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 22, `source_mode`: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance.
- `optional_image_step_required` — agent_workflow, row 16, `required`: Image metadata generation is required while images are optional.
- `pillow_enum_domain_contract` — image_rules_pillow, row 14, `value_type`: crop.mode is typed enum, but image_rules_pillow has no domain-reference column and validation_lists has no crop_mode family. Strict validation cannot prove that cover is allowed.
- `optional_image_step_required` — post_blueprint, row 11, `required`: Gallery layout is required while photos_min=0.
- `optional_image_step_required` — post_blueprint, row 6, `required`: Featured image caption is required while photos_min=0.
- `related_links_empty_contract` — shared_fields_schema, row 13, `required_for_output`: Internal-link rules correctly allow no link, but the required field has no validation rule explaining that an empty value is valid when no candidate survives filtering.

## Non-Blocking Warnings

- None.

## Architectural Decisions

- `required_fact_source_mapping_missing` — ACF_fields_schema, row 18: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. Recommendation: Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 19: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. Recommendation: Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 20: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. Recommendation: Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 21: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. Recommendation: Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows.
- `required_fact_source_mapping_missing` — ACF_fields_schema, row 22: The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. Recommendation: Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows.
- `optional_image_step_required` — agent_workflow, row 16: Image metadata generation is required while images are optional. Recommendation: Approve conditional requiredness semantics, or make the row/step optional.
- `pillow_enum_domain_contract` — image_rules_pillow, row 14: crop.mode is typed enum, but image_rules_pillow has no domain-reference column and validation_lists has no crop_mode family. Strict validation cannot prove that cover is allowed. Recommendation: Approve adding value_domain (for example crop_mode) and the corresponding validation list before implementation.
- `optional_image_step_required` — post_blueprint, row 11: Gallery layout is required while photos_min=0. Recommendation: Approve conditional requiredness semantics, or make the row/step optional.
- `optional_image_step_required` — post_blueprint, row 6: Featured image caption is required while photos_min=0. Recommendation: Approve conditional requiredness semantics, or make the row/step optional.
- `related_links_empty_contract` — shared_fields_schema, row 13: Internal-link rules correctly allow no link, but the required field has no validation rule explaining that an empty value is valid when no candidate survives filtering. Recommendation: Add an explicit validation_rule such as allow_empty_if_no_eligible_links.

## Definite Errors

| Sheet | Row | Column | Current value | Expected | Severity | Code | Reason | Recommended correction |
|---|---:|---|---|---|---|---|---|---|
| post_examples | 6 | post_type_key | None | Existing post_types.post_type_key | error | missing_example_post_type | Example cannot be partitioned by post type. | Set the correct post_type_key. |
| style_rules | 2 | match_value | hero_intro | Existing ACF_fields_schema.section | error | unresolved_style_section | Section rule does not resolve to a schema section. | Use match_type=field for hero_intro, or target section=hero. |

## Warnings

| Sheet | Row | Column | Current value | Expected | Severity | Code | Reason | Recommended correction |
|---|---:|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | No findings. | — |

## Architectural Decisions Requiring Approval

| Sheet | Row | Column | Current value | Expected | Severity | Code | Reason | Recommended correction |
|---|---:|---|---|---|---|---|---|---|
| ACF_fields_schema | 18 | source_mode | derived_from_facts | Explicit deterministic source-fact dependency: event_year/event_month/event_date or event_type | decision | required_fact_source_mapping_missing | The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. | Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows. |
| ACF_fields_schema | 19 | source_mode | derived_from_facts | Explicit deterministic source-fact dependency: event_date or event_year/event_month | decision | required_fact_source_mapping_missing | The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. | Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows. |
| ACF_fields_schema | 20 | source_mode | derived_from_facts | Explicit deterministic source-fact dependency: venue/city | decision | required_fact_source_mapping_missing | The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. | Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows. |
| ACF_fields_schema | 21 | source_mode | derived_from_facts | Explicit deterministic source-fact dependency: event_type | decision | required_fact_source_mapping_missing | The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. | Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows. |
| ACF_fields_schema | 22 | source_mode | derived_from_facts | Explicit deterministic source-fact dependency: service_type | decision | required_fact_source_mapping_missing | The row is correctly required, but no column explicitly identifies which confirmed input_fact keys satisfy it. Python must not infer this from names or guidance. | Approve adding source_fact_keys (or an equivalent typed dependency column) to required derived_from_facts rows. |
| agent_workflow | 16 | required | True | Conditional requirement when at least one image exists | decision | optional_image_step_required | Image metadata generation is required while images are optional. | Approve conditional requiredness semantics, or make the row/step optional. |
| image_rules_pillow | 14 | value_type | enum | A declared controlled domain for enum-valued Pillow rules | decision | pillow_enum_domain_contract | crop.mode is typed enum, but image_rules_pillow has no domain-reference column and validation_lists has no crop_mode family. Strict validation cannot prove that cover is allowed. | Approve adding value_domain (for example crop_mode) and the corresponding validation list before implementation. |
| post_blueprint | 11 | required | True | Conditional requirement when at least one image exists | decision | optional_image_step_required | Gallery layout is required while photos_min=0. | Approve conditional requiredness semantics, or make the row/step optional. |
| post_blueprint | 6 | required | True | Conditional requirement when at least one image exists | decision | optional_image_step_required | Featured image caption is required while photos_min=0. | Approve conditional requiredness semantics, or make the row/step optional. |
| shared_fields_schema | 13 | required_for_output | True | Required field with explicit allow-empty-if-no-eligible-links semantics | decision | related_links_empty_contract | Internal-link rules correctly allow no link, but the required field has no validation rule explaining that an empty value is valid when no candidate survives filtering. | Add an explicit validation_rule such as allow_empty_if_no_eligible_links. |

## Valid By Design

| Sheet | Row | Column | Current value | Expected | Severity | Code | Reason | Recommended correction |
|---|---:|---|---|---|---|---|---|---|
| ACF_fields_schema | 15 | field_key | hero_h1 | {'field_role': 'direct_acf', 'acf_field_name': 'hero_h1', 'include_in_payload': True} | info | required_acf_contract_valid | hero_h1 is a direct ACF payload field as required. | None |
| ACF_fields_schema | 18-27 | required_for_output | Rows 18-22 TRUE; rows 23-27 FALSE | Required and optional fakten sources | info | fact_requiredness_valid | Required facts trigger clarification; optional fact items may be skipped. | None |
| ACF_fields_schema | 30 | field_key | verlauf_h2 | {'field_role': 'direct_acf', 'acf_field_name': 'verlauf_h2', 'include_in_payload': True} | info | required_acf_contract_valid | verlauf_h2 is a direct ACF payload field as required. | None |
| README | 16 | single_template_url | User reference | Not runtime configuration | info | runtime_boundary_documented | Workbook explicitly documents single_template_url as user-reference metadata. | None |
| agent_instructions | 13 | instruction_id | analysis_003 | Bundled required-fact clarification | info | clarification_instruction_valid | The model asks bundled questions only for missing required dependencies. | None |
| agent_workflow | 5 | required | False | Optional transcription | info | transcription_optional_valid | Audio is transcribed when present and skipped for manual-text-only sessions. | None |
| agent_workflow | 8 | input | post_facts_json + ACF_fields_schema.required_for_analysis + required output source facts | Required analysis and output source facts | info | clarification_workflow_valid | Clarification is explicitly bundled before dependent generation. | None |
| api_contract | 2-13 | runtime dependency | Temporary implementation guidance | Not required at runtime after implementation | info | api_contract_temporary_valid | API contract is correctly categorized as temporary guidance. | None |
| context_building | 11 | filter_expression | active=TRUE AND target_url!=TBD AND (post_type_key=* OR post_type_key={post_type_key}) AND canonical_path(target_url)!={current_path} | Canonical target_url path filtering | info | canonical_path_filter_valid | Self-link filtering derives its canonical path from target_url. | None |
| context_building | 13 | filter_expression | enabled=TRUE AND condition satisfied | Known typed filter handler, never eval() | info | typed_filter_manifest_valid | The expression is declarative documentation and must map to a registered typed handler. | None |
| context_building | 6 | filter_expression | enabled=TRUE AND (post_type_key=* OR post_type_key={post_type_key}) AND stage={stage} AND target matches requested field/group | Known typed filter handler, never eval() | info | typed_filter_manifest_valid | The expression is declarative documentation and must map to a registered typed handler. | None |
| context_building | 7 | filter_expression | enabled=TRUE AND (post_type_key=* OR post_type_key={post_type_key}) AND match(global OR current section OR detected tags) | Known typed filter handler, never eval() | info | typed_filter_manifest_valid | The expression is declarative documentation and must map to a registered typed handler. | None |
| context_building | 8 | filter_expression | enabled=TRUE AND post_type_key={post_type_key} AND trigger_tags intersects {context_tags} AND required_facts available | Known typed filter handler, never eval() | info | typed_filter_manifest_valid | The expression is declarative documentation and must map to a registered typed handler. | None |
| implementation_notes | 2-17 | runtime dependency | Temporary implementation guidance | Traceability source, not runtime data | info | implementation_notes_temporary_valid | Implementation notes are correctly separated from runtime configuration. | None |
| internal_link_rules | 2 | value | 2;4 | Parseable 2..4 range | info | link_range_valid | Minimum and maximum link count are structurally parseable. | None |
| internal_links_database | 1 | target_slug | None | Column absent | info | target_slug_removed | Canonical self-link paths are derived from target_url; no duplicated slug column exists. | None |
| post_blueprint | 10 | target_key | verlauf_text | Exact aggregation_group target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 12 | target_key | faq | Exact section target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 13 | target_key | cta_h2 | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 14 | target_key | cta_text | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 15 | target_key | related_links_html | Exact shared_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 2 | target_key | hero_h1 | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 3 | target_key | hero_h2 | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 4 | target_key | hero_intro | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 5 | target_key | fakten | Exact aggregation_group target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 6 | target_key | image_caption | Exact image_metadata_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 7 | target_key | event_story_h2 | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 8 | target_key | event_story | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_blueprint | 9 | target_key | verlauf_h2 | Exact acf_field target | info | blueprint_target_valid | Enabled blueprint row resolves in exactly its declared namespace. | None |
| post_examples | 1 | post_type | None | Column absent | info | redundant_post_type_removed | The redundant post_type column is absent; post_type_key is authoritative. | None |
| post_examples | 2-6 | content | Approved historical examples | Style/context reference only | info | examples_reference_only | Examples are filtered context references and never authoritative current-post facts. | None |
| post_types | 2 | single_template_url | Event post template URL | User-facing reference only | info | single_template_url_reference_only | This value is intentionally excluded from runtime routing and startup validity. | None |
| post_types | 3 | single_template_url | TBD | User-facing reference only | info | single_template_url_reference_only | This value is intentionally excluded from runtime routing and startup validity. | None |
| post_types | 4 | single_template_url | TBD | User-facing reference only | info | single_template_url_reference_only | This value is intentionally excluded from runtime routing and startup validity. | None |
| post_types | 5 | single_template_url | TBD | User-facing reference only | info | single_template_url_reference_only | This value is intentionally excluded from runtime routing and startup validity. | None |
| seo_rules | 10 | target_key | slug | Resolved field target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 11 | target_key | internal_link_primary | Resolved internal_links target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 12 | target_key | internal_link_secondary | Resolved internal_links target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 13 | target_key | internal_link_contextual | Resolved internal_links target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 14 | target_key | all_content | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 15 | target_key | all_content | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 16 | target_key | all_content | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 17 | target_key | all_content | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 18 | target_key | all_content | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 19 | target_key | faq | Resolved section target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 2 | target_key | focus_keyword | Resolved field target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 20 | target_key | faq | Resolved section target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 21 | target_key | seo | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 22 | target_key | seo | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 23 | target_key | seo | Resolved draft_validation target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 24 | target_key | yoast | Resolved group target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 25 | target_key | image_alt | Resolved image_metadata target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 26 | target_key | internal_link_count | Resolved internal_links target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 3 | target_key | keyword | Resolved group target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 4 | target_key | keyword | Resolved group target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 5 | target_key | keyword | Resolved group target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 6 | target_key | seo_title | Resolved field target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 7 | target_key | meta_description | Resolved field target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 8 | target_key | social_title | Resolved field target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| seo_rules | 9 | target_key | social_description | Resolved field target | info | seo_target_valid | SEO target resolves according to its declared type. | None |
| shared_fields_schema | 13 | field_key | related_links_html | {'destination_type': 'acf', 'destination_key': 'related_links_html', 'generation_stage': 'internal_links', 'include_in_ai_schema': False, 'include_in_payload': True} | info | required_shared_field_valid | related_links_html satisfies its explicit routing and ownership contract. | None |
| shared_fields_schema | 5 | field_key | status | {'source_mode': 'configured', 'include_in_ai_schema': False, 'format_or_enum': 'publish_status'} | info | required_shared_field_valid | status satisfies its explicit routing and ownership contract. | None |
| shared_fields_schema | 6 | field_key | category | {'source_mode': 'configured', 'include_in_ai_schema': False, 'value_type': 'string'} | info | required_shared_field_valid | category satisfies its explicit routing and ownership contract. | None |
| story_patterns | 7 | semantic_prompt_hints | challenge; decision; implementation; result | Narrative concepts, not fact keys | info | semantic_hints_valid | semantic_prompt_hints are correctly treated as narrative guidance. | None |
| tab_legend | 2-5 | primary purpose | Green/Blue/Purple/Red ownership | Separated runtime and temporary guidance | info | workbook_ownership_boundaries_valid | Workbook clearly separates user data, runtime configuration, AI context, and temporary implementation guidance. | None |
