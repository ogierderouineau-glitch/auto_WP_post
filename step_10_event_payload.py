import argparse
import csv
import hashlib
import html
import json
import mimetypes
import re
import shutil
import zipfile
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any



DEFAULT_OUTPUT_ROOT = Path("data/imports")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


@dataclass
class ColumnSpec:
    index: int
    marker: str
    acf_name: str
    source_name: str
    guidance: str = ""
    min_words: int | None = None
    max_words: int | None = None
    display_name: str | None = None


def normalize_key(value: str) -> str:
    return (value or "").strip()


def normalize_marker(value: str) -> str:
    return normalize_key(value).lower()


def repair_mojibake(value: str) -> str:
    if not value:
        return value

    markers = ("Ã", "Â", "â€", "â€“", "â€”", "â€™", "â€œ", "â€")
    if not any(marker in value for marker in markers):
        return value

    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value


def parse_sheet_csv(csv_text: str) -> tuple[list[ColumnSpec], list[dict[str, str]]]:
    rows = list(csv.reader(StringIO(csv_text)))
    if len(rows) < 3:
        raise ValueError("The mapping CSV must contain at least 3 header rows.")

    marker_row, acf_row, source_row = rows[:3]
    guidance_row = rows[3] if len(rows) > 3 and is_guidance_row(rows[3]) else []
    specs = parse_mapping_rows(marker_row, acf_row, source_row, guidance_row)

    records: list[dict[str, str]] = []
    data_start = 4 if guidance_row else 3
    for raw_row in rows[data_start:]:
        record = parse_data_row(specs, raw_row)
        if record:
            records.append(record)

    return specs, records


def parse_mapping_csv(csv_text: str) -> list[ColumnSpec]:
    rows = list(csv.reader(StringIO(csv_text)))
    if len(rows) < 3:
        raise ValueError("The mapping CSV must contain 3 header rows.")

    guidance_row = rows[3] if len(rows) > 3 else []
    return parse_mapping_rows(rows[0], rows[1], rows[2], guidance_row)


def is_guidance_row(row: list[str]) -> bool:
    first_value = row[0].strip().lower() if row else ""
    return first_value in {"guidance", "agent guidance", "field guidance", "prompt guidance", "ai guidance"}


def parse_mapping_rows(
    marker_row: list[str],
    acf_row: list[str],
    source_row: list[str],
    guidance_row: list[str] | None = None,
) -> list[ColumnSpec]:
    guidance_row = guidance_row or []
    width = max(len(marker_row), len(acf_row), len(source_row), len(guidance_row))
    specs: list[ColumnSpec] = []

    for index in range(width):
        specs.append(
            ColumnSpec(
                index=index,
                marker=marker_row[index].strip() if index < len(marker_row) else "",
                acf_name=acf_row[index].strip() if index < len(acf_row) else "",
                source_name=source_row[index].strip() if index < len(source_row) else "",
                guidance=guidance_row[index].strip() if index < len(guidance_row) else "",
            )
        )

    return specs


def parse_data_row(specs: list[ColumnSpec], raw_row: list[str]) -> dict[str, str]:
    if not any(cell.strip() for cell in raw_row):
        return {}

    record: dict[str, str] = {}
    for spec in specs:
        value = raw_row[spec.index].strip() if spec.index < len(raw_row) else ""
        if spec.source_name:
            record[spec.source_name] = repair_mojibake(value)
    return record


def parse_event_csv(csv_text: str) -> list[dict[str, str]]:
    rows = list(csv.DictReader(StringIO(csv_text)))
    records: list[dict[str, str]] = []
    for row in rows:
        if not any((value or "").strip() for value in row.values()):
            continue
        record = {
            normalize_key(key): repair_mojibake((value or "").strip())
            for key, value in row.items()
            if key is not None and normalize_key(key)
        }
        records.append(record)

    return records


def find_event_csv(event_dir: Path, preferred_name: str = "data.csv") -> Path:
    preferred = event_dir / preferred_name
    if preferred.exists() and preferred.is_file():
        return preferred

    csv_files = [
        path
        for path in event_dir.rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() == ".csv"
            and not is_ignored_package_path(path.relative_to(event_dir))
        )
    ]
    csv_files = sorted(csv_files, key=lambda path: (path.parent != event_dir, str(path.relative_to(event_dir)).lower()))
    if len(csv_files) == 1:
        return csv_files[0]
    if not csv_files:
        raise FileNotFoundError(f"No event data CSV found in: {event_dir}")

    root_csv_files = [path for path in csv_files if path.parent == event_dir]
    if len(root_csv_files) == 1:
        return root_csv_files[0]

    names = ", ".join(str(path.relative_to(event_dir)) for path in csv_files)
    raise ValueError(
        "Multiple CSV files found in the event package. "
        f"Use --input-csv to choose one. Found: {names}"
    )


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return cleaned.strip("_") or "event_import"


def extract_zip(zip_path: Path, output_root: Path, event_name: str | None) -> Path:
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")

    target_name = safe_name(event_name or zip_path.stem)
    target_dir = output_root / target_name
    target_dir.mkdir(parents=True, exist_ok=True)

    extract_dir = target_dir / "extracted"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    return extract_dir


def is_ignored_package_path(path: Path) -> bool:
    ignored_names = {"__macosx", ".ds_store", "processed", "compressed_event"}
    return any(part.lower() in ignored_names or part.startswith(".") for part in path.parts)


def picture_sort_key(event_dir: Path, path: Path) -> tuple[int, str]:
    relative = path.relative_to(event_dir)
    parent_name = relative.parent.name.lower()
    preferred_names = {"pictures", "picture", "images", "image", "img", "photos", "photo"}
    if relative.parent == Path("."):
        priority = 0
    elif parent_name in preferred_names:
        priority = 1
    else:
        priority = 2
    return priority, str(relative).lower()


def find_picture_files(event_dir: Path) -> list[Path]:
    pictures = [
        path
        for path in event_dir.rglob("*")
        if (
            path.is_file()
            and path.suffix.lower() in IMAGE_EXTENSIONS
            and not is_ignored_package_path(path.relative_to(event_dir))
        )
    ]
    return sorted(pictures, key=lambda path: picture_sort_key(event_dir, path))


def picture_discovery_log(event_dir: Path, pictures: list[Path]) -> dict[str, Any]:
    folders: dict[str, int] = {}
    for path in pictures:
        folder = str(path.parent.relative_to(event_dir))
        folders[folder] = folders.get(folder, 0) + 1

    return {
        "event_dir": str(event_dir),
        "count": len(pictures),
        "folders": folders,
        "files": [str(path.relative_to(event_dir)) for path in pictures],
    }


def split_multi_value(value: str) -> list[str]:
    if not value:
        return []
    if "|" in value:
        return [part.strip() for part in value.split("|")]
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [part.strip() for part in value.split(",") if part.strip()]


def get_repeated_value(values: list[str], index: int) -> str:
    if not values:
        return ""
    if index < len(values):
        return values[index]
    return values[0]


def parse_category_names(value: str) -> list[str]:
    return split_multi_value(value)


def parse_tag_names(value: str) -> list[str]:
    return split_multi_value(value)


def is_facts_acf_field(acf_name: str) -> bool:
    normalized = acf_name.strip().lower()
    return normalized in {"fakten", "facts"} or "fakten" in normalized or "facts" in normalized


def fact_type_from_source(source_name: str) -> str:
    raw = source_name.rsplit("_", 1)[-1] if "_" in source_name else source_name
    raw = raw.replace("-", " ").strip()
    return raw[:1].upper() + raw[1:] if raw else "Fakt"


def format_fact_item(source_name: str, value: str) -> str:
    if not value:
        return ""
    stripped = value.strip()
    if "<strong>" in stripped or "<b>" in stripped:
        return stripped
    fact_type = html.escape(fact_type_from_source(source_name))
    return f"<strong>{fact_type}:</strong> {stripped}"


def normalize_rich_text_for_dedupe(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def has_bullet_guidance(guidance: str) -> bool:
    normalized = (guidance or "").lower()
    markers = (
        "bullet",
        "bullets",
        "list",
        "stichpunkt",
        "stichpunkte",
        "aufzaehlung",
        "aufzählung",
        "liste",
    )
    return any(marker in normalized for marker in markers)


def render_acf_items(items: list[str], render_bullets: bool) -> str:
    if not items:
        return ""
    if not render_bullets:
        return "\n\n".join(items)

    list_items: list[str] = []
    for item in items:
        stripped = item.strip()
        if stripped.lower().startswith("<li"):
            list_items.append(stripped)
        else:
            list_items.append(f"<li>{stripped}</li>")
    return f"<ul>{''.join(list_items)}</ul>"


def split_text_fragments(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []

    li_matches = re.findall(r"<li\b[^>]*>(.*?)</li>", text, flags=re.IGNORECASE | re.DOTALL)
    if li_matches:
        return [fragment.strip() for fragment in li_matches if fragment.strip()]

    parts = [part.strip() for part in re.split(r"\n\n+|\r\n\r\n+|\n|\r\n", text) if part.strip()]
    return parts or [text]


def dedupe_acf_fragments(items: list[str]) -> list[str]:
    def token_set(value: str) -> set[str]:
        return set(re.findall(r"\b[\wÄÖÜäöüß-]+\b", normalize_rich_text_for_dedupe(value)))

    def near_duplicate(existing: str, candidate: str) -> bool:
        existing_norm = normalize_rich_text_for_dedupe(existing)
        candidate_norm = normalize_rich_text_for_dedupe(candidate)
        if not existing_norm or not candidate_norm:
            return False

        # Catch common containment cases where one field repeats the same story with minor additions.
        if existing_norm in candidate_norm or candidate_norm in existing_norm:
            shorter = min(len(existing_norm), len(candidate_norm))
            longer = max(len(existing_norm), len(candidate_norm))
            if shorter >= 120 or (shorter >= 60 and shorter / max(longer, 1) >= 0.75):
                return True

        left = token_set(existing)
        right = token_set(candidate)
        if not left or not right:
            return False

        overlap = len(left & right)
        ratio = overlap / max(min(len(left), len(right)), 1)
        return ratio >= 0.8

    fragments: list[str] = []
    seen: set[str] = set()
    for item in items:
        for fragment in split_text_fragments(item):
            normalized = normalize_rich_text_for_dedupe(fragment)
            if not normalized or normalized in seen:
                continue
            if any(near_duplicate(existing, fragment) for existing in fragments):
                continue
            seen.add(normalized)
            fragments.append(fragment)
    return fragments


def select_featured_image(
    pictures: list[Path],
    record: dict[str, str],
    warnings: list[str],
    strict: bool,
) -> Path | None:
    if not pictures:
        warnings.append("No image files were found in the extracted event package.")
        return None

    requested = record.get("featured_image", "").strip()
    if requested:
        matches = [
            path for path in pictures
            if path.name == requested or path.stem == Path(requested).stem
        ]
        if matches:
            return matches[0]
        warnings.append(f"featured_image value did not match any file: {requested}")

    prefixed = [path for path in pictures if path.name.lower().startswith("featured_")]
    if prefixed:
        return prefixed[0]

    message = "No featured image was identified by featured_ prefix or featured_image column."
    if strict:
        raise ValueError(message)

    warnings.append(f"{message} Using the first image as a preview fallback.")
    return pictures[0]


def media_preview_item(path: Path, metadata: dict[str, str], role: str) -> dict[str, Any]:
    mime_type, _ = mimetypes.guess_type(path)
    stat = path.stat()
    return {
        "role": role,
        "filename": path.name,
        "path": str(path),
        "file_size": stat.st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mime_type": mime_type or "application/octet-stream",
        "alt_text": metadata.get("alt_text", ""),
        "title": metadata.get("title", ""),
        "caption": metadata.get("caption", ""),
        "description": metadata.get("description", ""),
        "media_id": None,
        "source_url": f"LOCAL_PREVIEW/{path.name}",
    }


def build_gallery_html(gallery_media: list[dict[str, Any]]) -> str:
    if not gallery_media:
        return ""

    slides = []
    for item in gallery_media:
        alt = html.escape(item.get("alt_text", ""), quote=True)
        title = html.escape(item.get("title", ""), quote=True)
        src = html.escape(item.get("source_url", ""), quote=True)
        title_attr = f' title="{title}"' if title else ""
        slides.append(
            f'<div class="swiper-slide" role="group">'
            f'<figure class="swiper-slide-inner">'
            f'<img class="swiper-slide-image" src="{src}" alt="{alt}"{title_attr} loading="lazy" decoding="async">'
            f'</figure>'
            f'</div>'
        )

    return (
        '<div class="flairlab-gallery-carousel elementor-image-carousel-wrapper swiper" '
        'data-flairlab-gallery-carousel role="region" aria-roledescription="carousel" aria-label="Image Carousel">'
        '<div class="flairlab-gallery-carousel-track elementor-image-carousel swiper-wrapper">'
        f'{"".join(slides)}'
        '</div>'
        '<div class="elementor-swiper-button elementor-swiper-button-prev" role="button" tabindex="0" aria-label="Previous slide">'
        '<svg aria-hidden="true" class="e-font-icon-svg e-eicon-chevron-left" viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg"><path d="M646 125C629 125 613 133 604 142L308 442C296 454 292 471 292 487 292 504 296 521 308 533L604 854C617 867 629 875 646 875 663 875 679 871 692 858 704 846 713 829 713 812 713 796 708 779 692 767L438 487 692 225C700 217 708 204 708 187 708 171 704 154 692 142 675 129 663 125 646 125Z"></path></svg>'
        '</div>'
        '<div class="elementor-swiper-button elementor-swiper-button-next" role="button" tabindex="0" aria-label="Next slide">'
        '<svg aria-hidden="true" class="e-font-icon-svg e-eicon-chevron-right" viewBox="0 0 1000 1000" xmlns="http://www.w3.org/2000/svg"><path d="M696 533C708 521 713 504 713 487 713 471 708 454 696 446L400 146C388 133 375 125 354 125 338 125 325 129 313 142 300 154 292 171 292 187 292 204 296 221 308 233L563 492 304 771C292 783 288 800 288 817 288 833 296 850 308 863 321 871 338 875 354 875 371 875 388 867 400 854L696 533Z"></path></svg>'
        '</div>'
        '<div class="swiper-pagination"></div>'
        '<span class="swiper-notification" aria-live="assertive" aria-atomic="true"></span>'
        '</div>'
    )


SOURCE_FIELD_ALIAS_LOOKUP = {
    "bartendertitle": "bartendertile",
    "bartendertile": "bartendertitle",
}


def normalize_source_field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def build_record_value_lookup(record: dict[str, str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for raw_key, raw_value in record.items():
        normalized = normalize_source_field_key(raw_key)
        if not normalized:
            continue
        lookup.setdefault(normalized, str(raw_value or ""))
    return lookup


def value_for_source_field(source_name: str, record: dict[str, str], normalized_lookup: dict[str, str]) -> str:
    source = str(source_name or "").strip()
    if not source:
        return ""
    if source in record:
        return str(record.get(source, "") or "")

    normalized_source = normalize_source_field_key(source)
    if not normalized_source:
        return ""

    value = normalized_lookup.get(normalized_source)
    if value is not None:
        return value

    alias = SOURCE_FIELD_ALIAS_LOOKUP.get(normalized_source)
    if alias:
        return normalized_lookup.get(alias, "")
    return ""


def build_payload(
    specs: list[ColumnSpec],
    record: dict[str, str],
    event_dir: Path | None,
    strict_featured_image: bool,
) -> dict[str, Any]:
    warnings: list[str] = []
    technical_log: dict[str, Any] = {}
    acf_payload: dict[str, str] = {}
    acf_collected_values: dict[str, list[str]] = {}
    acf_collected_specs: dict[str, list[ColumnSpec]] = {}
    acf_field_names: list[str] = []
    standard_payload: dict[str, Any] = {"status": "draft"}

    marker_map = {
        "post_slug": ("slug", "slug"),
        "post_title": ("title", "post_title"),
        "post_excerpt": ("excerpt", "excerpt"),
    }
    normalized_record_lookup = build_record_value_lookup(record)

    for spec in specs:
        source = spec.source_name
        value = value_for_source_field(source, record, normalized_record_lookup) if source else ""
        marker = normalize_marker(spec.marker)

        if not source:
            continue

        if marker in marker_map:
            payload_key, source_key = marker_map[marker]
            standard_payload[payload_key] = record.get(source_key, value)
        elif marker == "technical field to integrate":
            if source == "category":
                technical_log["category_names"] = parse_category_names(value)
            elif source == "tags":
                technical_log["tag_names"] = parse_tag_names(value)
            else:
                technical_log[source] = value
        elif marker in {"acf", "acr", "advanced custom fields"} and spec.acf_name and spec.acf_name != "gallery_html":
            if spec.acf_name not in acf_field_names:
                acf_field_names.append(spec.acf_name)
            if value:
                if is_facts_acf_field(spec.acf_name):
                    value = format_fact_item(source, value)
                acf_collected_values.setdefault(spec.acf_name, []).append(value)
                acf_collected_specs.setdefault(spec.acf_name, []).append(spec)
        elif marker.startswith("image_"):
            technical_log[source] = value

    # Build final ACF values with de-duplication and optional bullet rendering.
    for acf_name in acf_field_names:
        raw_items = acf_collected_values.get(acf_name, [])
        if not raw_items:
            continue

        specs_for_acf = acf_collected_specs.get(acf_name, [])
        repeated_parts = len(specs_for_acf) > 1

        if repeated_parts:
            deduped_items = dedupe_acf_fragments(raw_items)
        else:
            deduped_items = []
            seen: set[str] = set()
            for item in raw_items:
                normalized = normalize_rich_text_for_dedupe(item)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                deduped_items.append(item.strip())

        render_bullets = is_facts_acf_field(acf_name) or (
            repeated_parts and any(has_bullet_guidance(spec.guidance) for spec in specs_for_acf)
        )
        acf_payload[acf_name] = render_acf_items(deduped_items, render_bullets)
        technical_log.setdefault("acf_merge_debug", {})[acf_name] = {
            "source_parts": len(specs_for_acf),
            "raw_items": len(raw_items),
            "final_items": len(deduped_items),
            "render_bullets": render_bullets,
        }

    pictures = find_picture_files(event_dir) if event_dir else []
    if event_dir:
        technical_log["picture_discovery"] = picture_discovery_log(event_dir, pictures)
    featured = select_featured_image(pictures, record, warnings, strict_featured_image) if pictures else None
    gallery_pictures = [path for path in pictures if path != featured]

    featured_metadata = {
        "alt_text": record.get("featured_image_alt", ""),
        "title": record.get("featured_image_title", ""),
        "caption": record.get("featured_image_caption", ""),
        "description": record.get("featured_image_description", ""),
    }
    gallery_alts = split_multi_value(record.get("gallery_alts", ""))
    gallery_titles = split_multi_value(record.get("gallery_titles", ""))
    gallery_captions = split_multi_value(record.get("gallery_captions", ""))
    gallery_descriptions = split_multi_value(record.get("gallery_descriptions", ""))

    media_plan: list[dict[str, Any]] = []
    if featured:
        featured_media = media_preview_item(featured, featured_metadata, "featured")
        media_plan.append(featured_media)
        standard_payload["featured_media"] = None
        technical_log["featured_image_file"] = featured.name

    gallery_media: list[dict[str, Any]] = []
    for index, path in enumerate(gallery_pictures):
        item = media_preview_item(
            path,
            {
                "alt_text": get_repeated_value(gallery_alts, index),
                "title": get_repeated_value(gallery_titles, index),
                "caption": get_repeated_value(gallery_captions, index),
                "description": get_repeated_value(gallery_descriptions, index),
            },
            "gallery",
        )
        gallery_media.append(item)
        media_plan.append(item)

    if "gallery_html" not in acf_field_names:
        acf_field_names.append("gallery_html")
    acf_payload["gallery_html"] = build_gallery_html(gallery_media)
    technical_log["advanced_custom_field_names"] = acf_field_names

    return {
        "wordpress_payload_preview": standard_payload,
        "acf_payload": acf_payload,
        "technical_log": technical_log,
        "media_upload_plan": media_plan,
        "warnings": warnings,
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a WordPress/ACF payload preview from mapping rows and an event CSV."
    )
    parser.add_argument("--zip", dest="zip_path", type=Path, help="Local event package zip.")
    parser.add_argument("--event-dir", type=Path)
    parser.add_argument("--input-csv", type=Path)
    parser.add_argument("--event-name", help="Event/import folder name.")
    parser.add_argument("--csv-file", type=Path, required=True, help="Local mapping CSV with 3 header rows.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--row", type=int, default=0, help="Data row index in the event package CSV.")
    parser.add_argument("--strict-featured-image", action="store_true")
    args = parser.parse_args()

    mapping_csv_text = args.csv_file.read_text(encoding="utf-8-sig")
    specs = parse_mapping_csv(mapping_csv_text)

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

    event_name = args.event_name or records[args.row].get("slug") or "event_import"
    output_dir = args.output_root / safe_name(event_name)

    result = build_payload(
        specs=specs,
        record=records[args.row],
        event_dir=event_dir,
        strict_featured_image=args.strict_featured_image,
    )

    write_json(output_dir / "payload_preview.json", result)
    write_json(output_dir / "wordpress_payload_preview.json", result["wordpress_payload_preview"])
    write_json(output_dir / "acf_payload.json", result["acf_payload"])
    write_json(output_dir / "advanced_custom_fields_payload.json", result["acf_payload"])
    write_json(output_dir / "technical_log.json", result["technical_log"])
    write_json(output_dir / "media_upload_plan.json", result["media_upload_plan"])
    write_json(output_dir / "warnings.json", result["warnings"])
    print(f"Built payload preview: {output_dir / 'payload_preview.json'}")
    if result["warnings"]:
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
