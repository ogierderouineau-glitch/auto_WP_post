import csv
import hashlib
import html
import json
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None

from config import OPENAI_API_KEY
from legacy.step_10_event_payload import ColumnSpec, safe_name


DEFAULT_TEXT_MODEL = "gpt-4o-mini"
REQUIRED_CATEGORY = "auto event post"
FAST_DRAFT_SINGLE_AI_PASS = True
MODEL_POST_HTML_PATH = Path(__file__).resolve().parent / "data/knowledge/event post model page.html"
OPENAI_USAGE_LOG_PATH = Path(__file__).resolve().parent / "data/api_logs/openai_usage.jsonl"

# Approximate USD rates per 1M tokens for quick cost visibility in logs.
# Keep this table updated with current OpenAI pricing when models change.
MODEL_PRICING_PER_MILLION: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}
_MODEL_STYLE_PROFILE_CACHE: dict[str, Any] | None = None
IMAGE_METADATA_FIELDNAMES = {
    "featured_image",
    "featured_image_alt",
    "featured_image_title",
    "featured_image_caption",
    "featured_image_description",
    "gallery_images",
    "gallery_alts",
    "gallery_titles",
    "gallery_captions",
    "gallery_descriptions",
}
CSV_IMAGE_METADATA_FIELDNAMES = IMAGE_METADATA_FIELDNAMES - {"featured_image"}


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


def title_looks_like_noisy_transcript(value: str) -> bool:
    text = strip_html_tags(value or "").strip().lower()
    if not text:
        return True
    bad_starts = (
        "hallo",
        "hi",
        "hier ist",
        "ich habe",
        "ich bin",
        "das war",
    )
    if text.startswith(bad_starts):
        return True
    words = re.findall(r"\b[\wÄÖÜäöüß-]+\b", text)
    if len(words) < 4:
        return True
    conversational_hits = sum(1 for token in ("ich", "hier", "hallo", "äh", "also") if token in words)
    return conversational_hits >= 2


def smart_slug(post_title: str, transcript: str, post_type: str) -> str:
    candidate = strip_html_tags(post_title or "").strip()
    if not title_looks_like_noisy_transcript(candidate):
        return slugify(candidate)

    transcript_words = re.findall(r"\b[\wÄÖÜäöüß-]+\b", strip_html_tags(transcript or "").lower())
    filtered = [word for word in transcript_words if len(word) >= 4][:6]
    if filtered:
        return slugify(" ".join(filtered))
    return slugify(f"flairlab-{post_type}-event")


def normalize_category(category: str) -> str:
    requested = [part.strip() for part in re.split(r"[,|]", category or "") if part.strip()]
    if not any(part.lower() == REQUIRED_CATEGORY for part in requested):
        requested.insert(0, REQUIRED_CATEGORY)
    return ", ".join(dict.fromkeys(requested))


def is_faq_field_name(value: str) -> bool:
    return str(value or "").strip().lower().startswith("faq_")


def default_faq_guidance(source_name: str) -> str:
    source = str(source_name or "").strip().lower()
    if source.endswith("_question"):
        return (
            "FAQ-Frage: Formuliere eine konkrete, natürliche Kundenfrage zum Event oder Service. "
            "Die Frage soll hilfreich für Buchungsinteressenten sein und sich klar vom restlichen Text unterscheiden."
        )
    if source.endswith("_answer"):
        return (
            "FAQ-Antwort: Beantworte die passende FAQ-Frage auf Deutsch in 45 bis 75 Wörtern. "
            "Nutze nur gesicherte Informationen aus Transkript, Medienkontext und Feldern. "
            "Wenn Details fehlen, antworte allgemein aber hilfreich für FLAIRLAB-Anfragen."
        )
    return "FAQ-Feld: Erzeuge hilfreichen deutschen FAQ-Inhalt passend zum Event und zur Buchungsentscheidung."


def merge_guidance_text(*parts: str) -> str:
    values = [str(part or "").strip() for part in parts if str(part or "").strip()]
    return "\n".join(dict.fromkeys(values))


def faq_fieldnames_from_specs(specs: list[ColumnSpec]) -> list[str]:
    return [
        spec.source_name
        for spec in specs
        if spec.source_name and (is_faq_field_name(spec.source_name) or is_faq_field_name(spec.acf_name))
    ]


def missing_faq_fieldnames(row: dict[str, str], specs: list[ColumnSpec]) -> list[str]:
    return [field for field in faq_fieldnames_from_specs(specs) if not str(row.get(field) or "").strip()]


def ensure_faq_guidance_on_specs(specs: list[ColumnSpec]) -> list[ColumnSpec]:
    for spec in specs:
        if spec.source_name and (is_faq_field_name(spec.source_name) or is_faq_field_name(spec.acf_name)):
            spec.guidance = merge_guidance_text(spec.guidance, default_faq_guidance(spec.source_name))
    return specs


def estimate_openai_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    pricing = MODEL_PRICING_PER_MILLION.get(model)
    if not pricing:
        return None
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


def openai_usage_entry(call_name: str, model: str, response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None

    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or (prompt_tokens + completion_tokens))
    estimated_cost_usd = estimate_openai_cost_usd(model, prompt_tokens, completion_tokens)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call": call_name,
        "model": model,
        "response_id": getattr(response, "id", None),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(estimated_cost_usd, 8) if estimated_cost_usd is not None else None,
    }


def log_openai_usage(call_name: str, model: str, response: Any) -> dict[str, Any] | None:
    entry = openai_usage_entry(call_name, model, response)
    if entry is None:
        return None

    OPENAI_USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OPENAI_USAGE_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def strip_html_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_sentence_for_compare(value: str) -> str:
    value = html.unescape(value or "")
    value = strip_html_tags(value)
    value = re.sub(r"[^a-zA-Z0-9\säöüÄÖÜß]", "", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def dedupe_sentences(text: str) -> str:
    if not text or len(text) < 10:
        return text

    parts = re.split(r"(?<=[.!?])\s+", text)
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        normalized = normalize_sentence_for_compare(part)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(part.strip())
    return " ".join(result).strip() or text


def dedupe_paragraphs(text: str) -> str:
    if not text:
        return text
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if len(paragraphs) < 2:
        return text

    seen: set[str] = set()
    kept: list[str] = []
    for paragraph in paragraphs:
        normalized = normalize_sentence_for_compare(paragraph)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        kept.append(paragraph)
    return "\n\n".join(kept) if kept else text


def clean_repetition(value: str) -> str:
    text = value or ""
    text = dedupe_paragraphs(text)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return text.strip()

    cleaned_paragraphs = [dedupe_sentences(paragraph) for paragraph in paragraphs]
    cleaned_paragraphs = [re.sub(r"[ \t]+", " ", paragraph).strip() for paragraph in cleaned_paragraphs if paragraph.strip()]
    return "\n\n".join(cleaned_paragraphs).strip()


def clean_row_repetition(row: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in row.items():
        if key.startswith("_"):
            cleaned[key] = value
            continue
        text = str(value or "")
        # Keep short/meta fields untouched; clean only narrative fields.
        if len(text) >= 20 and any(token in key.lower() for token in ("text", "description", "intro", "story", "hero", "section", "faq", "content", "excerpt", "caption", "cta")):
            cleaned[key] = clean_repetition(text)
        else:
            cleaned[key] = text
    return cleaned


def guidance_requires_double_braces(guidance: str) -> bool:
    text = (guidance or "").lower()
    return any(
        marker in text
        for marker in (
            "{{",
            "}}",
            "geschweifte",
            "curly",
            "double brace",
            "doppelklammer",
        )
    )


def is_heading_like_spec(spec: ColumnSpec) -> bool:
    source = (spec.source_name or "").lower()
    acf = (spec.acf_name or "").lower()
    heading_tokens = ("h1", "h2", "h3", "headline", "heading", "title")
    return any(token in source or token in acf for token in heading_tokens)


def inject_double_braces(value: str) -> str:
    text = (value or "").strip()
    if not text or ("{{" in text and "}}" in text):
        return text

    # Keep existing HTML untouched; this formatter is for plain heading text values.
    if "<" in text and ">" in text:
        return text

    words = text.split()
    if len(words) >= 4:
        phrase = " ".join(words[-2:])
    elif len(words) >= 2:
        phrase = words[-1]
    else:
        phrase = words[0]

    index = text.find(phrase)
    if index < 0:
        return text
    return f"{text[:index]}{{{{{phrase}}}}}{text[index + len(phrase):]}"


def enforce_heading_brace_formatting(row: dict[str, str], specs: list[ColumnSpec]) -> dict[str, str]:
    by_source = {spec.source_name: spec for spec in specs if spec.source_name}
    fixed = dict(row)
    for source, value in row.items():
        spec = by_source.get(source)
        if not spec or not value:
            continue

        needs_braces = guidance_requires_double_braces(spec.guidance or "")

        if needs_braces and is_heading_like_spec(spec):
            fixed[source] = inject_double_braces(str(value))
    return fixed


def count_words(value: str) -> int:
    plain = strip_html_tags(value or "")
    return len(re.findall(r"\b[\wÄÖÜäöüß-]+\b", plain))


def count_characters(value: str) -> int:
    plain = strip_html_tags(value or "")
    return len(plain.strip())


def target_tolerance(target: int, unit: str) -> int:
    if unit == "words":
        return max(15, int(target * 0.15))
    return max(60, int(target * 0.12))


def parse_guidance_length_constraint(guidance: str) -> dict[str, Any] | None:
    text = (guidance or "").lower()
    if not text:
        return None

    patterns = [
        ("words", r"w[öo]rter|words"),
        ("chars", r"zeichen|characters|chars"),
    ]

    for unit, unit_pattern in patterns:
        between = re.search(rf"zwischen\s+(\d+)\s+(?:und|bis)\s+(\d+)\s*(?:{unit_pattern})", text)
        if between:
            start = int(between.group(1))
            end = int(between.group(2))
            return {
                "unit": unit,
                "min": min(start, end),
                "max": max(start, end),
                "target": int((start + end) / 2),
                "guidance": guidance,
            }

        range_match = re.search(rf"(\d+)\s*(?:-|–|—|to)\s*(\d+)\s*(?:{unit_pattern})", text)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            return {
                "unit": unit,
                "min": min(start, end),
                "max": max(start, end),
                "target": int((start + end) / 2),
                "guidance": guidance,
            }

        minimum = re.search(rf"(?:mindestens|min\.?|at least)\s*(\d+)\s*(?:{unit_pattern})", text)
        maximum = re.search(rf"(?:maximal|h[öo]chstens|max\.?|at most|no more than)\s*(\d+)\s*(?:{unit_pattern})", text)
        approx = re.search(rf"(?:ca\.?|circa|ungef[äa]hr|about|around)\s*(\d+)\s*(?:{unit_pattern})", text)
        exact = re.search(rf"(\d+)\s*(?:{unit_pattern})", text)

        if minimum or maximum or approx or exact:
            min_value = int(minimum.group(1)) if minimum else None
            max_value = int(maximum.group(1)) if maximum else None
            target = int(approx.group(1)) if approx else None
            if target is None and exact and minimum is None and maximum is None:
                target = int(exact.group(1))

            if target is not None:
                tolerance = target_tolerance(target, unit)
                if min_value is None and minimum is None and maximum is None:
                    min_value = max(1, target - tolerance)
                if max_value is None and minimum is None and maximum is None:
                    max_value = target + tolerance

            if min_value is None and max_value is None:
                continue

            return {
                "unit": unit,
                "min": min_value,
                "max": max_value,
                "target": target,
                "guidance": guidance,
            }

    return None


def collect_length_constraints(specs: list[ColumnSpec]) -> dict[str, dict[str, Any]]:
    constraints: dict[str, dict[str, Any]] = {}
    for spec in specs:
        source = (spec.source_name or "").strip()
        if not source:
            continue

        # Use explicit schema constraints as source of truth when available.
        min_words = getattr(spec, "min_words", None)
        max_words = getattr(spec, "max_words", None)
        if min_words is not None or max_words is not None:
            target = None
            if min_words is not None and max_words is not None:
                target = int((min_words + max_words) / 2)
            elif min_words is not None:
                target = min_words
            constraints[source] = {
                "unit": "words",
                "min": min_words,
                "max": max_words,
                "target": target,
                "guidance": spec.guidance,
            }
            continue

        if not spec.guidance:
            continue
        constraint = parse_guidance_length_constraint(spec.guidance)
        if constraint:
            constraints[source] = constraint
    return constraints


def normalize_field_lookup(value: str) -> str:
    cleaned = str(value or "").strip().lower().replace("_", " ")
    cleaned = re.sub(r"[^a-z0-9äöüß\s-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def infer_target_fieldnames(message: str, specs: list[ColumnSpec]) -> list[str]:
    """Infer which CSV fields the user wants to revise from a chat message."""
    text = str(message or "").strip()
    if not text:
        return []

    normalized_message = normalize_field_lookup(text)
    by_alias: dict[str, str] = {}
    candidates: list[tuple[str, str, str]] = []
    for spec in specs:
        source = (spec.source_name or "").strip()
        if not source:
            continue
        display = str(getattr(spec, "display_name", "") or "").strip()
        acf = (spec.acf_name or "").strip()
        aliases = {source, source.replace("_", " "), display, acf}
        for alias in aliases:
            key = normalize_field_lookup(alias)
            if key:
                by_alias[key] = source
        candidates.append((source, normalize_field_lookup(source), normalize_field_lookup(display or acf or source)))

    matched: list[str] = []

    # Strong signal: "field_name: new text" style instructions.
    for raw_alias in re.findall(r"(?:^|\n|,|;)([a-zA-Z0-9_\-\säöüÄÖÜß]{3,60})\s*[:=]", text):
        key = normalize_field_lookup(raw_alias)
        source = by_alias.get(key)
        if source and source not in matched:
            matched.append(source)

    # Fallback: detect explicit field mentions inside free text.
    for source, source_lookup, label_lookup in candidates:
        if source in matched:
            continue
        if source_lookup and len(source_lookup) >= 4 and source_lookup in normalized_message:
            matched.append(source)
            continue
        if label_lookup and len(label_lookup) >= 4 and label_lookup in normalized_message:
            matched.append(source)

    return matched


def length_violations(row: dict[str, str], constraints: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for field, rule in constraints.items():
        value = (row.get(field) or "").strip()
        if not value:
            continue

        current = count_words(value) if rule["unit"] == "words" else count_characters(value)
        min_value = rule.get("min")
        max_value = rule.get("max")
        if min_value is not None and current < min_value:
            violations.append({"field": field, "current": current, **rule, "problem": "too_short"})
            continue
        if max_value is not None and current > max_value:
            violations.append({"field": field, "current": current, **rule, "problem": "too_long"})
    return violations


def build_length_audit(row: dict[str, str], specs: list[ColumnSpec]) -> list[dict[str, Any]]:
    constraints = collect_length_constraints(specs)
    by_source = {spec.source_name: spec for spec in specs if spec.source_name}
    violations = {
        (item["field"], item["problem"]): item
        for item in length_violations(row, constraints)
    }

    audit: list[dict[str, Any]] = []
    for field, rule in constraints.items():
        value = row.get(field, "")
        current = count_words(value) if rule["unit"] == "words" else count_characters(value)
        too_short = (rule.get("min") is not None and current < rule["min"])
        too_long = (rule.get("max") is not None and current > rule["max"])
        status = "ok"
        if too_short:
            status = "too_short"
        elif too_long:
            status = "too_long"

        spec = by_source.get(field)
        audit.append(
            {
                "field": field,
                "acf_field": (spec.acf_name if spec else "") or "",
                "unit": rule["unit"],
                "current": current,
                "min": rule.get("min"),
                "max": rule.get("max"),
                "target": rule.get("target"),
                "status": status,
                "guidance": rule.get("guidance", ""),
                "has_violation": (field, status) in violations if status != "ok" else False,
            }
        )
    return audit


def pad_to_min_words(value: str, min_words: int, transcript: str) -> str:
    text = (value or "").strip()
    current = count_words(text)
    if current >= min_words:
        return text

    source_words = re.findall(r"\b[\wÄÖÜäöüß-]+\b", strip_html_tags(transcript or ""))
    if not source_words:
        return text

    needed = max(0, min_words - current)
    extra: list[str] = []
    index = 0
    while len(extra) < needed and index < len(source_words) * 4:
        extra.append(source_words[index % len(source_words)])
        index += 1

    if not extra:
        return text

    suffix = " ".join(extra[:needed]).strip()
    if not suffix:
        return text

    if text and text[-1] not in ".!?":
        text = f"{text}."
    return f"{text} {suffix}".strip()


def trim_to_max_words(value: str, max_words: int) -> str:
    words = re.findall(r"\b[\wÄÖÜäöüß-]+\b", strip_html_tags(value or ""))
    if len(words) <= max_words:
        return (value or "").strip()
    return " ".join(words[:max_words]).strip()


def enforce_length_constraints_deterministic(
    row: dict[str, str],
    constraints: dict[str, dict[str, Any]],
    transcript: str,
) -> dict[str, str]:
    if not constraints:
        return row

    updated = dict(row)
    for field, rule in constraints.items():
        value = str(updated.get(field) or "").strip()
        if not value:
            continue

        if rule.get("unit") == "words":
            min_words = int(rule.get("min") or 0)
            max_words = int(rule.get("max") or 0)
            if min_words > 0 and count_words(value) < min_words:
                value = pad_to_min_words(value, min_words, transcript)
            if max_words > 0 and count_words(value) > max_words:
                value = trim_to_max_words(value, max_words)
        else:
            min_chars = int(rule.get("min") or 0)
            max_chars = int(rule.get("max") or 0)
            plain = strip_html_tags(value)
            if min_chars > 0 and len(plain) < min_chars:
                filler = strip_html_tags(transcript or "")
                missing = max(0, min_chars - len(plain))
                value = f"{value} {filler[:missing]}".strip() if filler else value
            if max_chars > 0 and len(strip_html_tags(value)) > max_chars:
                value = strip_html_tags(value)[:max_chars].strip()

        updated[field] = value
    return updated


def apply_length_guidance_correction(
    client: Any,
    base_row: dict[str, str],
    violations: list[dict[str, Any]],
    transcript: str,
    post_type: str,
    category: str,
    featured_image_filename: str,
    image_names: list[str],
    chat_history: list[dict[str, str]] | None,
    usage_events: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    response = client.chat.completions.create(
        model=DEFAULT_TEXT_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict CSV field length corrector. "
                    "Return JSON with key 'row'. "
                    "Only change fields listed in violations. "
                    "Keep meaning and tone, but adjust length to fit each field requirement."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "transcript": transcript,
                        "post_type": post_type,
                        "selected_category": normalize_category(category),
                        "featured_image_filename": featured_image_filename,
                        "image_names": image_names,
                        "current_row": base_row,
                        "violations": violations,
                        "chat_history": chat_history or [],
                        "instructions": (
                            "Rewrite only violating fields to satisfy min/max constraints by unit. "
                            "Do not add bullets/labels for facts fields. "
                            "Keep output in German and preserve key intent."
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        temperature=0.2,
    )
    usage_entry = log_openai_usage("generate_ai_field_row_length_correction", DEFAULT_TEXT_MODEL, response)
    if usage_events is not None and usage_entry is not None:
        usage_events.append(usage_entry)
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    row = data.get("row", data)
    if not isinstance(row, dict):
        return {}
    return {str(key): str(value) for key, value in row.items() if value is not None}


def extract_model_style_profile(model_html_path: Path = MODEL_POST_HTML_PATH) -> dict[str, Any]:
    global _MODEL_STYLE_PROFILE_CACHE
    if _MODEL_STYLE_PROFILE_CACHE is not None:
        return _MODEL_STYLE_PROFILE_CACHE

    if not model_html_path.exists() or not model_html_path.is_file():
        _MODEL_STYLE_PROFILE_CACHE = {"available": False, "path": str(model_html_path)}
        return _MODEL_STYLE_PROFILE_CACHE

    raw = model_html_path.read_text(encoding="utf-8", errors="ignore")
    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw, re.IGNORECASE | re.DOTALL)
    html_body = body_match.group(1) if body_match else raw

    # Drop heavy technical content before extracting style signals.
    html_body = re.sub(r"<script\b[^>]*>.*?</script>", " ", html_body, flags=re.IGNORECASE | re.DOTALL)
    html_body = re.sub(r"<style\b[^>]*>.*?</style>", " ", html_body, flags=re.IGNORECASE | re.DOTALL)
    html_body = re.sub(r"<!--.*?-->", " ", html_body, flags=re.DOTALL)

    paragraph_blocks = [strip_html_tags(chunk) for chunk in re.findall(r"<p\b[^>]*>(.*?)</p>", html_body, flags=re.IGNORECASE | re.DOTALL)]
    paragraph_blocks = [p for p in paragraph_blocks if len(p.split()) >= 8]

    heading_blocks = [strip_html_tags(chunk) for chunk in re.findall(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", html_body, flags=re.IGNORECASE | re.DOTALL)]
    heading_blocks = [h for h in heading_blocks if h]

    noise_markers = (
        "javascript",
        "cookie",
        "elementor",
        "plugin",
        "wp-",
        "wordpress",
        "site kit",
        "admin bar",
        "cdn.",
        "gtm",
        "google tag",
        "sourceurl",
    )

    def is_editorial_line(text: str) -> bool:
        lowered = text.lower()
        if any(marker in lowered for marker in noise_markers):
            return False
        return len(re.findall(r"\w+", text)) >= 3

    paragraph_blocks = [p for p in paragraph_blocks if is_editorial_line(p)]
    heading_blocks = [h for h in heading_blocks if is_editorial_line(h)]

    tag_names = re.findall(r"<\s*([a-zA-Z0-9]+)\b", html_body)
    tag_counter = Counter(tag.lower() for tag in tag_names)
    common_tags = [tag for tag, _count in tag_counter.most_common(12) if tag not in {"div", "span", "section", "article", "meta", "link"}][:8]

    paragraph_lengths = [len(re.findall(r"\S+", p)) for p in paragraph_blocks]
    avg_paragraph_words = int(sum(paragraph_lengths) / len(paragraph_lengths)) if paragraph_lengths else 0

    sample_chunks = (heading_blocks[:4] + paragraph_blocks[:6])
    style_excerpt = "\n".join(sample_chunks)
    style_excerpt = style_excerpt[:2200]

    _MODEL_STYLE_PROFILE_CACHE = {
        "available": True,
        "path": str(model_html_path),
        "paragraph_count": len(paragraph_blocks),
        "heading_count": len(heading_blocks),
        "avg_paragraph_words": avg_paragraph_words,
        "common_html_tags": common_tags,
        "style_excerpt": style_excerpt,
    }
    return _MODEL_STYLE_PROFILE_CACHE


def draft_generation_signature(
    transcript: str,
    post_type: str,
    category: str,
    featured_image_filename: str,
    image_names: list[str],
    specs: list[ColumnSpec],
) -> str:
    specs_fingerprint = [
        {
            "source_name": spec.source_name,
            "acf_name": spec.acf_name,
            "marker": spec.marker,
            "guidance": spec.guidance,
        }
        for spec in specs
    ]
    payload = {
        "transcript": transcript,
        "post_type": post_type,
        "category": normalize_category(category),
        "featured_image_filename": featured_image_filename,
        "image_names": image_names,
        "specs": specs_fingerprint,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_ai_draft(
    transcript: str,
    post_type: str,
    category: str,
    image_names: list[str],
    usage_events: list[dict[str, Any]] | None = None,
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
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.4,
        )
        usage_entry = log_openai_usage("generate_ai_draft", DEFAULT_TEXT_MODEL, response)
        if usage_events is not None and usage_entry is not None:
            usage_events.append(usage_entry)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception:
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def specs_for_prompt(specs: list[ColumnSpec]) -> list[dict[str, Any]]:
    specs = ensure_faq_guidance_on_specs(specs)
    return [
        {
            "source_name": spec.source_name,
            "marker": spec.marker,
            "acf_name": spec.acf_name,
            "guidance": spec.guidance,
            "guidance_lines": [line.strip() for line in (spec.guidance or "").splitlines() if line.strip()],
            "is_repeated_acf_part": bool(spec.acf_name and sum(1 for item in specs if item.acf_name == spec.acf_name) > 1),
            "fact_label_generated_by_importer": bool(spec.acf_name and ("fakten" in spec.acf_name.lower() or "facts" in spec.acf_name.lower())),
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
    target_fieldnames: list[str] | None = None,
    usage_events: list[dict[str, Any]] | None = None,
    guidance_data: dict[str, Any] | None = None,
    internal_links_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    if not OPENAI_API_KEY or OpenAI is None:
        return {}

    client = OpenAI(api_key=OPENAI_API_KEY)
    requested_targets = [name for name in (target_fieldnames or []) if name]
    allowed_targets = set(requested_targets)
    prompt_specs = [
        spec for spec in specs
        if spec.source_name and (not allowed_targets or spec.source_name in allowed_targets)
    ]
    prompt_specs = ensure_faq_guidance_on_specs(prompt_specs)
    fieldnames = [spec.source_name for spec in prompt_specs if spec.source_name]
    constraints = collect_length_constraints(prompt_specs)
    try:
        model_style = extract_model_style_profile()
        response = client.chat.completions.create(
            model=DEFAULT_TEXT_MODEL,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are FLAIRLAB's WordPress event post drafting agent. "
                        "Fill one CSV row using exact source_name keys. Return JSON: {\"row\": {...}, \"reply\": \"...\"}. "
                        "Write polished German copy. Treat guidance as hard requirements (word counts, tone, structure). "
                        "For facts/fakten fields: one fact per field, no bullets/labels/HTML (importer adds key/formatting). "
                        "For SEO fields: follow seo_guidance_context exactly if provided. "
                        "For fields with repeated acf_name (e.g., verlauf_text + fakten): each source contributes one part only. "
                        "Do not invent facts; use transcript and instructions only. "
                        "Use featured_image filename exactly. Reference model_style_profile for length/rhythm guidance. "
                        "Never repeat sentences across fields unless field purpose requires it."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "csv_fields": specs_for_prompt(prompt_specs),
                            "allowed_fieldnames": fieldnames,
                            "transcript": transcript,
                            "post_type": post_type,
                            "selected_category": normalize_category(category),
                            "featured_image_filename": featured_image_filename,
                            "image_names": image_names,
                            "model_style_profile": model_style,
                            "current_row": current_row or {},
                            "chat_history": chat_history or [],
                            "field_contract": (
                                "Only generate/update fields in csv_fields below. Return null/empty for all fields NOT in csv_fields. "
                                "Preserve all existing current_row fields not listed in csv_fields."
                                if allowed_targets else
                                "Every csv_fields item is a contract. Fill every relevant allowed_fieldname. "
                                "For ACF fields with guidance, obey the guidance in that item. "
                                "For repeated acf_name groups, each source field is one segment of the final ACF field. "
                                "No duplicate lines across hero, sections, CTA, FAQ, or captions."
                            ),
                            "update_scope": (
                                f"Only update these fields: {fieldnames}. Keep all other current_row fields unchanged."
                                if fieldnames else
                                "Update the full row."
                            ),
                            "seo_guidance_context": (
                                guidance_data.get("items", [])
                                if guidance_data else
                                []
                            ),
                            "internal_links_context": (
                                {
                                    "rules": list((internal_links_context or {}).get("rules") or []),
                                    "candidate_links": list((internal_links_context or {}).get("database") or [])[:20],
                                    "target_field": "related_links_html",
                                    "target_field_html_template": (
                                        "<div class=\"post-tags\"><span class=\"tag-links\">Related: "
                                        "<a href=\"...\">...</a>, <a href=\"...\">...</a></span></div>"
                                    ),
                                    "requirements": [
                                        "Use only internal_links_database entries with active=true.",
                                        "Follow internal_link_rules with applies_to=internal_links.",
                                        "Avoid self-linking by considering avoid_if_current_slug.",
                                        "Render 2-4 links unless rules specify another range.",
                                    ],
                                }
                                if "related_links_html" in fieldnames
                                else None
                            ),
                            "user_message": user_message
                            or (
                                "Generate the best complete draft. Pay special attention to: "
                                "event_story (must be a polished narrative summary of at least 100 words from the transcript), "
                                "hero fields, CTA title/text, FAQ content, facts/fakten fields, and SEO fields "
                                "(focus_keyword, seo_title, meta_description, social_title, social_description)."
                                + (
                                    " Fill related_links_html with valid internal links HTML using the candidate_links provided."
                                    if "related_links_html" in fieldnames else ""
                                )
                            ),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.35,
        )
        usage_entry = log_openai_usage("generate_ai_field_row", DEFAULT_TEXT_MODEL, response)
        if usage_events is not None and usage_entry is not None:
            usage_events.append(usage_entry)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        row = data.get("row", data)
        if not isinstance(row, dict):
            return {}
        fieldnames_set = set(fieldnames)
        normalized_fieldnames = {
            normalize_field_lookup(name): name
            for name in fieldnames
            if normalize_field_lookup(name)
        }
        normalized_aliases = {
            "bartender title": "bartender tile",
            "bartender tile": "bartender title",
        }
        result: dict[str, str] = {}
        for key, value in row.items():
            if value is None:
                continue
            raw_key = str(key).strip()
            canonical_key = raw_key if raw_key in fieldnames_set else ""
            if not canonical_key:
                normalized_key = normalize_field_lookup(raw_key)
                canonical_key = normalized_fieldnames.get(normalized_key, "")
                if not canonical_key:
                    alias_key = normalized_aliases.get(normalized_key, "")
                    canonical_key = normalized_fieldnames.get(alias_key, "")
            if canonical_key:
                result[canonical_key] = str(value)
        
        # Enforce selective field generation: preserve non-target fields from current_row
        if allowed_targets and current_row:
            for key in fieldnames:
                if key not in allowed_targets and key in current_row:
                    result[key] = current_row[key]
        
        result = clean_row_repetition(result)

        remaining_violations = length_violations(result, constraints) if constraints else []
        for _ in range(3):
            if not remaining_violations:
                break
            corrected = apply_length_guidance_correction(
                client=client,
                base_row=result,
                violations=remaining_violations,
                transcript=transcript,
                post_type=post_type,
                category=category,
                featured_image_filename=featured_image_filename,
                image_names=image_names,
                chat_history=chat_history,
                usage_events=usage_events,
            )
            if not corrected:
                break

            changed = False
            for key, value in corrected.items():
                if key in fieldnames and result.get(key) != value:
                    result[key] = value
                    changed = True
            if not changed:
                break

            result = clean_row_repetition(result)
            remaining_violations = length_violations(result, constraints) if constraints else []

        result = enforce_length_constraints_deterministic(result, constraints, transcript)
        result = clean_row_repetition(result)

        remaining_violations = length_violations(result, constraints) if constraints else []
        if data.get("reply"):
            result["_agent_reply"] = str(data["reply"])
        if remaining_violations:
            violation_msg = ", ".join(
                f"{item['field']} ({item['current']} {item['unit']})"
                for item in remaining_violations[:6]
            )
            existing_reply = result.get("_agent_reply", "")
            suffix = f" Length constraints still need review for: {violation_msg}."
            result["_agent_reply"] = f"{existing_reply}{suffix}".strip()
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

    return {
        "post_title": title,
        "title": title,
        "slug": slugify(title),
        "excerpt": excerpt,
        "post_excerpt": excerpt,
        "category": normalize_category(category),
        "tags": post_type,
        "hero_title": title,
        "hero_description": excerpt,
        "section_1_title": "Ausgangssituation",
        "section_1_text": transcript,
        "section_2_title": "Umsetzung",
        "section_2_text": transcript,
        "cta_title": "Event mit FLAIRLAB planen",
        "cta_text": "FLAIRLAB unterstützt Events mit mobiler Bar, Drinks und professionellem Service.",
    }


def humanize_image_name(value: str) -> str:
    stem = Path(str(value or "")).stem
    label = re.sub(r"[_-]+", " ", stem).strip()
    return label[:1].upper() + label[1:] if label else ""


def suggest_image_metadata_for_state(state: dict[str, Any], filename: str) -> dict[str, str]:
    files = state.get("files", {}) if isinstance(state, dict) else {}
    images = [item for item in list(files.get("images") or []) if isinstance(item, dict)]
    featured_filename = str(files.get("featured_image_filename") or "").strip()
    transcript = str((state.get("transcript") or {}).get("text") or "").strip()
    post_type = str(state.get("post_type") or "Event")

    draft_row: dict[str, str] = {}
    draft_csv = str((state.get("draft") or {}).get("csv_text") or "")
    if draft_csv:
        _, draft_row = parse_single_row_csv(draft_csv)

    title = (
        str(draft_row.get("post_title") or draft_row.get("title") or "").strip()
        or fallback_title(transcript, post_type)
    )
    excerpt = (
        str(draft_row.get("excerpt") or draft_row.get("post_excerpt") or "").strip()
        or compact_words(transcript, 28)
    )

    image_item = next((item for item in images if str(item.get("filename") or "") == filename), None)
    label = humanize_image_name(
        str((image_item or {}).get("original_filename") or (image_item or {}).get("filename") or filename)
    )

    if featured_filename and filename == featured_filename:
        return {
            "alt_text": f"{title} von FLAIRLAB",
            "title": title,
            "caption": title,
            "description": excerpt,
        }

    gallery_items = [item for item in images if str(item.get("filename") or "") != featured_filename]
    gallery_index = next(
        (index + 1 for index, item in enumerate(gallery_items) if str(item.get("filename") or "") == filename),
        1,
    )
    gallery_title = f"{title} - Galerie {gallery_index}"
    gallery_alt = f"{title} - Galeriebild {gallery_index}"
    gallery_caption = label or f"Galeriebild {gallery_index}"
    return {
        "alt_text": gallery_alt,
        "title": gallery_title,
        "caption": gallery_caption,
        "description": excerpt,
    }


def collect_session_image_metadata_overrides(state: dict[str, Any]) -> dict[str, str]:
    files = state.get("files", {}) if isinstance(state, dict) else {}
    images = [item for item in list(files.get("images") or []) if isinstance(item, dict)]
    featured_filename = str(files.get("featured_image_filename") or "").strip()
    if not featured_filename and images:
        featured_filename = str(images[0].get("filename") or "").strip()

    def effective_metadata(item: dict[str, Any]) -> dict[str, str]:
        raw = item.get("wp_metadata")
        if isinstance(raw, dict):
            return {
                "alt_text": str(raw.get("alt_text") or "").strip(),
                "title": str(raw.get("title") or "").strip(),
                "caption": str(raw.get("caption") or "").strip(),
                "description": str(raw.get("description") or "").strip(),
            }
        return suggest_image_metadata_for_state(state, str(item.get("filename") or ""))

    featured_item = next(
        (item for item in images if str(item.get("filename") or "").strip() == featured_filename),
        images[0] if images else None,
    )
    featured_meta = effective_metadata(featured_item) if isinstance(featured_item, dict) else {
        "alt_text": "",
        "title": "",
        "caption": "",
        "description": "",
    }

    gallery_items = [
        item for item in images
        if str(item.get("filename") or "").strip() != featured_filename
    ]
    gallery_meta = [effective_metadata(item) for item in gallery_items]

    return {
        "featured_image": featured_filename,
        "featured_image_alt": featured_meta.get("alt_text", ""),
        "featured_image_title": featured_meta.get("title", ""),
        "featured_image_caption": featured_meta.get("caption", ""),
        "featured_image_description": featured_meta.get("description", ""),
        "gallery_alts": " | ".join(item.get("alt_text", "") for item in gallery_meta),
        "gallery_titles": " | ".join(item.get("title", "") for item in gallery_meta),
        "gallery_captions": " | ".join(item.get("caption", "") for item in gallery_meta),
        "gallery_descriptions": " | ".join(item.get("description", "") for item in gallery_meta),
    }


def sync_session_image_metadata_csv(csv_text: str, state: dict[str, Any]) -> str:
    headers, row = parse_single_row_csv(csv_text or "")
    if not headers:
        return csv_text
    row.update(collect_session_image_metadata_overrides(state))
    return write_single_row_csv(headers, row)


def value_for_source(source_name: str, acf_name: str, values: dict[str, str], transcript: str) -> str:
    source = source_name.strip()
    if source in values:
        return values[source]

    normalized = source.lower()
    if normalized in {"content", "post_content", "body", "text"}:
        return transcript
    if "title" in normalized:
        return values["post_title"]
    if any(token in normalized for token in ("description", "excerpt", "summary")):
        return values["excerpt"]
    if any(token in normalized for token in ("text", "copy", "content")):
        return transcript
    if "faq" in normalized:
        return ""
    if "fakten" in normalized or "facts" in normalized:
        return compact_words(transcript, 14)
    if "story" in normalized or "verlauf" in normalized:
        return transcript
    return ""


def parse_internal_link_count(rules: list[dict[str, Any]]) -> tuple[int, int]:
    min_links = 2
    max_links = 4
    for rule in rules:
        applies = str(rule.get("applies_to") or "").strip().lower()
        instruction = str(rule.get("instruction") or "")
        value = str(rule.get("value") or "")
        if applies and applies != "internal_links":
            continue
        text = f"{value} {instruction}"
        match = re.search(r"(\d+)\s*[-–]\s*(\d+)", text)
        if match:
            left = int(match.group(1))
            right = int(match.group(2))
            min_links = min(left, right)
            max_links = max(left, right)
            break
    return min_links, max_links


def tokenize_text(value: str) -> set[str]:
    return {token.lower() for token in re.findall(r"\b[\wÄÖÜäöüß-]{3,}\b", value or "")}


def pick_internal_links_for_row(
    row: dict[str, str],
    transcript: str,
    internal_links_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    context = internal_links_context or {}
    database = list(context.get("database") or [])
    rules = list(context.get("rules") or [])
    if not database:
        return []

    min_links, max_links = parse_internal_link_count(rules)
    slug = smart_slug(row.get("post_title") or row.get("title") or "", transcript, "Event")
    searchable = " ".join(
        [
            transcript,
            row.get("post_title", ""),
            row.get("title", ""),
            row.get("excerpt", ""),
            row.get("hero_title", ""),
            row.get("hero_description", ""),
            row.get("section_1_text", ""),
            row.get("section_2_text", ""),
            row.get("tags", ""),
            row.get("category", ""),
        ]
    )
    tokens = tokenize_text(searchable)
    city_tokens = {"berlin", "hamburg", "münchen", "munchen", "köln", "koeln", "frankfurt"}

    def score(item: dict[str, Any]) -> int:
        points = 0
        priority = str(item.get("priority") or "").strip().lower()
        if priority == "high":
            points += 40
        elif priority == "medium":
            points += 20
        elif priority == "low":
            points += 10

        keyword_tokens = tokenize_text(str(item.get("keyword") or ""))
        anchor_tokens = tokenize_text(str(item.get("anchor_text") or ""))
        context_tokens = tokenize_text(str(item.get("usage_context") or ""))
        points += 8 * len(tokens.intersection(keyword_tokens))
        points += 5 * len(tokens.intersection(anchor_tokens))
        points += 3 * len(tokens.intersection(context_tokens))

        city = str(item.get("city") or "").strip().lower()
        if city and city in tokens:
            points += 12
        elif city and city in city_tokens and city not in tokens:
            points -= 2

        category = str(item.get("category") or "").strip().lower()
        if category and category in searchable.lower():
            points += 6

        avoid_slug = slugify(str(item.get("avoid_if_current_slug") or ""))
        if avoid_slug and avoid_slug in slug:
            points -= 1000
        return points

    ranked = sorted(database, key=score, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in ranked:
        url = str(item.get("target_url") or "").strip()
        if not url or url in seen_urls:
            continue
        if score(item) < 5:
            continue
        selected.append(item)
        seen_urls.add(url)
        if len(selected) >= max_links:
            break

    if len(selected) < min_links:
        for item in ranked:
            url = str(item.get("target_url") or "").strip()
            if not url or url in seen_urls:
                continue
            selected.append(item)
            seen_urls.add(url)
            if len(selected) >= min_links:
                break
    return selected[:max_links]


def build_related_links_html(links: list[dict[str, Any]]) -> str:
    if not links:
        return ""
    anchors = [
        f'<a href="{html.escape(str(item.get("target_url") or ""), quote=True)}">{html.escape(str(item.get("anchor_text") or ""))}</a>'
        for item in links
        if str(item.get("target_url") or "").strip() and str(item.get("anchor_text") or "").strip()
    ]
    if not anchors:
        return ""
    return (
        '<div class="post-tags">\n'
        '  <span class="tag-links">\n'
        '    Related:\n'
        f"    {', '.join(anchors)}\n"
        '  </span>\n'
        '</div>'
    )


def build_event_csv(
    specs: list[ColumnSpec],
    transcript: str,
    post_type: str,
    category: str,
    featured_image_filename: str,
    image_names: list[str],
    usage_events: list[dict[str, Any]] | None = None,
    guidance_data: dict[str, Any] | None = None,
    internal_links_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, str]]:
    values = base_draft_values(
        transcript=transcript,
        post_type=post_type,
        category=category,
        featured_image_filename=featured_image_filename,
        image_names=image_names,
    )
    if not FAST_DRAFT_SINGLE_AI_PASS:
        values.update(
            {
                key: value
                for key, value in generate_ai_draft(transcript, post_type, category, image_names, usage_events=usage_events).items()
                if value
            }
        )
    values["post_title"] = values.get("post_title") or values.get("title") or fallback_title(transcript, post_type)
    values["title"] = values["post_title"]
    values["category"] = normalize_category(values.get("category") or category)
    values["slug"] = smart_slug(values.get("post_title") or values.get("title") or "", transcript, post_type)

    fieldnames = [
        spec.source_name
        for spec in specs
        if spec.source_name and spec.source_name not in CSV_IMAGE_METADATA_FIELDNAMES
    ]
    ai_specs = [
        spec
        for spec in specs
        if spec.source_name and spec.source_name not in CSV_IMAGE_METADATA_FIELDNAMES
    ]
    if not fieldnames:
        fieldnames = sorted(key for key in values if key not in CSV_IMAGE_METADATA_FIELDNAMES)
    row = {
        source: value_for_source(source, next((spec.acf_name for spec in specs if spec.source_name == source), ""), values, transcript)
        for source in fieldnames
    }
    ai_row = generate_ai_field_row(
        specs=ai_specs,
        transcript=transcript,
        post_type=post_type,
        category=category,
        featured_image_filename=featured_image_filename,
        image_names=image_names,
        current_row=row,
        usage_events=usage_events,
        guidance_data=guidance_data or {},
        internal_links_context=internal_links_context or {},
    )
    agent_reply = ai_row.pop("_agent_reply", "")
    row.update({key: value for key, value in ai_row.items() if value})

    missing_faq = missing_faq_fieldnames(row, ai_specs)
    if missing_faq:
        faq_row = generate_ai_field_row(
            specs=ai_specs,
            transcript=transcript,
            post_type=post_type,
            category=category,
            featured_image_filename=featured_image_filename,
            image_names=image_names,
            current_row=row,
            target_fieldnames=missing_faq,
            user_message=(
                "Die FAQ-Felder sind leer geblieben. Fülle jetzt ausschließlich die fehlenden FAQ-Fragen "
                "und FAQ-Antworten. Erzeuge praktische Kundenfragen und konkrete, hilfreiche Antworten "
                "auf Deutsch. Nutze nur Informationen aus Transkript, Medienkontext und vorhandenen Feldern."
            ),
            usage_events=usage_events,
            guidance_data=guidance_data or {},
            internal_links_context=internal_links_context or {},
        )
        faq_reply = faq_row.pop("_agent_reply", "")
        row.update({key: value for key, value in faq_row.items() if key in missing_faq and value})
        if faq_reply:
            agent_reply = f"{agent_reply} {faq_reply}".strip()

    row = clean_row_repetition(row)
    row = enforce_heading_brace_formatting(row, specs)

    if "related_links_html" in fieldnames and not str(row.get("related_links_html") or "").strip():
        selected_links = pick_internal_links_for_row(row, transcript, internal_links_context)
        generated_html = build_related_links_html(selected_links)
        if generated_html:
            row["related_links_html"] = generated_html

    row["category"] = normalize_category(row.get("category") or category)
    row["slug"] = smart_slug(row.get("post_title") or row.get("title") or values.get("post_title") or "", transcript, post_type)

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow({name: row.get(name, "") for name in fieldnames})
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


def count_words(text: str) -> int:
    """Count words in text."""
    return len(re.findall(r"\b\w+\b", str(text or "").strip()))


def generate_refinement_questions(
    row: dict[str, str],
    specs: list[ColumnSpec],
    guidance_data: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Auto-generate questions for fields that are empty or too short.
    Returns list of {"field": "...", "label": "...", "question": "...", "color": "..."}.
    Color codes: "warning" for empty, "info" for short.
    """
    from app_knowledge_base import guidance_for_field

    questions = []
    
    for spec in specs:
        if not spec.source_name or spec.source_name in ("featured_image", "category", "slug"):
            continue
        if spec.source_name in IMAGE_METADATA_FIELDNAMES:
            continue
        if spec.source_name not in row:
            continue
        
        value = row.get(spec.source_name, "").strip()
        word_count = count_words(value)
        min_words = spec.min_words or 0
        max_words = spec.max_words or 0
        
        # Determine if field needs attention
        is_empty = not value
        is_too_short = min_words > 0 and word_count < min_words
        
        if is_empty or is_too_short:
            label = spec.display_name or spec.source_name
            guidances = guidance_for_field(guidance_data, spec.source_name, spec.acf_name or "")
            guidance_text = "; ".join(guidances) if guidances else ""
            
            if is_empty:
                question = f"Kannst du Details für '{label}' liefern?" + (f" ({guidance_text})" if guidance_text else "")
                color = "warning"
            else:
                needed_words = min_words - word_count
                question = f"'{label}' hat nur {word_count} Wörter, braucht aber mindestens {min_words}. Kannst du {needed_words} mehr Wörter hinzufügen?"
                color = "info"
            
            questions.append({
                "field": spec.source_name,
                "label": label,
                "question": question,
                "color": color,
                "current_value": value,
                "min_words": min_words,
                "max_words": max_words,
            })
    
    return questions


def create_session_draft(
    session_dir: Path,
    state: dict[str, Any],
    specs: list[ColumnSpec],
    category: str,
    force_regenerate: bool = False,
    guidance_data: dict[str, Any] | None = None,
    internal_links_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    transcript = state.get("transcript", {}).get("text", "").strip()
    if not transcript:
        raise ValueError("Transcript is required before generating a draft.")

    images = state.get("files", {}).get("images", [])
    featured = state.get("files", {}).get("featured_image_filename") or (images[0]["filename"] if images else "")
    image_names = [item["filename"] for item in images]
    normalized_category = normalize_category(category)
    generation_signature = draft_generation_signature(
        transcript=transcript,
        post_type=state.get("post_type", "Event"),
        category=normalized_category,
        featured_image_filename=featured,
        image_names=image_names,
        specs=specs,
    )

    previous_draft = state.get("draft") if isinstance(state.get("draft"), dict) else {}
    if (
        not force_regenerate
        and
        previous_draft
        and previous_draft.get("generation_signature") == generation_signature
        and previous_draft.get("csv_text")
    ):
        draft = dict(previous_draft)
        zip_path_value = draft.get("zip_path")
        zip_exists = bool(zip_path_value) and Path(str(zip_path_value)).exists()
        if not zip_exists:
            zip_path = rebuild_session_package(session_dir, draft.get("csv_text", ""), state)
            draft["zip_path"] = str(zip_path)
        draft["package_dir"] = str(session_dir / "draft" / "package")
        draft["generation_signature"] = generation_signature
        draft["generation_mode"] = "cached"
        draft["_usage_events"] = []
        return draft

    usage_events: list[dict[str, Any]] = []

    csv_text, row = build_event_csv(
        specs=specs,
        transcript=transcript,
        post_type=state.get("post_type", "Event"),
        category=normalized_category,
        featured_image_filename=featured,
        image_names=image_names,
        usage_events=usage_events,
        guidance_data=guidance_data,
        internal_links_context=internal_links_context,
    )
    agent_reply = row.pop("_agent_reply", "")
    if agent_reply:
        row["_agent_reply"] = agent_reply
    zip_path = rebuild_session_package(session_dir, csv_text, state)
    length_audit = build_length_audit(row, specs)
    
    # Generate refinement questions for weak/empty fields
    questions = generate_refinement_questions(row, specs, guidance_data or {})
    
    # Build chat response with questions
    chat = [
        {
            "role": "assistant",
            "content": row.get("_agent_reply") or "Draft CSV generated successfully! 🎉",
        }
    ]
    
    if questions:
        questions_text = "Ich habe ein paar Fragen zu bessern Details:\n\n"
        for i, q in enumerate(questions, 1):
            color_emoji = "⚠️" if q["color"] == "warning" else "ℹ️"
            questions_text += f"{color_emoji} **{q['label']}**: {q['question']}\n"
        
        chat.append({
            "role": "assistant",
            "content": questions_text,
            "questions": questions,
            "type": "refinement",
        })
    else:
        chat.append({
            "role": "assistant",
            "content": "Kontext-Check abgeschlossen: Es wurden keine fehlenden Pflichtinformationen erkannt.",
            "questions": [],
            "type": "refinement",
        })
    
    return {
        "category": normalized_category,
        "csv_text": csv_text,
        "row": row,
        "length_audit": length_audit,
        "generation_signature": generation_signature,
        "generation_mode": "fresh_ai",
        "chat": chat,
        "zip_path": str(zip_path),
        "package_dir": str(session_dir / "draft" / "package"),
        "_usage_events": usage_events,
    }


def revise_session_draft(
    session_dir: Path,
    state: dict[str, Any],
    specs: list[ColumnSpec],
    message: str,
    guidance_data: dict[str, Any] | None = None,
    internal_links_context: dict[str, Any] | None = None,
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
    target_fields = infer_target_fieldnames(message, specs)
    selected_specs = [spec for spec in specs if spec.source_name in set(target_fields)] if target_fields else specs
    scoped_message = message
    if target_fields:
        scoped_message = (
            f"{message}\n\n"
            f"Bitte nur diese Felder aktualisieren: {', '.join(target_fields)}."
        )

    usage_events: list[dict[str, Any]] = []
    ai_row = generate_ai_field_row(
        specs=selected_specs,
        transcript=transcript,
        post_type=state.get("post_type", "Event"),
        category=draft.get("category") or current_row.get("category") or REQUIRED_CATEGORY,
        featured_image_filename=featured,
        image_names=image_names,
        current_row=current_row,
        chat_history=chat_history,
        user_message=scoped_message,
        target_fieldnames=target_fields,
        usage_events=usage_events,
        guidance_data=guidance_data,
        internal_links_context=internal_links_context,
    )
    agent_reply = ai_row.pop("_agent_reply", "")
    current_row.update({key: value for key, value in ai_row.items() if key in headers})
    current_row = clean_row_repetition(current_row)
    current_row = enforce_heading_brace_formatting(current_row, specs)
    if "category" in headers:
        current_row["category"] = normalize_category(current_row.get("category") or draft.get("category") or REQUIRED_CATEGORY)
    if "featured_image" in headers:
        current_row["featured_image"] = featured
    if "related_links_html" in headers and not str(current_row.get("related_links_html") or "").strip():
        selected_links = pick_internal_links_for_row(current_row, transcript, internal_links_context)
        generated_html = build_related_links_html(selected_links)
        if generated_html:
            current_row["related_links_html"] = generated_html

    csv_text = write_single_row_csv(headers, current_row)
    zip_path = rebuild_session_package(session_dir, csv_text, state)
    length_audit = build_length_audit(current_row, specs)
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
        "length_audit": length_audit,
        "chat": updated_chat,
        "zip_path": str(zip_path),
        "package_dir": str(session_dir / "draft" / "package"),
        "_usage_events": usage_events,
    }


def apply_refinement_answers(
    session_dir: Path,
    state: dict[str, Any],
    specs: list[ColumnSpec],
    answers: dict[str, str],
    transcript: str,
) -> dict[str, Any]:
    """
    Apply user answers to refinement questions, update draft, enforce constraints.
    answers: {"field_name": "user provided text", ...}
    """
    draft = state.get("draft", {})
    headers, current_row = parse_single_row_csv(draft.get("csv_text", ""))
    if not headers:
        headers = [spec.source_name for spec in specs if spec.source_name]
        current_row = {}

    # Apply user answers to the row
    for field_name, answer_text in answers.items():
        if field_name in headers:
            current_row[field_name] = answer_text.strip()
    
    # Rebuild constraints dict from specs
    constraints = {}
    for spec in specs:
        if spec.source_name and (spec.min_words or spec.max_words):
            constraints[spec.source_name] = {
                "min_words": spec.min_words or 0,
                "max_words": spec.max_words or 0,
            }
    
    # Enforce length constraints on updated fields
    current_row = enforce_length_constraints_deterministic(
        current_row, constraints, transcript
    )
    
    # Rebuild CSV
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerow({name: current_row.get(name, "") for name in headers})
    csv_text = output.getvalue()
    
    # Rebuild package
    zip_path = rebuild_session_package(session_dir, csv_text, state)
    length_audit = build_length_audit(current_row, specs)
    
    # Add answer acknowledgment to chat
    updated_chat = draft.get("chat", [])
    answer_summary = "Danke für die Details! Ich habe den Entwurf aktualisiert mit deinen Antworten. ✅"
    updated_chat.append({"role": "assistant", "content": answer_summary})
    
    return {
        **draft,
        "csv_text": csv_text,
        "row": current_row,
        "length_audit": length_audit,
        "chat": updated_chat,
        "zip_path": str(zip_path),
        "package_dir": str(session_dir / "draft" / "package"),
    }
