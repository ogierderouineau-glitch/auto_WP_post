from typing import Any


YOAST_META_FIELD_MAP = {
    "focus_keyword": "yoast_wpseo_focuskw",
    "seo_title": "yoast_wpseo_title",
    "meta_description": "yoast_wpseo_metadesc",
    "social_title": "yoast_wpseo_opengraph_title",
    "social_description": "yoast_wpseo_opengraph_description",
}


def build_yoast_meta_payload(seo_payload: dict[str, Any] | None) -> dict[str, str]:
    if not seo_payload:
        return {}

    yoast_meta: dict[str, str] = {}
    for source_key, yoast_key in YOAST_META_FIELD_MAP.items():
        value = seo_payload.get(source_key)
        text = str(value or "").strip()
        if text:
            # Some WordPress setups expose Yoast keys without underscore in REST,
            # while Yoast itself persists underscore-prefixed postmeta keys.
            yoast_meta[yoast_key] = text
            yoast_meta[f"_{yoast_key}"] = text
    return yoast_meta


def create_post_payload(
    wordpress_payload: dict[str, Any],
    category_ids: list[int],
    tag_ids: list[int],
    featured_media_id: int | None,
    status: str,
    acf_payload: dict[str, Any] | None = None,
    seo_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "title": wordpress_payload.get("title", ""),
        "content": wordpress_payload.get("content", ""),
        "status": status,
    }
    if wordpress_payload.get("slug"):
        payload["slug"] = wordpress_payload["slug"]
    if wordpress_payload.get("excerpt"):
        payload["excerpt"] = wordpress_payload["excerpt"]
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    if category_ids:
        payload["categories"] = category_ids
    if tag_ids:
        payload["tags"] = tag_ids
    if acf_payload:
        payload["acf"] = acf_payload
    yoast_meta = build_yoast_meta_payload(seo_payload)
    if yoast_meta:
        payload["meta"] = yoast_meta
    return payload
