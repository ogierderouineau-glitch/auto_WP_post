from typing import Any


def create_post_payload(
    wordpress_payload: dict[str, Any],
    category_ids: list[int],
    tag_ids: list[int],
    featured_media_id: int | None,
    status: str,
    acf_payload: dict[str, Any] | None = None,
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
    return payload
