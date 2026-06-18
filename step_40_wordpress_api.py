import json
import base64
import mimetypes
import re
from pathlib import Path
from typing import Any

import requests

from config import get_active_client_config


def get_auth_header(username: str, app_password: str) -> dict[str, str]:
    credentials = f"{username}:{app_password}".encode("utf-8")
    token = base64.b64encode(credentials).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def wp_headers() -> dict[str, str]:
    client = get_active_client_config()
    headers = get_auth_header(client.wp_username, client.wp_app_password)
    headers["Content-Type"] = "application/json"
    return headers


def request_json(method: str, path: str, **kwargs: Any) -> Any:
    client = get_active_client_config()
    url = f"{client.wp_base_url.rstrip('/')}{path}"
    response = requests.request(method, url, headers=wp_headers(), timeout=120, **kwargs)
    if not response.ok:
        print(f"WordPress request failed: {method} {path}")
        print(response.text)
        response.raise_for_status()
    return response.json()


def preflight_wordpress_permissions(strict: bool) -> dict[str, Any]:
    try:
        user = request_json("GET", "/wp-json/wp/v2/users/me", params={"context": "edit"})
    except requests.HTTPError as exc:
        response = exc.response
        details = {
            "base_url": get_active_client_config().wp_base_url,
            "username": get_active_client_config().wp_username,
            "authenticated": False,
            "status_code": response.status_code if response is not None else None,
            "response": response.text if response is not None else str(exc),
        }
        if strict:
            raise PermissionError(
                "WordPress did not accept the configured Application Password. "
                "Check WP_USERNAME/WP_APP_PASSWORD in config.py and whether the "
                "server passes Authorization headers to WordPress."
            ) from exc
        return details

    capabilities = user.get("capabilities") or {}
    missing = [
        capability
        for capability in ("upload_files", "edit_posts", "publish_posts")
        if not capabilities.get(capability)
    ]
    result = {
        "base_url": get_active_client_config().wp_base_url,
        "user_id": user.get("id"),
        "username": user.get("username") or user.get("slug"),
        "roles": user.get("roles", []),
        "authenticated": True,
        "missing_capabilities": missing,
    }
    if missing:
        raise PermissionError(
            "WordPress user is authenticated but lacks required capabilities: "
            + ", ".join(missing)
        )
    return result


def term_slug(name: str) -> str:
    return (
        name.lower()
        .replace("&", "and")
        .replace("/", "-")
        .replace("_", "-")
        .replace(" ", "-")
    )


def find_term(endpoint: str, name: str) -> dict[str, Any] | None:
    terms = request_json("GET", f"/wp-json/wp/v2/{endpoint}", params={"search": name, "per_page": 100})
    normalized = name.strip().lower()
    for term in terms:
        if term.get("name", "").strip().lower() == normalized:
            return term
        if term.get("slug", "").strip().lower() == term_slug(name):
            return term
    return None


def create_term(endpoint: str, name: str) -> dict[str, Any]:
    return request_json("POST", f"/wp-json/wp/v2/{endpoint}", json={"name": name})


def resolve_category_ids(names: list[str]) -> list[int]:
    ids: list[int] = []
    for name in names:
        term = find_term("categories", name)
        if not term:
            raise ValueError(f"WordPress category not found: {name}")
        ids.append(term["id"])
    return ids


def resolve_category_ids_with_required_category(
    names: list[str],
    required_name: str,
    skip_missing_optional: bool,
) -> tuple[list[int], dict[str, Any]]:
    ids: list[int] = []
    missing_optional: list[str] = []
    resolved_names: list[str] = []

    required_term = find_term("categories", required_name)
    if not required_term:
        raise ValueError(f"Required WordPress category not found: {required_name}")
    ids.append(required_term["id"])
    resolved_names.append(required_name)

    for name in names:
        if name.strip().lower() == required_name.strip().lower():
            continue
        term = find_term("categories", name)
        if not term:
            if skip_missing_optional:
                missing_optional.append(name)
                continue
            raise ValueError(f"WordPress category not found: {name}")
        ids.append(term["id"])
        resolved_names.append(name)

    return ids, {
        "required_category_name": required_name,
        "requested_category_names": names,
        "resolved_category_names": resolved_names,
        "missing_optional_category_names": missing_optional,
        "skipped_missing_optional_categories": bool(missing_optional),
        }


def resolve_tag_ids(names: list[str], create_missing: bool) -> list[int]:
    ids: list[int] = []
    for name in names:
        term = find_term("tags", name)
        if not term and create_missing:
            term = create_term("tags", name)
        if not term:
            raise ValueError(f"WordPress tag not found: {name}")
        ids.append(term["id"])
    return ids


def load_existing_media_plan(output_dir: Path) -> list[dict[str, Any]]:
    cache_path = output_dir / "media_upload_cache.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
        if isinstance(data, list):
            return data

    path = output_dir / "media_upload_plan.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def upload_media(image_path: str | Path) -> tuple[int, str]:
    path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(path.name)
    client = get_active_client_config()
    headers = get_auth_header(client.wp_username, client.wp_app_password)
    headers.update({
        "Content-Disposition": f'attachment; filename="{path.name}"',
        "Content-Type": mime_type or "application/octet-stream",
    })

    response = requests.post(
        f"{client.wp_base_url.rstrip('/')}/wp-json/wp/v2/media",
        headers=headers,
        data=path.read_bytes(),
        timeout=120,
    )
    if not response.ok:
        print("Media upload failed:")
        print(response.text)
        response.raise_for_status()

    media = response.json()
    return media["id"], media["source_url"]


def update_media_metadata(
    media_id: int,
    alt_text: str | None = None,
    title: str | None = None,
    caption: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in {
            "alt_text": alt_text,
            "title": title,
            "caption": caption,
            "description": description,
        }.items()
        if value
    }
    if not payload:
        return {"id": media_id, "skipped": True}

    return request_json("POST", f"/wp-json/wp/v2/media/{media_id}", json=payload)


def same_media_file(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    if current.get("sha256") and previous.get("sha256"):
        return (
            current.get("role") == previous.get("role")
            and current.get("filename") == previous.get("filename")
            and current.get("file_size") == previous.get("file_size")
            and current.get("sha256") == previous.get("sha256")
        )

    return (
        current.get("role") == previous.get("role")
        and current.get("filename") == previous.get("filename")
        and current.get("path") == previous.get("path")
    )


def find_reusable_media(
    item: dict[str, Any],
    existing_media_plan: list[dict[str, Any]],
    required_parent_post_id: int | None = None,
) -> dict[str, Any] | None:
    for previous in existing_media_plan:
        if not previous.get("media_id") or not previous.get("source_url"):
            continue
        if required_parent_post_id and previous.get("attached_to_post") != required_parent_post_id:
            continue
        if same_media_file(item, previous):
            reused = dict(item)
            reused["media_id"] = previous["media_id"]
            reused["source_url"] = previous["source_url"]
            reused["reused_upload"] = True
            reused["reused_from_filename"] = previous.get("filename")
            return reused
    return None


def normalize_media_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def media_title(media: dict[str, Any]) -> str:
    title = media.get("title") or {}
    if isinstance(title, dict):
        return title.get("raw") or title.get("rendered") or ""
    return str(title or "")


def wordpress_media_base_stem(value: str) -> str:
    stem = Path(value.split("?")[0]).stem
    stem = re.sub(r"-scaled$", "", stem)
    stem = re.sub(r"-\d+$", "", stem)
    return stem


def find_reusable_media_in_wordpress(
    item: dict[str, Any],
    required_parent_post_id: int | None = None,
) -> dict[str, Any] | None:
    search_term = Path(item.get("filename", "")).stem
    if not search_term:
        return None

    media_items = request_json(
        "GET",
        "/wp-json/wp/v2/media",
        params={"search": search_term, "per_page": 100, "context": "edit"},
    )
    expected_title = normalize_media_text(item.get("title"))
    expected_alt = normalize_media_text(item.get("alt_text"))

    for media in media_items:
        if required_parent_post_id and media.get("post") != required_parent_post_id:
            continue
        source_url = media.get("source_url") or ""
        source_stem = wordpress_media_base_stem(source_url)
        if normalize_media_text(source_stem) != normalize_media_text(search_term):
            continue
        if expected_title and normalize_media_text(media_title(media)) != expected_title:
            continue
        if expected_alt and normalize_media_text(media.get("alt_text")) != expected_alt:
            continue

        reused = dict(item)
        reused["media_id"] = media["id"]
        reused["source_url"] = source_url
        reused["reused_upload"] = True
        reused["reused_from_wordpress_search"] = True
        return reused

    return None


def find_reusable_media_anywhere(
    item: dict[str, Any],
    existing_media_plan: list[dict[str, Any]],
    required_parent_post_id: int | None = None,
) -> dict[str, Any] | None:
    reusable = find_reusable_media(item, existing_media_plan, required_parent_post_id)
    if reusable:
        return reusable
    return find_reusable_media_in_wordpress(item, required_parent_post_id)


def upload_media_plan(
    media_plan: list[dict[str, Any]],
    existing_media_plan: list[dict[str, Any]],
    reuse_existing_uploads: bool,
) -> list[dict[str, Any]]:
    uploaded: list[dict[str, Any]] = []
    for item in media_plan:
        if reuse_existing_uploads:
            reusable = find_reusable_media_anywhere(item, existing_media_plan)
            if reusable:
                print(
                    "Reusing existing media upload: "
                    f"{reusable['filename']} -> ID {reusable['media_id']}"
                )
                uploaded.append(reusable)
                continue

        media_id, media_url = upload_media(item["path"])
        update_media_metadata(
            media_id=media_id,
            alt_text=item.get("alt_text"),
            title=item.get("title"),
            caption=item.get("caption"),
            description=item.get("description"),
        )
        updated = dict(item)
        updated["media_id"] = media_id
        updated["source_url"] = media_url
        updated["reused_upload"] = False
        uploaded.append(updated)
    return uploaded


def attach_media_to_post(media_id: int, post_id: int) -> dict[str, Any]:
    return request_json("POST", f"/wp-json/wp/v2/media/{media_id}", json={"post": post_id})


def set_post_featured_media(post_id: int, media_id: int) -> dict[str, Any]:
    return request_json("POST", f"/wp-json/wp/v2/posts/{post_id}", json={"featured_media": media_id})


def upload_media_plan_for_post_attachments(
    media_plan: list[dict[str, Any]],
    post_id: int,
    existing_media_plan: list[dict[str, Any]],
    reuse_existing_uploads: bool,
) -> list[dict[str, Any]]:
    uploaded: list[dict[str, Any]] = []
    for item in media_plan:
        reusable = (
            find_reusable_media_anywhere(
                item,
                existing_media_plan,
                post_id if item.get("role") == "gallery" else None,
            )
            if reuse_existing_uploads
            else None
        )
        if reusable:
            print(
                "Reusing existing media upload: "
                f"{reusable['filename']} -> ID {reusable['media_id']}"
            )
            updated = reusable
        else:
            media_id, media_url = upload_media(item["path"])
            update_media_metadata(
                media_id=media_id,
                alt_text=item.get("alt_text"),
                title=item.get("title"),
                caption=item.get("caption"),
                description=item.get("description"),
            )
            updated = dict(item)
            updated["media_id"] = media_id
            updated["source_url"] = media_url
            updated["reused_upload"] = False

        if updated["role"] == "gallery":
            attach_response = attach_media_to_post(updated["media_id"], post_id)
            updated["attached_to_post"] = post_id
            updated["attachment_parent"] = attach_response.get("post")
        else:
            updated["attached_to_post"] = None

        uploaded.append(updated)
    return uploaded


def create_wordpress_post(payload: dict[str, Any]) -> dict[str, Any]:
    post = request_json("POST", "/wp-json/wp/v2/posts", json=payload)
    print(f"Created post ID: {post['id']}")
    print(f"Post link: {post.get('link')}")
    print(f"Edit post: {get_active_client_config().wp_base_url.rstrip('/')}/wp-admin/post.php?post={post['id']}&action=edit")
    return post


def find_post_by_slug(slug: str) -> dict[str, Any] | None:
    if not slug:
        return None
    posts = request_json(
        "GET",
        "/wp-json/wp/v2/posts",
        params={"slug": slug, "status": "any", "context": "edit", "per_page": 1},
    )
    return posts[0] if posts else None


def create_or_update_wordpress_post(
    payload: dict[str, Any],
    existing_post_mode: str,
) -> tuple[dict[str, Any], str]:
    existing_post = (
        find_post_by_slug(payload.get("slug", ""))
        if existing_post_mode == "update"
        else None
    )
    if existing_post:
        post = request_json("POST", f"/wp-json/wp/v2/posts/{existing_post['id']}", json=payload)
        print(f"Updated existing post ID: {post['id']}")
        print(f"Post link: {post.get('link')}")
        print(f"Edit post: {get_active_client_config().wp_base_url.rstrip('/')}/wp-admin/post.php?post={post['id']}&action=edit")
        return post, "updated"

    return create_wordpress_post(payload), "created"


def frontend_render_note(post: dict[str, Any]) -> dict[str, Any]:
    status = post.get("status")
    link = post.get("link")
    note = {
        "post_status": status,
        "post_link": link,
        "plain_link_is_public_render": status == "publish",
    }
    if status == "draft":
        note["warning"] = (
            "The REST post link for a draft is not an Elementor preview URL. "
            "Use WordPress/Elementor Preview, or create the test post as publish "
            "to verify the Single Post template on the frontend."
        )
    elif status == "private":
        note["warning"] = (
            "Private WordPress posts usually return 404 for visitors who are not logged in. "
            "Use --status publish when the post should be accessible from another device."
        )
    return note


def acf_update_has_values(response: Any, acf_payload: dict[str, Any], mode: str) -> bool:
    if not isinstance(response, dict):
        return False

    if mode == "acf-v3":
        fields = response.get("acf") or response.get("fields")
    else:
        fields = response.get("acf") or response.get("meta")

    if not isinstance(fields, dict):
        return False

    return any(key in fields and fields.get(key) not in ("", None, []) for key in acf_payload)


def update_acf_fields(post_id: int, acf_payload: dict[str, Any], mode: str) -> tuple[str, dict[str, Any]]:
    if mode == "none":
        return "none", {
            "skipped": True,
            "reason": "ACF update skipped by --acf-mode none.",
        }
    if mode == "post-acf":
        response = request_json("POST", f"/wp-json/wp/v2/posts/{post_id}", json={"acf": acf_payload})
        if acf_update_has_values(response, acf_payload, mode):
            return mode, response
        raise RuntimeError("post-acf returned successfully but did not expose saved ACF values.")
    if mode == "acf-v3":
        response = request_json("POST", f"/wp-json/acf/v3/posts/{post_id}", json={"fields": acf_payload})
        if acf_update_has_values(response, acf_payload, mode):
            return mode, response
        raise RuntimeError("acf-v3 returned successfully but did not expose saved ACF values.")
    if mode == "meta":
        response = request_json("POST", f"/wp-json/wp/v2/posts/{post_id}", json={"meta": acf_payload})
        if acf_update_has_values(response, acf_payload, mode):
            return mode, response
        raise RuntimeError("meta returned successfully but did not expose saved values.")

    errors: list[str] = []
    for candidate in ("post-acf", "acf-v3", "meta"):
        try:
            return update_acf_fields(post_id, acf_payload, candidate)
        except (requests.HTTPError, RuntimeError) as exc:
            errors.append(f"{candidate}: {exc}")

    raise RuntimeError("Could not update Advanced Custom Fields. Tried: " + "; ".join(errors))


def acf_failure_payload(exc: Exception) -> dict[str, Any]:
    return {
        "success": False,
        "error": str(exc),
        "diagnosis": (
            "The post was created, but Advanced Custom Fields were not written. "
            "This site does not expose /wp-json/acf/v3, and wp/v2 post updates "
            "did not return saved ACF/meta values."
        ),
        "likely_wordpress_fix": (
            "Enable 'Show in REST API' for the ACF field group, or install/configure "
            "an ACF REST endpoint, or add a small custom WordPress endpoint that calls "
            "ACF update_field() for these field names."
        ),
    }
