from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import unicodedata
from typing import Any

from backend.app.models.step_01_session import ContentSession
from backend.app.models.step_02_payload import WordPressPayload
from backend.app.providers.step_01_interfaces import WordPressProvider
from backend.config import CLIENTS, DEFAULT_CLIENT_ID, get_active_client_config, set_active_client
from backend.wordpress_api import (
    find_term,
    match_registered_term,
    registered_terms,
    request_json,
    resolve_tag_ids,
    taxonomy_terms_endpoint,
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

    @staticmethod
    def registered_taxonomy_candidates(
        taxonomies: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        canonical: dict[str, list[str]] = {}
        for taxonomy, requested_terms in taxonomies.items():
            endpoint = taxonomy_terms_endpoint(taxonomy)
            available_terms = registered_terms(endpoint)
            matches = [
                match_registered_term(available_terms, requested)
                for requested in requested_terms
            ]
            canonical[taxonomy] = [
                str(term.get("name") or "").strip()
                for term in matches
                if term is not None and str(term.get("name") or "").strip()
            ]
        return canonical
    OPTIONAL_META_FIELDS = {"_generated_variables"}

    def __init__(
        self,
        *,
        client_id: str = DEFAULT_CLIENT_ID,
        create_missing_tags: bool = True,
        non_blocking_missing_acf_fields: tuple[str, ...] = (),
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
        target_post_id: int | None = None,
        force_create_new: bool = False,
        partial_update_fields: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        # The authenticated client is persisted as the session owner. The
        # fallback supports older/test sessions created before client IDs were
        # constrained by the registry.
        set_active_client(session.user_id if session.user_id in CLIENTS else self.client_id)
        wordpress = payload.wordpress
        schema = self._rest_schema(session)
        self._log_section(
            "WordPress rules retrieved",
            {
                "session_id": session.session_id,
                "wordpress_post_type": session.wordpress_post_type,
                "acf_fields": sorted(schema.get("acf", set())),
                "meta_fields": sorted(schema.get("meta", set())),
            },
        )
        partial_update_fields = partial_update_fields or None
        acf_source = payload.acf
        meta_source = payload.meta
        if partial_update_fields:
            acf_source = {
                key: value
                for key, value in payload.acf.items()
                if key in partial_update_fields.get("acf", set())
            }
            meta_source = {
                key: value
                for key, value in payload.meta.items()
                if key in partial_update_fields.get("meta", set())
            }
        acf_payload, warnings = self._prepare_acf_payload(acf_source, schema)
        warnings.extend(
            "Optional generated-variable shortcode plugin is unavailable; "
            f"{key} was omitted from the WordPress payload."
            for key in sorted(self.OPTIONAL_META_FIELDS.intersection(meta_source))
            if self._resolve_meta_key(key, schema["meta"]) is None
        )
        resolved_meta = self._resolve_meta_payload(meta_source, schema)
        wordpress_fields = partial_update_fields.get("wordpress", set()) if partial_update_fields else set()
        categories = (
            self._category_ids(wordpress.categories)
            if not partial_update_fields or "categories" in wordpress_fields
            else []
        )
        tags = (
            self._tag_ids(wordpress.tags)
            if not partial_update_fields or "tags" in wordpress_fields
            else []
        )
        media_changed = not partial_update_fields or "media" in wordpress_fields
        media_source = (
            payload.media
            if media_changed
            else []
        )
        taxonomy_ids = {
            taxonomy: self._taxonomy_term_ids(taxonomy, terms)
            for taxonomy, terms in payload.taxonomies.items()
        }
        missing_taxonomies = sorted(set(taxonomy_ids).difference(schema["properties"]))
        if missing_taxonomies:
            raise ValueError(
                "WordPress REST does not expose configured taxonomies: "
                + ", ".join(missing_taxonomies)
            )
        current_media_acf_fields = {
            str(item.get("acf_field_name")): 1
            for item in media_source
            if str(item.get("acf_field_name") or "").strip()
        }
        previous_media_acf_fields = {
            str(item.get("acf_field_name")): 0
            for item in (session.wordpress_result or {}).get("media", [])
            if str(item.get("acf_field_name") or "").strip()
        }
        media_acf_fields = {
            **(
                previous_media_acf_fields
                if media_changed and target_post_id
                else {}
            ),
            **current_media_acf_fields,
        }
        validated_media_acf, media_warnings = self._prepare_acf_payload(media_acf_fields, schema)
        warnings.extend(media_warnings)
        media = (
            self._sync_media(session, media_source)
            if media_changed
            else list((session.wordpress_result or {}).get("media", []))
        )
        for field, value in validated_media_acf.items():
            if value == 0 and field not in current_media_acf_fields:
                acf_payload[field] = 0
        for item in media if media_changed else []:
            acf_field_name = str(item.get("acf_field_name") or "").strip()
            if acf_field_name in validated_media_acf:
                acf_payload[acf_field_name] = item["media_id"]
        featured_id = next(
            (
                item["media_id"]
            for item in media if media_changed
                if item.get("media_kind", "image") == "image"
                and item.get("image_usage") == "featured"
            ),
            None,
        )
        previous_had_featured = any(
            item.get("image_usage") == "featured"
            for item in (session.wordpress_result or {}).get("media", [])
        )
        if partial_update_fields:
            body = self._partial_post_body(
                wordpress=wordpress,
                wordpress_fields=wordpress_fields,
                categories=categories,
                tags=tags,
                meta=resolved_meta,
                acf=acf_payload,
                taxonomies=taxonomy_ids,
            )
        else:
            body = {
                "title": wordpress.title,
                "slug": wordpress.slug,
                "excerpt": wordpress.excerpt,
                "status": wordpress.status,
                "categories": categories,
                "tags": tags,
                "meta": resolved_meta,
                "acf": acf_payload,
                **taxonomy_ids,
            }
        if featured_id:
            body["featured_media"] = featured_id
        elif media_changed and target_post_id and previous_had_featured:
            body["featured_media"] = 0
        sent_fields = self._sent_fields(body)
        rest_base = (
            "posts"
            if session.wordpress_post_type == "post"
            else session.wordpress_post_type
        )
        endpoint = f"/wp-json/wp/v2/{rest_base}"
        target_endpoint = f"{endpoint}/{int(target_post_id)}" if target_post_id else endpoint
        self._log_section(
            "WordPress payload sent",
            {
                "session_id": session.session_id,
                "target_endpoint": target_endpoint,
                "target_post_id": target_post_id,
                "force_create_new": force_create_new,
                "partial_update_fields": partial_update_fields,
                "sent_fields": sent_fields,
                "body": body,
            },
        )
        if target_post_id:
            post = request_json("POST", f"{endpoint}/{int(target_post_id)}", json=body)
            mode = "updated_linked_post"
        else:
            # A slug describes content; it does not establish session ownership.
            # Different sessions may legitimately generate the same slug, and
            # WordPress will make a newly created post slug unique. Existing
            # posts are updated only through an explicit target_post_id.
            post = request_json("POST", endpoint, json=body)
            mode = "created"
        post_id = int(post["id"])
        attachment_taxonomies = {
            taxonomy: taxonomy_ids[taxonomy]
            for taxonomy in payload.media_taxonomies
            if taxonomy in taxonomy_ids
        }
        attachment_media = (
            media
            if media_changed
            else (
                list((session.wordpress_result or {}).get("media", []))
                if attachment_taxonomies
                else []
            )
        )
        for item in attachment_media:
            matched_taxonomies = self._media_taxonomy_ids(
                item,
                payload=payload,
                taxonomy_ids=attachment_taxonomies,
            )
            if item.get("image_usage") != "featured" or attachment_taxonomies:
                request_json(
                    "POST",
                    f"/wp-json/wp/v2/media/{item['media_id']}",
                    json={"post": post_id, **matched_taxonomies},
                )
        deleted_media_ids: list[int] = []
        if target_post_id and media_changed:
            replacement_ids = {
                int(item["media_id"])
                for item in media
                if item.get("media_id") is not None
            }
            previous_ids = {
                int(item["media_id"])
                for item in (session.wordpress_result or {}).get("media", [])
                if item.get("media_id") is not None
            }
            for media_id in sorted(previous_ids - replacement_ids):
                try:
                    request_json(
                        "DELETE",
                        f"/wp-json/wp/v2/media/{media_id}",
                        params={"force": "true"},
                    )
                    deleted_media_ids.append(media_id)
                except Exception as exc:
                    warnings.append(
                        f"Post updated, but previous WordPress media {media_id} "
                        f"could not be deleted: {exc}"
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
            "deleted_media_ids": deleted_media_ids,
            "warnings": warnings,
            "sent_fields": sent_fields,
            "sent_body": body,
            "taxonomy_terms": taxonomy_ids,
        }

    @staticmethod
    def _log_section(title: str, data: dict[str, Any]) -> None:
        if os.getenv("V2_WORDPRESS_PAYLOAD_LOGS", "1").lower() in {
            "0",
            "false",
            "off",
            "no",
        }:
            return
        print(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "section": title,
                    **data,
                },
                ensure_ascii=False,
                default=lambda value: sorted(value) if isinstance(value, set) else str(value),
            ),
            flush=True,
        )

    @staticmethod
    def _partial_post_body(
        *,
        wordpress: Any,
        wordpress_fields: set[str],
        categories: list[int],
        tags: list[int],
        meta: dict[str, Any],
        acf: dict[str, Any],
        taxonomies: dict[str, list[int]],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        for key in ("title", "slug", "excerpt", "status"):
            if key in wordpress_fields:
                body[key] = getattr(wordpress, key)
        if "categories" in wordpress_fields:
            body["categories"] = categories
        if "tags" in wordpress_fields:
            body["tags"] = tags
        if meta:
            body["meta"] = meta
        if acf:
            body["acf"] = acf
        body.update(taxonomies)
        return body

    @staticmethod
    def _sent_fields(body: dict[str, Any]) -> dict[str, list[str]]:
        return {
            "wordpress": sorted(
                key
                for key in body
                if key not in {"meta", "acf"}
            ),
            "meta": sorted((body.get("meta") or {}).keys()),
            "acf": sorted((body.get("acf") or {}).keys()),
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
        taxonomy_missing = sorted(
            set(payload.taxonomies).difference(schema.get("properties", set()))
        )
        meta_resolution: dict[str, str | None] = {}
        for key in payload.meta:
            meta_resolution[key] = self._resolve_meta_key(key, meta_properties)
        missing_required_meta = [
            key
            for key, resolved_key in meta_resolution.items()
            if resolved_key is None and key not in self.OPTIONAL_META_FIELDS
        ]
        missing_optional_meta = [
            key
            for key, resolved_key in meta_resolution.items()
            if resolved_key is None and key in self.OPTIONAL_META_FIELDS
        ]
        return {
            "ready": not acf_missing and not missing_required_meta and not taxonomy_missing,
            "missing_acf_fields": acf_missing,
            "missing_taxonomies": taxonomy_missing,
            "meta_resolution": meta_resolution,
            "missing_optional_meta_fields": missing_optional_meta,
        }

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
            "properties": set(properties),
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
                if key not in cls.OPTIONAL_META_FIELDS:
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
    def _taxonomy_term_ids(taxonomy: str, values: list[str | int]) -> list[int]:
        identifiers: list[int] = []
        endpoint = taxonomy_terms_endpoint(taxonomy)
        available_terms = registered_terms(endpoint)
        for value in values:
            if isinstance(value, int):
                identifiers.append(value)
                continue
            term = match_registered_term(available_terms, value)
            if term is None:
                raise ValueError(
                    f"No safe registered WordPress term match for {value!r} "
                    f"in taxonomy {taxonomy!r}; automatic term creation is disabled."
                )
            identifiers.append(int(term["id"]))
        return identifiers

    @classmethod
    def _media_taxonomy_ids(
        cls,
        item: dict[str, Any],
        *,
        payload: WordPressPayload,
        taxonomy_ids: dict[str, list[int]],
    ) -> dict[str, list[int]]:
        searchable = cls._media_subject_text(item)
        visible_terms = item.get("visible_taxonomy_terms")
        matched: dict[str, list[int]] = {}
        for taxonomy, identifiers in taxonomy_ids.items():
            terms = payload.taxonomies.get(taxonomy, [])
            selected = (
                set(visible_terms.get(taxonomy) or [])
                if isinstance(visible_terms, dict)
                else None
            )
            matched[taxonomy] = [
                identifier
                for term, identifier in zip(terms, identifiers)
                if isinstance(term, str)
                and (
                    any(
                        match_registered_term(
                            [{"name": selected_term, "slug": selected_term}],
                            term,
                        )
                        is not None
                        for selected_term in selected
                    )
                    if selected is not None
                    else f" {cls._normalized_phrase(term)} " in searchable
                )
            ]
        return matched

    @classmethod
    def _media_subject_text(cls, item: dict[str, Any]) -> str:
        fields = (
            "image_alt",
            "image_title",
            "image_caption",
            "image_description",
            "image_description_wp",
            "video_title",
            "video_caption",
            "video_description",
        )
        values = [item.get(field) for field in fields]
        analysis = item.get("image_analysis")
        if isinstance(analysis, dict):
            values.extend(analysis.values())
        return f" {' '.join(cls._flatten_text(values))} "

    @classmethod
    def _flatten_text(cls, values: Any) -> list[str]:
        if isinstance(values, dict):
            values = values.values()
        if isinstance(values, (list, tuple, set)):
            return [
                text
                for value in values
                for text in cls._flatten_text(value)
            ]
        normalized = cls._normalized_phrase(values)
        return [normalized] if normalized else []

    @staticmethod
    def _normalized_phrase(value: Any) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
        without_marks = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()

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
                title=item.get("image_title") or item.get("video_title"),
                caption=item.get("image_caption") or item.get("video_caption"),
                description=(
                    item.get("image_description")
                    or item.get("video_description")
                    or item.get("description")
                    or item.get("image_description_wp")
                ),
            )
            uploaded.append(
                {
                    **item,
                    "source_media_id": ExistingWordPressProvider._media_source_key(item),
                    "media_id": media_id,
                    "source_url": source_url,
                }
            )
        return uploaded

    @classmethod
    def _sync_media(
        cls,
        session: ContentSession,
        materialized_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        current_items = list(
            (session.wordpress_payload or {}).get("media", [])
            or materialized_items
        )
        previous_items = list((session.published_wordpress_payload or {}).get("media", []))
        previous_results = list((session.wordpress_result or {}).get("media", []))
        previous_by_key: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        previous_by_path = {
            str(item.get("path") or item.get("output") or "").strip(): item
            for item in previous_items
            if str(item.get("path") or item.get("output") or "").strip()
        }
        for index, result in enumerate(previous_results):
            result_path = str(result.get("path") or result.get("output") or "").strip()
            previous = previous_by_path.get(result_path)
            if previous is None:
                previous = previous_items[index] if index < len(previous_items) else {}
            key = str(result.get("source_media_id") or cls._media_source_key(previous or result))
            if key:
                previous_by_key[key] = (previous, result)

        materialized_by_key = {
            cls._media_source_key(item): item for item in materialized_items
        }
        synchronized: list[dict[str, Any]] = []
        for current in current_items:
            key = cls._media_source_key(current)
            materialized = materialized_by_key.get(key, current)
            previous_pair = previous_by_key.get(key)
            if previous_pair is None:
                synchronized.extend(cls._upload_media([materialized]))
                continue
            previous, result = previous_pair
            if cls._media_binary_changed(current, previous):
                synchronized.extend(cls._upload_media([materialized]))
                continue
            wordpress_id = int(result["media_id"])
            if cls._media_metadata(current) != cls._media_metadata(previous):
                update_media_metadata(
                    wordpress_id,
                    alt_text=current.get("image_alt"),
                    title=current.get("image_title") or current.get("video_title"),
                    caption=current.get("image_caption") or current.get("video_caption"),
                    description=(
                        current.get("image_description")
                        or current.get("video_description")
                        or current.get("description")
                        or current.get("image_description_wp")
                    ),
                )
            synchronized.append({
                **materialized,
                "source_media_id": key,
                "media_id": wordpress_id,
                "source_url": result.get("source_url"),
            })
        return synchronized

    @staticmethod
    def _media_source_key(item: dict[str, Any]) -> str:
        explicit = str(item.get("source_media_id") or "").strip()
        if explicit:
            return explicit
        video_id = str(item.get("source_video_media_id") or "").strip()
        if video_id:
            return f"video:{video_id}:{item.get('media_kind') or 'video'}"
        media_id = item.get("media_id")
        if isinstance(media_id, str) and media_id.strip():
            return f"media:{media_id.strip()}"
        path = str(item.get("path") or item.get("output") or "").strip()
        return f"path:{path}" if path else ""

    @staticmethod
    def _media_binary_changed(current: dict[str, Any], previous: dict[str, Any]) -> bool:
        current_revision = current.get("binary_revision")
        previous_revision = previous.get("binary_revision")
        if current_revision is not None and previous_revision is not None:
            return current_revision != previous_revision
        return str(current.get("path") or "") != str(previous.get("path") or "")

    @staticmethod
    def _media_metadata(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item.get(key)
            for key in (
                "image_alt",
                "image_title",
                "image_caption",
                "image_description",
                "image_description_wp",
                "video_title",
                "video_caption",
                "video_description",
            )
        }
