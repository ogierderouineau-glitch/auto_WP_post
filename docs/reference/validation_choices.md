# Validation Choices

- Generated at: 2026-07-29T17:17:13.496507+00:00
- Workbook: FLAIRLAB_Knowledge_Base_Revised_V7.xlsm
- Workbook SHA-256: 066e85552effea2c08a360146734ab4764bb9fbec6f4e04a4be3f613e5aef3d0

This file is generated from the loaded workbook snapshot.

## action_type

| # | allowed_value |
|---|---|
| 1 | `"generator"` |
| 2 | `"validator"` |
| 3 | `"instruction"` |
| 4 | `"constraint"` |

## blueprint_target_type

| # | allowed_value |
|---|---|
| 1 | `"acf_field"` |
| 2 | `"aggregation_group"` |
| 3 | `"group"` |
| 4 | `"section"` |
| 5 | `"shared_field"` |
| 6 | `"image_metadata_field"` |
| 7 | `"layout_marker"` |

## boolean

| # | allowed_value |
|---|---|
| 1 | `true` |
| 2 | `false` |

## client_type

| # | allowed_value |
|---|---|
| 1 | `"company"` |
| 2 | `"private"` |
| 3 | `"event_agency"` |
| 4 | `"brand"` |
| 5 | `"hotel"` |
| 6 | `"media_production"` |
| 7 | `"other"` |

## conflict_policy

| # | allowed_value |
|---|---|
| 1 | `"higher_priority_wins"` |
| 2 | `"schema_wins"` |
| 3 | `"specific_over_global"` |
| 4 | `"confirmed_user_input_wins"` |
| 5 | `"user_request_wins"` |
| 6 | `"facts_override_examples"` |
| 7 | `"database_only"` |
| 8 | `"image_analysis_wins"` |

## content_signal

| # | allowed_value |
|---|---|
| 1 | `"challenge_present"` |
| 2 | `"solution_present"` |
| 3 | `"highlight_present"` |
| 4 | `"atmosphere_present"` |

## context_tag

| # | allowed_value |
|---|---|
| 1 | `"promotion"` |
| 2 | `"retail"` |
| 3 | `"luxury_hotel"` |
| 4 | `"media_tv"` |
| 5 | `"corporate"` |
| 6 | `"showbartending"` |
| 7 | `"challenge_solution"` |

## crop_mode

| # | allowed_value |
|---|---|
| 1 | `"cover"` |
| 2 | `"contain"` |
| 3 | `"preserve"` |

## destination_type

| # | allowed_value |
|---|---|
| 1 | `"wordpress"` |
| 2 | `"yoast"` |
| 3 | `"acf"` |
| 4 | `"media"` |

## display_condition

| # | allowed_value |
|---|---|
| 1 | `"always"` |
| 2 | `"image_count_gt_0"` |

## field_role

| # | allowed_value |
|---|---|
| 1 | `"input_fact"` |
| 2 | `"derived_field"` |
| 3 | `"direct_acf"` |
| 4 | `"aggregation_source"` |
| 5 | `"generated_field"` |

## gallery_role

| # | allowed_value |
|---|---|
| 1 | `"overview"` |
| 2 | `"action"` |
| 3 | `"cocktail"` |
| 4 | `"bartender"` |
| 5 | `"guests"` |
| 6 | `"branding"` |
| 7 | `"detail"` |

## generation_condition_type

| # | allowed_value |
|---|---|
| 1 | `"always"` |
| 2 | `"content_signal"` |
| 3 | `"context_tag"` |
| 4 | `"fact_present"` |
| 5 | `"fact_present_any"` |

## generation_stage

| # | allowed_value |
|---|---|
| 1 | `"fact_extraction"` |
| 2 | `"content_generation"` |
| 3 | `"seo_generation"` |
| 4 | `"internal_links"` |
| 5 | `"image_selection"` |
| 6 | `"image_metadata"` |
| 7 | `"payload_construction"` |

## image_analysis_output

| # | allowed_value |
|---|---|
| 1 | `"short_text"` |
| 2 | `"integer_0_100"` |
| 3 | `"enum"` |
| 4 | `"normalized_focal_point_or_none"` |
| 5 | `"float_or_zero"` |
| 6 | `"low|medium|high"` |
| 7 | `"short_text_or_none"` |
| 8 | `"group_id_or_none"` |
| 9 | `"boolean_with_reason"` |
| 10 | `"enum_list"` |

## image_edit_mode

| # | allowed_value |
|---|---|
| 1 | `"local"` |
| 2 | `"selective"` |
| 3 | `"ai_all"` |

## image_metadata_trigger_type

| # | allowed_value |
|---|---|
| 1 | `"always"` |
| 2 | `"image_analysis_contains"` |
| 3 | `"content_signal"` |
| 4 | `"context_tag"` |

## image_metadata_usage_mode

| # | allowed_value |
|---|---|
| 1 | `"allow"` |
| 2 | `"prefer_when_natural"` |
| 3 | `"require_when_visible_and_confirmed"` |
| 4 | `"exclude"` |

## image_visible_action

| # | allowed_value |
|---|---|
| 1 | `"cocktail_preparation"` |
| 2 | `"showbartending"` |
| 3 | `"flair_bartending"` |
| 4 | `"serving_drinks"` |
| 5 | `"guest_interaction"` |
| 6 | `"branding_activation"` |

## image_visible_role

| # | allowed_value |
|---|---|
| 1 | `"bartender"` |
| 2 | `"bar_team_member"` |
| 3 | `"guest"` |
| 4 | `"client_representative"` |
| 5 | `"product"` |
| 6 | `"venue"` |
| 7 | `"cocktail"` |
| 8 | `"bar"` |

## knowledge_enrichment

| # | allowed_value |
|---|---|
| 1 | `"forbidden"` |
| 2 | `"allowed"` |

## match_type

| # | allowed_value |
|---|---|
| 1 | `"global"` |
| 2 | `"section"` |
| 3 | `"event_context"` |
| 4 | `"content_signal"` |
| 5 | `"post_type"` |
| 6 | `"field"` |

## owner

| # | allowed_value |
|---|---|
| 1 | `"application"` |
| 2 | `"language_model"` |
| 3 | `"speech_to_text"` |
| 4 | `"pillow"` |
| 5 | `"vision_model"` |
| 6 | `"image_api"` |
| 7 | `"wordpress_api"` |
| 8 | `"user"` |
| 9 | `"manual_review"` |

## priority

| # | allowed_value |
|---|---|
| 1 | `"high"` |
| 2 | `"medium"` |
| 3 | `"low"` |
| 4 | `"critical"` |

## publish_status

| # | allowed_value |
|---|---|
| 1 | `"draft"` |
| 2 | `"private"` |

## risk_level

| # | allowed_value |
|---|---|
| 1 | `"low"` |
| 2 | `"medium"` |
| 3 | `"high"` |

## run_condition

| # | allowed_value |
|---|---|
| 1 | `"always"` |
| 2 | `"audio_count_gt_0"` |
| 3 | `"image_count_gt_0"` |

## session_state

| # | allowed_value |
|---|---|
| 1 | `"created"` |
| 2 | `"uploading"` |
| 3 | `"analyzing"` |
| 4 | `"needs_input"` |
| 5 | `"ready_to_generate"` |
| 6 | `"generating"` |
| 7 | `"needs_review"` |
| 8 | `"ready_to_publish"` |
| 9 | `"publishing"` |
| 10 | `"published"` |
| 11 | `"failed"` |

## source_mode

| # | allowed_value |
|---|---|
| 1 | `"user_input_or_generated"` |
| 2 | `"generated"` |
| 3 | `"configured"` |
| 4 | `"derived"` |
| 5 | `"derived_from_facts"` |
| 6 | `"generated_from_facts"` |
| 7 | `"generated_from_image_analysis"` |
| 8 | `"image_analysis"` |

## target_type

| # | allowed_value |
|---|---|
| 1 | `"field"` |
| 2 | `"group"` |
| 3 | `"section"` |
| 4 | `"image_metadata"` |
| 5 | `"internal_links"` |
| 6 | `"draft_validation"` |

## value_type

| # | allowed_value |
|---|---|
| 1 | `"string"` |
| 2 | `"integer"` |
| 3 | `"float"` |
| 4 | `"boolean"` |
| 5 | `"enum"` |
| 6 | `"list"` |
| 7 | `"date"` |
| 8 | `"json"` |
| 9 | `"ratio"` |
| 10 | `"html"` |

## workflow_stage

| # | allowed_value |
|---|---|
| 1 | `"all"` |
| 2 | `"analysis"` |
| 3 | `"context_loading"` |
| 4 | `"clarification"` |
| 5 | `"generation"` |
| 6 | `"internal_links"` |
| 7 | `"image_metadata"` |
| 8 | `"ai_image_edit"` |
