from __future__ import annotations

from typing import Any

from app.v2.models.step_01_session import ContentSession
from app.v2.models.step_02_payload import WordPressPayload
from app.v2.providers.step_01_interfaces import WordPressProvider
from config import get_active_client_config, set_active_client
from step_40_wordpress_api import (
    find_term,
    request_json,
    resolve_tag_ids,
    update_media_metadata,
    upload_media,
)


class ExistingWordPressProvider(WordPressProvider):
    """Reuse proven authentication/HTTP functions without using the V1 importer."""

    META_ALIASES = {
        "yoast_wpseo_opengraph_title": (
            "_yoast_wpseo_opengraph-title",
            "_yoast_wpseo_opengraph_title",
        ),
        "yoast_wpseo_opengraph_description": (
            "_yoast_wpseo_opengraph-description",
            "_yoast_wpseo_opengraph_description",
        ),
    }

    def __init__(
        self,
        *,
        client_id: str = "flairlab",
        create_missing_tags: bool = True,
        non_blocking_missing_acf_fields: tuple[str, ...] = ("related_links_html",),
    ) -> None:
        self.client_id = client_id
        self.create_missing_tags = create_missing_tags
        self.non_blocking_missing_acf_fields = set(non_blocking_missing_acf_fields)

    def publish(
        self,
        *,
        session: ContentSession,
        payload: WordPressPayload,
        idempotency_key: str,
    ) -> dict[str, Any]:
        set_active_client(self.client_id)
        wordpress = payload.wordpress
        schema = self._rest_schema(session)
        acf_payload, warnings = self._prepare_acf_payload(payload.acf, schema)
        resolved_meta = self._resolve_meta_payload(payload.meta, schema)
        categories = self._category_ids(wordpress.categories)
        tags = self._tag_ids(wordpress.tags)
        media = self._upload_media(payload.media)
        featured_id = next(
            (
                item["media_id"]
                for item in media
                if item.get("image_usage") == "featured"
            ),
            None,
        )
        body: dict[str, Any] = {
            "title": wordpress.title,
            "slug": wordpress.slug,
            "excerpt": wordpress.excerpt,
            "status": wordpress.status,
            "categories": categories,
            "tags": tags,
            "meta": resolved_meta,
            "acf": acf_payload,
        }
        if featured_id:
            body["featured_media"] = featured_id
        rest_base = (
            "posts"
            if session.wordpress_post_type == "post"
            else session.wordpress_post_type
        )
        endpoint = f"/wp-json/wp/v2/{rest_base}"
        existing = self._find_existing(endpoint, wordpress.slug, idempotency_key)
        if existing:
            post = request_json("POST", f"{endpoint}/{existing['id']}", json=body)
            mode = "updated_idempotently"
        else:
            post = request_json("POST", endpoint, json=body)
            mode = "created"
        post_id = int(post["id"])
        for item in media:
            if item.get("image_usage") != "featured":
                request_json(
                    "POST",
                    f"/wp-json/wp/v2/media/{item['media_id']}",
                    json={"post": post_id},
                )
        return {
            "post_id": post_id,
            "status": post.get("status"),
            "view_url": post.get("link"),
            "edit_url": (
                f"{get_active_client_config().wp_base_url.rstrip('/')}"
                f"/wp-admin/post.php?post={post_id}&action=edit"
            ),
            "write_mode": mode,
            "idempotency_key": idempotency_key,
            "media": media,
            "warnings": warnings,
        }

    def contract_report(
        self,
        *,
        session: ContentSession,
        payload: WordPressPayload,
    ) -> dict[str, Any]:
        schema = self._rest_schema(session)
        acf_properties = set(schema.get("acf", ()))
        meta_properties = set(schema.get("meta", ()))
        acf_missing = sorted(set(payload.acf).difference(acf_properties))
        meta_resolution: dict[str, str | None] = {}
        for key in payload.meta:
            meta_resolution[key] = self._resolve_meta_key(key, meta_properties)
        return {
            "ready": not acf_missing and all(meta_resolution.values()),
            "missing_acf_fields": acf_missing,
            "meta_resolution": meta_resolution,
        }

    @staticmethod
    def _find_existing(endpoint: str, slug: str, idempotency_key: str) -> dict[str, Any] | None:
        if not slug:
            return None
        rows = request_json(
            "GET",
            endpoint,
            params={"slug": slug, "status": "any", "context": "edit", "per_page": 1},
        )
        return rows[0] if rows else None

    @staticmethod
    def _rest_schema(session: ContentSession) -> dict[str, set[str]]:
        rest_base = (
            "posts"
            if session.wordpress_post_type == "post"
            else session.wordpress_post_type
        )
        response = request_json("OPTIONS", f"/wp-json/wp/v2/{rest_base}")
        properties = (response.get("schema") or {}).get("properties") or {}
        return {
            "acf": set(((properties.get("acf") or {}).get("properties") or {}).keys()),
            "meta": set(((properties.get("meta") or {}).get("properties") or {}).keys()),
        }

    def _prepare_acf_payload(
        self,
        payload: dict[str, Any],
        schema: dict[str, set[str]],
    ) -> tuple[dict[str, Any], list[str]]:
        missing = sorted(set(payload).difference(schema["acf"]))
        blocking = [
            field
            for field in missing
            if field not in self.non_blocking_missing_acf_fields
        ]
        if blocking:
            raise ValueError(
                "WordPress REST does not expose required ACF fields: "
                + ", ".join(blocking)
            )
        warnings = [
            "WordPress REST does not expose optional ACF field "
            f"{field}; omitted from publication payload."
            for field in missing
        ]
        return {
            key: value
            for key, value in payload.items()
            if key in schema["acf"]
        }, warnings

    @classmethod
    def _resolve_meta_key(
        cls,
        key: str,
        exposed_meta_keys: set[str],
    ) -> str | None:
        candidates = (
            key,
            f"_{key}",
            *cls.META_ALIASES.get(key, ()),
        )
        return next((candidate for candidate in candidates if candidate in exposed_meta_keys), None)

    @classmethod
    def _resolve_meta_payload(
        cls,
        payload: dict[str, Any],
        schema: dict[str, set[str]],
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        missing: list[str] = []
        for key, value in payload.items():
            resolved_key = cls._resolve_meta_key(key, schema["meta"])
            if resolved_key is None:
                missing.append(key)
            else:
                resolved[resolved_key] = value
        if missing:
            raise ValueError(
                "WordPress REST does not expose required meta fields: "
                + ", ".join(sorted(missing))
            )
        return resolved

    @staticmethod
    def _category_ids(values: list[str | int]) -> list[int]:
        identifiers: list[int] = []
        for value in values:
            if isinstance(value, int):
                identifiers.append(value)
                continue
            term = find_term("categories", value)
            if term is None:
                raise ValueError(f"Required WordPress category not found: {value}")
            identifiers.append(int(term["id"]))
        return identifiers

    def _tag_ids(self, values: list[str | int]) -> list[int]:
        numeric = [value for value in values if isinstance(value, int)]
        names = [value for value in values if isinstance(value, str)]
        return [*numeric, *resolve_tag_ids(names, self.create_missing_tags)]

    @staticmethod
    def _upload_media(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        uploaded: list[dict[str, Any]] = []
        for item in items:
            path = item.get("path") or item.get("output")
            if not path:
                continue
            media_id, source_url = upload_media(path)
            update_media_metadata(
                media_id,
                alt_text=item.get("image_alt"),
                title=item.get("image_title"),
                caption=item.get("image_caption"),
                description=(
                    item.get("image_description")
                    or item.get("description")
                    or item.get("image_description_wp")
                ),
            )
            uploaded.append(
                {
                    **item,
                    "media_id": media_id,
                    "source_url": source_url,
                }
            )
        return uploaded
