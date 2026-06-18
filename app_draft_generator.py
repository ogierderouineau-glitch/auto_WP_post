import csv
import json
import re
import shutil
import zipfile
from io import StringIO
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None

from config import OPENAI_API_KEY
from step_10_event_payload import ColumnSpec, safe_name


DEFAULT_TEXT_MODEL = "gpt-4o-mini"
REQUIRED_CATEGORY = "auto event post"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "event-post"


def compact_words(value: str, limit: int) -> str:
    words = re.sub(r"\s+", " ", value).strip().split()
    return " ".join(words[:limit])


def fallback_title(transcript: str, post_type: str) -> str:
    candidate = compact_words(transcript, 10)
    if candidate:
        return candidate[:1].upper() + candidate[1:]
    return f"FLAIRLAB {post_type}".strip()


def normalize_category(category: str) -> str:
    requested = [part.strip() for part in re.split(r"[,|]", category or "") if part.strip()]
    if not any(part.lower() == REQUIRED_CATEGORY for part in requested):
        requested.insert(0, REQUIRED_CATEGORY)
    return ", ".join(dict.fromkeys(requested))


def generate_ai_draft(
    transcript: str,
    post_type: str,
    category: str,
    image_names: list[str],
) -> dict[str, str]:
    if not OPENAI_API_KEY or OpenAI is None:
        return {"_agent_reply": "AI drafting is not available because OPENAI_API_KEY or the openai package is missing."}

    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model=DEFAULT_TEXT_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You create concise, polished German WordPress event post draft data "
                        "for FLAIRLAB. Return only valid JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "transcript": transcript,
                            "post_type": post_type,
                            "category": category,
                            "image_names": image_names,
                            "required_json_keys": [
                                "post_title",
                                "slug",
                                "excerpt",
                                "hero_title",
                                "hero_description",
                                "section_1_title",
                                "section_1_text",
                                "section_2_title",
                                "section_2_text",
                                "cta_title",
                                "cta_text",
                                "tags",
                                "featured_image_alt",
                                "featured_image_title",
                                "featured_image_caption",
                                "featured_image_description",
                                "gallery_alts",
                                "gallery_titles",
                                "gallery_captions",
                                "gallery_descriptions",
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.4,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def specs_for_prompt(specs: list[ColumnSpec]) -> list[dict[str, Any]]:
    return [
        {
            "source_name": spec.source_name,
            "marker": spec.marker,
            "acf_name": spec.acf_name,
            "guidance": spec.guidance,
        }
        for spec in specs
        if spec.source_name
    ]


def parse_single_row_csv(csv_text: str) -> tuple[list[str], dict[str, str]]:
    rows = list(csv.reader(StringIO(csv_text or "")))
    if not rows:
        return [], {}
    headers = rows[0]
    values = rows[1] if len(rows) > 1 else []
    return headers, {
        header: values[index] if index < len(values) else ""
        for index, header in enumerate(headers)
    }


def write_single_row_csv(headers: list[str], row: dict[str, str]) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerow({header: row.get(header, "") for header in headers})
    return output.getvalue()


def generate_ai_field_row(
    specs: list[ColumnSpec],
    transcript: str,
    post_type: str,
    category: str,
    featured_image_filename: str,
    image_names: list[str],
    current_row: dict[str, str] | None = None,
    chat_history: list[dict[str, str]] | None = None,
    user_message: str | None = None,
) -> dict[str, str]:
    if not OPENAI_API_KEY or OpenAI is None:
        return {}

    client = OpenAI(api_key=OPENAI_API_KEY)
    fieldnames = [spec.source_name for spec in specs if spec.source_name]
    try:
        response = client.chat.completions.create(
            model=DEFAULT_TEXT_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the FLAIRLAB WordPress event post drafting agent. "
                        "You fill one CSV data row for an existing import script. "
                        "Use the exact CSV source_name keys provided. "
                        "Return JSON with two keys: row and reply. "
                        "row must be an object whose keys are CSV source_name values. "
                        "reply must briefly explain what you changed or what still needs clarification. "
                        "Write polished German copy. Keep HTML tags from the user's content style when useful. "
                        "Build hero fields, CTA title/text, FAQ fields, facts/fakten, image metadata, and all ACF fields when matching columns exist. "
                        "Follow each field's guidance value when present; it may define length, tone, creativity, structure, or examples. "
                        "For CSV columns feeding a facts/fakten ACF field, write one concise fact per column. "
                        "Do not include the fact label unless the guidance explicitly asks for it; the importer formats facts as bold labels from the column suffix. "
                        "Do not invent unknown facts; use the transcript and chat instructions. "
                        "Always keep category containing 'auto event post'. "
                        "Use the exact featured_image filename provided."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "csv_fields": specs_for_prompt(specs),
                            "allowed_fieldnames": fieldnames,
                            "transcript": transcript,
                            "post_type": post_type,
                            "selected_category": normalize_category(category),
                            "featured_image_filename": featured_image_filename,
                            "image_names": image_names,
                            "current_row": current_row or {},
                            "chat_history": chat_history or [],
                            "user_message": user_message
                            or (
                                "Generate the best complete draft. Pay special attention to hero fields, "
                                "CTA title/text, FAQ content, and facts/fakten fields."
                            ),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.35,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        row = data.get("row", data)
        if not isinstance(row, dict):
            return {}
        result = {str(key): str(value) for key, value in row.items() if key in fieldnames and value is not None}
        if data.get("reply"):
            result["_agent_reply"] = str(data["reply"])
        return result
    except Exception as exc:
        return {"_agent_reply": f"AI draft update skipped: {exc}"}


def base_draft_values(
    transcript: str,
    post_type: str,
    category: str,
    featured_image_filename: str,
    image_names: list[str],
) -> dict[str, str]:
    title = fallback_title(transcript, post_type)
    excerpt = compact_words(transcript, 28)
    image_alt = f"{title} von FLAIRLAB"
    gallery_value = " | ".join(image_alt for _ in image_names)

    return {
        "post_title": title,
        "title": title,
        "slug": slugify(title),
        "excerpt": excerpt,
        "post_excerpt": excerpt,
        "category": normalize_category(category),
        "tags": post_type,
        "featured_image": featured_image_filename,
        "featured_image_alt": image_alt,
        "featured_image_title": title,
        "featured_image_caption": title,
        "featured_image_description": excerpt,
        "gallery_alts": gallery_value,
        "gallery_titles": gallery_value,
        "gallery_captions": gallery_value,
        "gallery_descriptions": gallery_value,
        "hero_title": title,
        "hero_description": excerpt,
        "section_1_title": "Ausgangssituation",
        "section_1_text": transcript,
        "section_2_title": "Umsetzung",
        "section_2_text": transcript,
        "cta_title": "Event mit FLAIRLAB planen",
        "cta_text": "FLAIRLAB unterstützt Events mit mobiler Bar, Drinks und professionellem Service.",
    }


def value_for_source(source_name: str, acf_name: str, values: dict[str, str], transcript: str) -> str:
    source = source_name.strip()
    if source in values:
        return values[source]

    normalized = source.lower()
    acf = acf_name.lower()
    if normalized in {"content", "post_content", "body", "text"}:
        return transcript
    if "title" in normalized or "title" in acf:
        return values["post_title"]
    if any(token in normalized or token in acf for token in ("description", "excerpt", "summary")):
        return values["excerpt"]
    if any(token in normalized or token in acf for token in ("text", "copy", "content")):
        return transcript
    if "faq" in normalized or "faq" in acf:
        return ""
    if "fakten" in normalized or "facts" in normalized or "fakten" in acf or "facts" in acf:
        return compact_words(transcript, 14)
    return ""


def build_event_csv(
    specs: list[ColumnSpec],
    transcript: str,
    post_type: str,
    category: str,
    featured_image_filename: str,
    image_names: list[str],
) -> tuple[str, dict[str, str]]:
    values = base_draft_values(
        transcript=transcript,
        post_type=post_type,
        category=category,
        featured_image_filename=featured_image_filename,
        image_names=image_names,
    )
    values.update(
        {
            key: value
            for key, value in generate_ai_draft(transcript, post_type, category, image_names).items()
            if value
        }
    )
    values["post_title"] = values.get("post_title") or values.get("title") or fallback_title(transcript, post_type)
    values["title"] = values["post_title"]
    values["category"] = normalize_category(values.get("category") or category)
    values["featured_image"] = featured_image_filename
    if not values.get("slug") or values["slug"] == "event-post":
        values["slug"] = slugify(values["post_title"])

    fieldnames = [spec.source_name for spec in specs if spec.source_name]
    if not fieldnames:
        fieldnames = sorted(values)
    row = {
        source: value_for_source(source, next((spec.acf_name for spec in specs if spec.source_name == source), ""), values, transcript)
        for source in fieldnames
    }
    ai_row = generate_ai_field_row(
        specs=specs,
        transcript=transcript,
        post_type=post_type,
        category=category,
        featured_image_filename=featured_image_filename,
        image_names=image_names,
        current_row=row,
    )
    agent_reply = ai_row.pop("_agent_reply", "")
    row.update({key: value for key, value in ai_row.items() if value})
    row["category"] = normalize_category(row.get("category") or category)
    row["featured_image"] = featured_image_filename

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow(row)
    if agent_reply:
        row["_agent_reply"] = agent_reply
    return output.getvalue(), row


def rebuild_session_package(session_dir: Path, csv_text: str, state: dict[str, Any]) -> Path:
    draft_dir = session_dir / "draft"
    package_dir = draft_dir / "package"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    (package_dir / "pictures").mkdir(parents=True, exist_ok=True)
    (package_dir / "videos").mkdir(parents=True, exist_ok=True)

    csv_path = package_dir / "event.csv"
    csv_path.write_text(csv_text, encoding="utf-8")

    for item in state.get("files", {}).get("images", []):
        source = Path(item["path"])
        if source.exists():
            shutil.copy2(source, package_dir / "pictures" / source.name)

    for item in state.get("files", {}).get("videos", []):
        source = Path(item["path"])
        if source.exists():
            shutil.copy2(source, package_dir / "videos" / source.name)

    zip_name = safe_name(state.get("session_id", "event_session")) + ".zip"
    zip_path = draft_dir / zip_name
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in package_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(package_dir))

    return zip_path


def create_session_draft(
    session_dir: Path,
    state: dict[str, Any],
    specs: list[ColumnSpec],
    category: str,
) -> dict[str, Any]:
    transcript = state.get("transcript", {}).get("text", "").strip()
    if not transcript:
        raise ValueError("Transcript is required before generating a draft.")

    images = state.get("files", {}).get("images", [])
    featured = state.get("files", {}).get("featured_image_filename") or (images[0]["filename"] if images else "")
    image_names = [item["filename"] for item in images]
    csv_text, row = build_event_csv(
        specs=specs,
        transcript=transcript,
        post_type=state.get("post_type", "Event"),
        category=category,
        featured_image_filename=featured,
        image_names=image_names,
    )
    zip_path = rebuild_session_package(session_dir, csv_text, state)
    return {
        "category": normalize_category(category),
        "csv_text": csv_text,
        "row": row,
        "chat": [
            {
                "role": "assistant",
                "content": row.get("_agent_reply") or "Draft CSV generated. You can ask me to revise any field.",
            }
        ],
        "zip_path": str(zip_path),
        "package_dir": str(session_dir / "draft" / "package"),
    }


def revise_session_draft(
    session_dir: Path,
    state: dict[str, Any],
    specs: list[ColumnSpec],
    message: str,
) -> dict[str, Any]:
    transcript = state.get("transcript", {}).get("text", "").strip()
    if not transcript:
        raise ValueError("Transcript is required before revising a draft.")

    draft = state.get("draft", {})
    headers, current_row = parse_single_row_csv(draft.get("csv_text", ""))
    if not headers:
        headers = [spec.source_name for spec in specs if spec.source_name]
        current_row = {}

    images = state.get("files", {}).get("images", [])
    featured = state.get("files", {}).get("featured_image_filename") or (images[0]["filename"] if images else "")
    image_names = [item["filename"] for item in images]
    chat_history = draft.get("chat", [])
    ai_row = generate_ai_field_row(
        specs=specs,
        transcript=transcript,
        post_type=state.get("post_type", "Event"),
        category=draft.get("category") or current_row.get("category") or REQUIRED_CATEGORY,
        featured_image_filename=featured,
        image_names=image_names,
        current_row=current_row,
        chat_history=chat_history,
        user_message=message,
    )
    agent_reply = ai_row.pop("_agent_reply", "")
    current_row.update({key: value for key, value in ai_row.items() if key in headers})
    if "category" in headers:
        current_row["category"] = normalize_category(current_row.get("category") or draft.get("category") or REQUIRED_CATEGORY)
    if "featured_image" in headers:
        current_row["featured_image"] = featured

    csv_text = write_single_row_csv(headers, current_row)
    zip_path = rebuild_session_package(session_dir, csv_text, state)
    updated_chat = [
        *chat_history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": agent_reply or "I updated the draft fields."},
    ]
    return {
        **draft,
        "category": normalize_category(current_row.get("category") or draft.get("category") or REQUIRED_CATEGORY),
        "csv_text": csv_text,
        "row": current_row,
        "chat": updated_chat,
        "zip_path": str(zip_path),
        "package_dir": str(session_dir / "draft" / "package"),
    }
