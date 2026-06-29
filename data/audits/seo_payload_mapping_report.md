# SEO to WordPress Payload Mapping Report

- Generated at (UTC): 2026-06-23T09:08:02.377539+00:00
- Workbook storage mode: local_file
- Workbook sha256: 99d3b03322c99f4c8ef348b9025bce26fa263cffa01676d545eee379066a2872
- Workbook size bytes: 242822
- GCS URI: gs://auto-wordpress-post-499518-knowledge-workbook/knowledge/FLAIRLAB_EventPost_Master_Knowledge.xlsm
- GCS generation: None
- GCS fallback reason: Direct GCS parse failed in current environment; used local workbook copy

## Summary
- Total SEO fields: 25
- Directly mapped (WordPress core): 1
- Yoast-persistable (via meta): 5
- Indirect/guidance only: 16
- Unmapped: 19

## SEO Field Mapping Matrix
| field | mapped | destination_class | destination_path | reason |
|---|---|---|---|---|
| focus_keyword | True | yoast_plugin_meta | meta.yoast_wpseo_focuskw | Can be persisted to Yoast SEO via meta.yoast_wpseo_focuskw (meta endpoint in WordPress REST API v2) |
| keyword_variant_local | False | unmapped_not_persisted |  | No explicit mapping detected in current payload assembly/write functions. |
| keyword_variant_service | False | unmapped_not_persisted |  | No explicit mapping detected in current payload assembly/write functions. |
| secondary_keywords | False | unmapped_not_persisted |  | No explicit mapping detected in current payload assembly/write functions. |
| seo_title | True | yoast_plugin_meta | meta.yoast_wpseo_title | Can be persisted to Yoast SEO via meta.yoast_wpseo_title (meta endpoint in WordPress REST API v2) |
| meta_description | True | yoast_plugin_meta | meta.yoast_wpseo_metadesc | Can be persisted to Yoast SEO via meta.yoast_wpseo_metadesc (meta endpoint in WordPress REST API v2) |
| social_title | True | yoast_plugin_meta | meta.yoast_wpseo_opengraph_title | Can be persisted to Yoast SEO via meta.yoast_wpseo_opengraph_title (meta endpoint in WordPress REST API v2) |
| social_description | True | yoast_plugin_meta | meta.yoast_wpseo_opengraph_description | Can be persisted to Yoast SEO via meta.yoast_wpseo_opengraph_description (meta endpoint in WordPress REST API v2) |
| slug | True | wordpress_core_payload | payload.slug | Slug is explicitly routed from marker_map to wordpress_payload and then emitted into create_post_payload. |
| internal_link_primary | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| internal_link_secondary | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| internal_link_contextual | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| keyword_usage_intro | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| keyword_usage_h2 | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| keyword_usage_body | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| avoid_keyword_stuffing | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| title_rule | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| faq_question_rule | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| faq_answer_rule | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| local_seo_rule | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| event_seo_rule | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| service_seo_rule | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| meta_no_generic | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| image_alt_seo | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |
| internal_link_count | False | indirect_generation_only |  | Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys. |

## Implementation Requirements
### Yoast SEO Integration
To persist SEO fields to Yoast, extend `create_post_payload()` to populate the `meta` dict:

```python
# In create_post_payload, add:
if acf_payload or yoast_enabled:
    payload['meta'] = {
        'yoast_wpseo_focuskw': source_data.get('focus_keyword'),  # Yoast focus keyword (primary keyword)
        'yoast_wpseo_title': source_data.get('seo_title'),  # Yoast SEO title (overrides default)
        'yoast_wpseo_metadesc': source_data.get('meta_description'),  # Yoast meta description
        'yoast_wpseo_opengraph_title': source_data.get('social_title'),  # Yoast OpenGraph title (social)
        'yoast_wpseo_opengraph_description': source_data.get('social_description'),  # Yoast OpenGraph description (social)
    }
```

## Unmapped Fields
- keyword_variant_local
- keyword_variant_service
- secondary_keywords
- internal_link_primary
- internal_link_secondary
- internal_link_contextual
- keyword_usage_intro
- keyword_usage_h2
- keyword_usage_body
- avoid_keyword_stuffing
- title_rule
- faq_question_rule
- faq_answer_rule
- local_seo_rule
- event_seo_rule
- service_seo_rule
- meta_no_generic
- image_alt_seo
- internal_link_count

## Shared Field Schema Recommendations
- excerpt: keep_in_shared_field_schema (Explicitly routed to payload['excerpt'] and persisted by create_post_payload.)
- status: move_to_workflow_or_system_config (Post status is passed as function argument, not sourced from shared field schema row values.)
- category: keep_but_mark_as_technical_routing (Category flows through technical routing to category_names then resolved to category IDs before post write.)
