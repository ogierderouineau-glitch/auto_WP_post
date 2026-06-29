from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_JSON = APP_ROOT / "data/audits/knowledge_workbook_audit.json"
DEFAULT_OUT_JSON = APP_ROOT / "data/audits/seo_payload_mapping_report.json"
DEFAULT_OUT_MD = APP_ROOT / "data/audits/seo_payload_mapping_report.md"

CODE_REFS = {
    "build_payload": "step_10_event_payload.py:481",
    "marker_map": "step_10_event_payload.py:495",
    "technical_field_route": "step_10_event_payload.py:512",
    "create_post_payload": "step_30_wordpress_payload.py:4",
    "wp_payload_status": "step_30_wordpress_payload.py:15",
    "wp_payload_slug": "step_30_wordpress_payload.py:17",
    "wp_payload_excerpt": "step_30_wordpress_payload.py:19",
    "media_metadata_update": "step_40_wordpress_api.py:244",
}

YOAST_META_MAPPING = {
    "focus_keyword": {
        "yoast_meta_key": "yoast_wpseo_focuskw",
        "rest_path": "meta.yoast_wpseo_focuskw",
        "description": "Yoast focus keyword (primary keyword)",
        "max_length": None,
    },
    "seo_title": {
        "yoast_meta_key": "yoast_wpseo_title",
        "rest_path": "meta.yoast_wpseo_title",
        "description": "Yoast SEO title (overrides default)",
        "max_length": 60,
    },
    "meta_description": {
        "yoast_meta_key": "yoast_wpseo_metadesc",
        "rest_path": "meta.yoast_wpseo_metadesc",
        "description": "Yoast meta description",
        "max_length": 155,
    },
    "social_title": {
        "yoast_meta_key": "yoast_wpseo_opengraph_title",
        "rest_path": "meta.yoast_wpseo_opengraph_title",
        "description": "Yoast OpenGraph title (social)",
        "max_length": 70,
    },
    "social_description": {
        "yoast_meta_key": "yoast_wpseo_opengraph_description",
        "rest_path": "meta.yoast_wpseo_opengraph_description",
        "description": "Yoast OpenGraph description (social)",
        "max_length": 160,
    },
}

DIRECT_WORDPRESS_CORE = {
    "slug": {
        "destination_class": "wordpress_core_payload",
        "destination_path": "payload.slug",
        "evidence": [CODE_REFS["marker_map"], CODE_REFS["wp_payload_slug"]],
        "reason": "Slug is explicitly routed from marker_map to wordpress_payload and then emitted into create_post_payload.",
    }
}

INDIRECT_CONTENT_HINTS = {
    "title_rule",
    "faq_question_rule",
    "faq_answer_rule",
    "local_seo_rule",
    "event_seo_rule",
    "service_seo_rule",
    "meta_no_generic",
    "avoid_keyword_stuffing",
    "keyword_usage_intro",
    "keyword_usage_h2",
    "keyword_usage_body",
    "image_alt_seo",
    "internal_link_primary",
    "internal_link_secondary",
    "internal_link_contextual",
    "internal_link_count",
}

SEO_META_KEYS = {
    "focus_keyword",
    "keyword_variant_local",
    "keyword_variant_service",
    "secondary_keywords",
    "seo_title",
    "meta_description",
    "social_title",
    "social_description",
}


def classify_seo_field(field: str) -> dict[str, Any]:
    key = str(field or "").strip()
    if key in DIRECT_WORDPRESS_CORE:
        base = dict(DIRECT_WORDPRESS_CORE[key])
        base["field"] = key
        base["mapped"] = True
        return base

    if key in YOAST_META_MAPPING:
        yoast_info = YOAST_META_MAPPING[key]
        return {
            "field": key,
            "mapped": True,
            "destination_class": "yoast_plugin_meta",
            "destination_path": yoast_info["rest_path"],
            "yoast_meta_key": yoast_info["yoast_meta_key"],
            "yoast_description": yoast_info["description"],
            "yoast_max_length": yoast_info["max_length"],
            "evidence": [CODE_REFS["create_post_payload"], "https://developer.yoast.com/wordpress-plugins/api/"],
            "reason": f"Can be persisted to Yoast SEO via {yoast_info['rest_path']} (meta endpoint in WordPress REST API v2)",
            "implementation_required": "Extend create_post_payload() to populate meta dict with Yoast keys when Yoast is active",
        }

    if key in INDIRECT_CONTENT_HINTS:
        return {
            "field": key,
            "mapped": False,
            "destination_class": "indirect_generation_only",
            "destination_path": None,
            "evidence": [CODE_REFS["build_payload"], CODE_REFS["create_post_payload"]],
            "reason": "Field acts as generation/rule guidance but has no explicit write path to WordPress REST payload keys.",
        }

    return {
        "field": key,
        "mapped": False,
        "destination_class": "unmapped_not_persisted",
        "destination_path": None,
        "evidence": [CODE_REFS["create_post_payload"]],
        "reason": "No explicit mapping detected in current payload assembly/write functions.",
    }


def shared_field_recommendations(shared_fields: list[str]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for field in shared_fields:
        key = str(field or "").strip()
        if key == "excerpt":
            recommendations.append(
                {
                    "field": key,
                    "recommendation": "keep_in_shared_field_schema",
                    "owner": "wordpress_core_payload",
                    "evidence": [CODE_REFS["marker_map"], CODE_REFS["wp_payload_excerpt"]],
                    "reason": "Explicitly routed to payload['excerpt'] and persisted by create_post_payload.",
                }
            )
        elif key == "status":
            recommendations.append(
                {
                    "field": key,
                    "recommendation": "move_to_workflow_or_system_config",
                    "owner": "workflow_state",
                    "evidence": [CODE_REFS["wp_payload_status"]],
                    "reason": "Post status is passed as function argument, not sourced from shared field schema row values.",
                }
            )
        elif key == "category":
            recommendations.append(
                {
                    "field": key,
                    "recommendation": "keep_but_mark_as_technical_routing",
                    "owner": "technical_field_route",
                    "evidence": [CODE_REFS["technical_field_route"]],
                    "reason": "Category flows through technical routing to category_names then resolved to category IDs before post write.",
                }
            )
    return recommendations


def make_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# SEO to WordPress Payload Mapping Report")
    lines.append("")
    lines.append(f"- Generated at (UTC): {payload.get('generated_at')}")
    version = payload.get("workbook_version", {})
    lines.append(f"- Workbook storage mode: {version.get('storage_mode')}")
    lines.append(f"- Workbook sha256: {version.get('sha256')}")
    lines.append(f"- Workbook size bytes: {version.get('size_bytes')}")
    lines.append(f"- GCS URI: {version.get('gcs_uri')}")
    lines.append(f"- GCS generation: {version.get('gcs_generation')}")
    if version.get("gcs_fallback_reason"):
        lines.append(f"- GCS fallback reason: {version.get('gcs_fallback_reason')}")
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Total SEO fields: {payload.get('seo_fields_total', 0)}")
    lines.append(f"- Directly mapped (WordPress core): {payload.get('directly_mapped_count', 0)}")
    lines.append(f"- Yoast-persistable (via meta): {payload.get('yoast_mapped_count', 0)}")
    lines.append(f"- Indirect/guidance only: {payload.get('indirect_count', 0)}")
    lines.append(f"- Unmapped: {payload.get('unmapped_fields_total', 0)}")
    lines.append("")

    lines.append("## SEO Field Mapping Matrix")
    lines.append("| field | mapped | destination_class | destination_path | reason |")
    lines.append("|---|---|---|---|---|")
    for row in payload.get("seo_field_mapping", []):
        destination = row.get('destination_path') or ''
        reason = row.get("reason", "")
        lines.append(
            f"| {row.get('field')} | {row.get('mapped')} | {row.get('destination_class')} | {destination} | {reason} |"
        )
    lines.append("")

    lines.append("## Implementation Requirements")
    yoast_fields = [row for row in payload.get("seo_field_mapping", []) if row.get("destination_class") == "yoast_plugin_meta"]
    if yoast_fields:
        lines.append("### Yoast SEO Integration")
        lines.append("To persist SEO fields to Yoast, extend `create_post_payload()` to populate the `meta` dict:")
        lines.append("")
        lines.append("```python")
        lines.append("# In create_post_payload, add:")
        lines.append("if acf_payload or yoast_enabled:")
        lines.append("    payload['meta'] = {")
        for field_row in yoast_fields:
            yoast_key = field_row.get('yoast_meta_key')
            yoast_desc = field_row.get('yoast_description')
            lines.append(f"        '{yoast_key}': source_data.get('{field_row['field']}'),  # {yoast_desc}")
        lines.append("    }")
        lines.append("```")
        lines.append("")

    lines.append("## Unmapped Fields")
    unmapped = payload.get("unmapped_fields", [])
    if unmapped:
        for field in unmapped:
            lines.append(f"- {field}")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Shared Field Schema Recommendations")
    for row in payload.get("shared_field_recommendations", []):
        lines.append(f"- {row.get('field')}: {row.get('recommendation')} ({row.get('reason')})")
    lines.append("")

    return "\n".join(lines)


def generate_report(audit_payload: dict[str, Any]) -> dict[str, Any]:
    seo_fields = audit_payload.get("tabs", {}).get("seo_rules", {}).get("fields", [])
    shared_fields = audit_payload.get("tabs", {}).get("shared_field_schema", {}).get("fields", [])

    mapping_rows = [classify_seo_field(field) for field in seo_fields]
    unmapped = [row["field"] for row in mapping_rows if not row.get("mapped")]
    directly_mapped = [row for row in mapping_rows if row.get("destination_class") == "wordpress_core_payload"]
    yoast_mapped = [row for row in mapping_rows if row.get("destination_class") == "yoast_plugin_meta"]
    indirect = [row for row in mapping_rows if row.get("destination_class") == "indirect_generation_only"]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workbook_version": audit_payload.get("workbook_version", {}),
        "seo_fields_total": len(seo_fields),
        "directly_mapped_count": len(directly_mapped),
        "yoast_mapped_count": len(yoast_mapped),
        "indirect_count": len(indirect),
        "mapped_fields_total": sum(1 for row in mapping_rows if row.get("mapped")),
        "unmapped_fields_total": len(unmapped),
        "seo_field_mapping": mapping_rows,
        "unmapped_fields": unmapped,
        "shared_field_recommendations": shared_field_recommendations(shared_fields),
        "code_references": CODE_REFS,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate seo_rules to WordPress payload mapping report")
    parser.add_argument("--audit-json", default=str(DEFAULT_AUDIT_JSON), help="Path to workbook audit JSON")
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON), help="Output JSON path")
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD), help="Output Markdown path")
    args = parser.parse_args()

    audit_path = Path(args.audit_json)
    if not audit_path.exists():
        raise FileNotFoundError(f"Audit file not found: {audit_path}")

    audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
    report = generate_report(audit_payload)

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(make_markdown(report), encoding="utf-8")

    print(
        f"Mapping report complete. "
        f"direct={report['directly_mapped_count']}, "
        f"yoast={report['yoast_mapped_count']}, "
        f"indirect={report['indirect_count']}, "
        f"unmapped={report['unmapped_fields_total']}"
    )
    print(f"JSON: {out_json}")
    print(f"MD: {out_md}")


if __name__ == "__main__":
    main()
