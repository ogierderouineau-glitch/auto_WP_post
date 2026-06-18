import argparse
from pathlib import Path
from typing import Any

from config import set_active_client
from step_10_event_payload import (
    DEFAULT_DATA_GID,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_SHEET_ID,
    build_gallery_html,
    build_payload,
    extract_zip,
    find_event_csv,
    load_csv_text,
    parse_event_csv,
    parse_helper_csv,
    safe_name,
    write_json,
)
from step_20_prepare_images import prepare_event_images
from step_30_wordpress_payload import create_post_payload
from step_40_wordpress_api import (
    acf_failure_payload,
    acf_update_has_values,
    create_or_update_wordpress_post,
    frontend_render_note,
    load_existing_media_plan,
    preflight_wordpress_permissions,
    resolve_category_ids_with_required_category,
    resolve_tag_ids,
    set_post_featured_media,
    update_acf_fields,
    upload_media_plan,
    upload_media_plan_for_post_attachments,
)
from step_50_batch_workflow import run_batch_import


def build_import_result(args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    helper_csv_text = load_csv_text(args.sheet_id, args.gid, args.csv_file)
    specs = parse_helper_csv(helper_csv_text)

    if args.event_dir:
        event_dir = args.event_dir
    elif args.zip_path:
        event_dir = extract_zip(args.zip_path, args.output_root, args.event_name or args.zip_path.stem)
    else:
        raise ValueError("Provide either --zip or --event-dir.")

    input_csv = args.input_csv or find_event_csv(event_dir)
    records = parse_event_csv(input_csv.read_text(encoding="utf-8-sig"))
    if not records:
        raise ValueError(f"No event data rows found in input CSV: {input_csv}")
    if args.row >= len(records):
        raise IndexError(f"Requested row {args.row}, but {input_csv} has only {len(records)} data row(s).")

    record = records[args.row]
    event_name = args.event_name or record.get("slug") or event_dir.name or "event_import"
    output_dir = args.output_root / safe_name(event_name)
    event_dir, compression_log = prepare_event_images(
        event_dir=event_dir,
        output_dir=output_dir,
        compress_images=args.compress_images,
        target_kb=args.compression_target_kb,
        min_quality=args.compression_min_quality,
        start_quality=args.compression_start_quality,
        min_width=args.compression_min_width,
    )
    result = build_payload(specs, record, event_dir, args.strict_featured_image)
    result["technical_log"]["helper_mapping_source"] = str(args.csv_file or f"google-sheet:{args.sheet_id}:{args.gid}")
    result["technical_log"]["event_data_source"] = str(input_csv)
    result["technical_log"]["event_data_row"] = args.row
    result["technical_log"]["image_compression"] = compression_log
    return result, output_dir


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    write_json(output_dir / "payload_preview.json", result)
    write_json(output_dir / "wordpress_payload_preview.json", result["wordpress_payload_preview"])
    write_json(output_dir / "acf_payload.json", result["acf_payload"])
    write_json(output_dir / "acf_create_payload.json", {"acf": result["acf_payload"]})
    write_json(output_dir / "advanced_custom_fields_payload.json", result["acf_payload"])
    write_json(output_dir / "technical_log.json", result["technical_log"])
    write_json(output_dir / "media_upload_plan.json", result["media_upload_plan"])
    write_json(output_dir / "warnings.json", result["warnings"])


def run_import(args: argparse.Namespace) -> Path:
    set_active_client(getattr(args, "client_id", "flairlab"))
    # 1. Read the helper sheet/CSV and event package, then build the mapped payload.
    result, output_dir = build_import_result(args)
    existing_media_plan = load_existing_media_plan(output_dir)
    write_outputs(output_dir, result)

    # 2. Stop here for dry runs. The generated JSON files show exactly what would be sent.
    if not args.live:
        print(f"Dry run complete: {output_dir / 'payload_preview.json'}")
        print("Use --live to upload media and create a WordPress draft.")
        return output_dir

    # 3. Check WordPress authentication and resolve categories/tags to numeric IDs.
    preflight = preflight_wordpress_permissions(strict=args.strict_preflight)
    result["technical_log"]["wordpress_preflight"] = preflight
    write_outputs(output_dir, result)
    if not preflight.get("authenticated"):
        print("WordPress preflight could not authenticate via /users/me.")
        print("Continuing because --strict-preflight was not set.")

    categories = result["technical_log"].get("category_names", [])
    tags = result["technical_log"].get("tag_names", [])
    category_ids, category_resolution = resolve_category_ids_with_required_category(
        categories,
        required_name=args.required_category,
        skip_missing_optional=args.skip_missing_categories,
    )
    tag_ids = resolve_tag_ids(tags, create_missing=args.create_missing_tags)
    result["technical_log"]["category_ids"] = category_ids
    result["technical_log"]["category_resolution"] = category_resolution
    result["technical_log"]["tag_ids"] = tag_ids

    # 4. Create the post and handle media using the selected Elementor strategy.
    if args.media_mode == "post-attachments":
        post, post_payload = create_post_then_attach_gallery_images(
            args=args,
            result=result,
            category_ids=category_ids,
            tag_ids=tag_ids,
            existing_media_plan=existing_media_plan,
        )
    else:
        post, post_payload = upload_media_then_create_post(
            args=args,
            result=result,
            category_ids=category_ids,
            tag_ids=tag_ids,
            existing_media_plan=existing_media_plan,
        )

    # 5. Write ACF after post creation when requested.
    create_saved_acf = (
        acf_update_has_values(post, result["acf_payload"], "post-acf")
        if args.acf_placement in {"create", "both"}
        else False
    )
    result["technical_log"]["advanced_custom_fields_create_payload_had_values"] = create_saved_acf

    if args.acf_placement in {"after-create", "both"} and args.acf_mode != "none":
        try:
            acf_update_mode, acf_update = update_acf_fields(post["id"], result["acf_payload"], args.acf_mode)
            result["technical_log"]["advanced_custom_fields_update_mode"] = acf_update_mode
            result["advanced_custom_fields_update_response"] = acf_update
        except Exception as exc:
            acf_update = acf_failure_payload(exc)
            result["technical_log"]["advanced_custom_fields_update_mode"] = "failed"
            result["advanced_custom_fields_update_response"] = acf_update
            if args.strict_acf:
                write_final_import_logs(output_dir, result, post_payload, post, acf_update)
                raise
    else:
        acf_update = {
            "skipped": True,
            "reason": f"ACF after-create update skipped by --acf-placement {args.acf_placement}.",
        }
        result["technical_log"]["advanced_custom_fields_update_mode"] = "skipped"
        result["advanced_custom_fields_update_response"] = acf_update

    # 6. Persist the full audit trail for the run.
    write_final_import_logs(output_dir, result, post_payload, post, acf_update)
    print(f"Import complete. Logs written to: {output_dir}")
    return output_dir


def create_post_then_attach_gallery_images(
    args: argparse.Namespace,
    result: dict[str, Any],
    category_ids: list[int],
    tag_ids: list[int],
    existing_media_plan: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result["technical_log"]["media_mode"] = args.media_mode
    result["technical_log"]["post_image_attachment_note"] = (
        "Gallery images are uploaded as attachments of the created post. "
        "The featured image is not attached, so Elementor Post Image Attachment "
        "carousel should only see gallery images."
    )
    create_acf_payload = (
        {key: value for key, value in result["acf_payload"].items() if key != "gallery_html"}
        if args.acf_placement in {"create", "both"}
        else None
    )
    post_payload = create_post_payload(
        wordpress_payload=result["wordpress_payload_preview"],
        category_ids=category_ids,
        tag_ids=tag_ids,
        featured_media_id=None,
        status=args.status,
        acf_payload=create_acf_payload,
    )
    result["wordpress_create_payload"] = post_payload
    result["technical_log"]["advanced_custom_fields_placement"] = args.acf_placement
    result["technical_log"]["advanced_custom_fields_in_create_payload"] = "acf" in post_payload

    post, post_write_mode = create_or_update_wordpress_post(post_payload, args.existing_post_mode)
    result["technical_log"]["post_write_mode"] = post_write_mode
    result["created_post"] = post
    result["technical_log"]["frontend_render_note"] = frontend_render_note(post)

    uploaded_media = upload_media_plan_for_post_attachments(
        result["media_upload_plan"],
        post_id=post["id"],
        existing_media_plan=existing_media_plan,
        reuse_existing_uploads=args.reuse_existing_uploads,
    )
    featured = next((item for item in uploaded_media if item["role"] == "featured"), None)
    gallery_media = [item for item in uploaded_media if item["role"] == "gallery"]
    result["media_upload_plan"] = uploaded_media
    result["acf_payload"]["gallery_html"] = build_gallery_html(gallery_media)

    if featured:
        post = set_post_featured_media(post["id"], featured["media_id"])
        result["created_post"] = post
        result["wordpress_payload_preview"]["featured_media"] = featured["media_id"]

    return post, post_payload


def upload_media_then_create_post(
    args: argparse.Namespace,
    result: dict[str, Any],
    category_ids: list[int],
    tag_ids: list[int],
    existing_media_plan: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result["technical_log"]["media_mode"] = args.media_mode
    uploaded_media = upload_media_plan(
        result["media_upload_plan"],
        existing_media_plan=existing_media_plan,
        reuse_existing_uploads=args.reuse_existing_uploads,
    )
    featured = next((item for item in uploaded_media if item["role"] == "featured"), None)
    gallery_media = [item for item in uploaded_media if item["role"] == "gallery"]
    result["media_upload_plan"] = uploaded_media
    result["acf_payload"]["gallery_html"] = build_gallery_html(gallery_media)
    result["wordpress_payload_preview"]["featured_media"] = featured["media_id"] if featured else None

    post_payload = create_post_payload(
        wordpress_payload=result["wordpress_payload_preview"],
        category_ids=category_ids,
        tag_ids=tag_ids,
        featured_media_id=featured["media_id"] if featured else None,
        status=args.status,
        acf_payload=result["acf_payload"] if args.acf_placement in {"create", "both"} else None,
    )
    result["wordpress_create_payload"] = post_payload
    result["technical_log"]["advanced_custom_fields_placement"] = args.acf_placement
    result["technical_log"]["advanced_custom_fields_in_create_payload"] = "acf" in post_payload

    post, post_write_mode = create_or_update_wordpress_post(post_payload, args.existing_post_mode)
    result["technical_log"]["post_write_mode"] = post_write_mode
    result["created_post"] = post
    result["technical_log"]["frontend_render_note"] = frontend_render_note(post)
    return post, post_payload


def write_final_import_logs(
    output_dir: Path,
    result: dict[str, Any],
    post_payload: dict[str, Any],
    post: dict[str, Any],
    acf_update: dict[str, Any],
) -> None:
    write_outputs(output_dir, result)
    write_json(output_dir / "media_upload_cache.json", result["media_upload_plan"])
    write_json(output_dir / "wordpress_create_payload.json", post_payload)
    write_json(output_dir / "created_post.json", post)
    write_json(output_dir / "advanced_custom_fields_update_response.json", acf_update)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import a FLAIRLAB event package into WordPress using the helper sheet mapping."
    )
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--event-dir", type=Path)
    parser.add_argument("--input-csv", type=Path)
    parser.add_argument("--event-name")
    parser.add_argument("--client-id", default="flairlab")
    parser.add_argument("--batch-root", type=Path)
    parser.add_argument("--sync-source", type=Path)
    parser.add_argument("--rclone-source")
    parser.add_argument("--rclone-root-folder-id")
    parser.add_argument("--allow-rclone-root", action="store_true")
    parser.add_argument("--processed-dir-name", default="processed")
    parser.add_argument("--move-after-dry-run", action="store_true")
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    parser.add_argument("--gid", default=DEFAULT_DATA_GID)
    parser.add_argument("--csv-file", type=Path, help="Local helper mapping CSV with 3 header rows.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--row", type=int, default=0, help="Data row index in the event package CSV.")
    parser.add_argument("--status", default="draft", choices=["draft", "publish", "pending", "private"])
    parser.add_argument("--media-mode", default="acf-html", choices=["acf-html", "post-attachments"])
    parser.add_argument("--existing-post-mode", default="update", choices=["update", "create"])
    parser.add_argument("--acf-mode", default="auto", choices=["auto", "post-acf", "acf-v3", "meta", "none"])
    parser.add_argument("--acf-placement", default="both", choices=["create", "after-create", "both", "none"])
    parser.add_argument("--strict-acf", action="store_true")
    parser.add_argument("--required-category", default="auto event post")
    parser.add_argument("--skip-missing-categories", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--create-missing-tags", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--strict-featured-image", action="store_true")
    parser.add_argument("--strict-preflight", action="store_true")
    parser.add_argument("--reuse-existing-uploads", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--compress-images", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--compression-target-kb", type=int, default=50)
    parser.add_argument("--compression-min-quality", type=int, default=25)
    parser.add_argument("--compression-start-quality", type=int, default=90)
    parser.add_argument("--compression-min-width", type=int, default=300)
    parser.add_argument("--live", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_root:
        run_batch_import(args, run_import)
    else:
        run_import(args)


if __name__ == "__main__":
    main()
