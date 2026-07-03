from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.v2.knowledge_base.step_01_models import InternalLinkRecord, WorkbookSnapshot


def canonical_path(url: str) -> str:
    parsed = urlsplit(url.strip())
    path = "/" + parsed.path.strip("/")
    if path != "/":
        path += "/"
    return path.lower()


@dataclass(frozen=True)
class EligibleLinks:
    candidates: tuple[InternalLinkRecord, ...]
    empty_reason: str | None = None


@dataclass(frozen=True)
class InternalLinkInjectionResult:
    shared_fields: dict[str, Any]
    acf_source_fields: dict[str, Any]
    injected: list[dict[str, str]]
    skipped: list[dict[str, str]]


class InternalLinkService:
    BODY_FIELD_PRIORITY = (
        "hero_intro",
        "event_story",
        "verlauf_text",
        "faq_1_answer",
        "faq_2_answer",
        "faq_3_answer",
        "faq_4_answer",
        "faq_5_answer",
        "cta_text",
    )
    SKIP_FIELD_KEYS = {
        "post_title",
        "slug",
        "excerpt",
        "status",
        "category",
        "tags",
        "focus_keyword",
        "seo_title",
        "meta_description",
        "social_title",
        "social_description",
        "hero_h1",
        "hero_h2",
        "event_story_h2",
        "verlauf_h2",
        "cta_h2",
    }

    def eligible(
        self,
        snapshot: WorkbookSnapshot,
        *,
        post_type_key: str,
        language: str,
        current_url: str | None,
    ) -> EligibleLinks:
        current_path = canonical_path(current_url) if current_url else None
        candidates: list[InternalLinkRecord] = []
        seen_urls: set[str] = set()
        for row in snapshot.internal_links:
            if not row.active or row.target_url == "TBD":
                continue
            if row.post_type_key not in {"*", post_type_key} or row.language != language:
                continue
            normalized_url = urlunsplit(urlsplit(row.target_url)._replace(fragment=""))
            if normalized_url in seen_urls:
                continue
            if current_path and canonical_path(row.target_url) == current_path:
                continue
            seen_urls.add(normalized_url)
            candidates.append(row)
        candidates.sort(key=lambda row: ({"high": 0, "medium": 1, "low": 2}.get(row.priority, 9), row.link_id))
        return EligibleLinks(
            candidates=tuple(candidates),
            empty_reason=None if candidates else "deterministic_filter_returned_zero_candidates",
        )

    def inject(
        self,
        eligible: EligibleLinks,
        selections: list[dict[str, str]],
        *,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
    ) -> InternalLinkInjectionResult:
        records = {row.link_id: row for row in eligible.candidates}
        updated_shared = dict(shared_fields)
        updated_acf = dict(acf_source_fields)
        injected: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        seen_anchors: set[str] = set()

        for selection in selections:
            link_id = selection.get("link_id", "")
            record = records.get(link_id)
            if record is None:
                raise ValueError(f"Unknown or ineligible internal-link candidate: {link_id}")
            anchor = self._valid_anchor(record, selection.get("anchor_text", ""))
            normalized_anchor = anchor.casefold()
            if record.target_url in seen_urls or normalized_anchor in seen_anchors:
                raise ValueError("Duplicate internal-link target or anchor.")
            seen_urls.add(record.target_url)
            seen_anchors.add(normalized_anchor)

            placed = self._inject_one(
                record,
                anchor,
                shared_fields=updated_shared,
                acf_source_fields=updated_acf,
            )
            if placed is None:
                continue
            field_group, field_key, next_value = placed
            if field_group == "shared":
                updated_shared[field_key] = next_value
            else:
                updated_acf[field_key] = next_value
            injected.append(
                {
                    "link_id": record.link_id,
                    "anchor_text": anchor,
                    "field_key": field_key,
                    "target_url": record.target_url,
                }
            )

        return InternalLinkInjectionResult(
            shared_fields=updated_shared,
            acf_source_fields=updated_acf,
            injected=injected,
            skipped=[],
        )

    def inject_placements(
        self,
        eligible: EligibleLinks,
        placements: list[dict[str, Any]],
        *,
        acf_source_fields: dict[str, Any],
        linkable_fields: dict[str, Any],
        minimum_words_between_links: int = 0,
    ) -> InternalLinkInjectionResult:
        records = {row.link_id: row for row in eligible.candidates}
        updated_acf = dict(acf_source_fields)
        injected: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        seen_anchors: set[str] = set()
        field_counts: dict[str, int] = {}

        for placement in placements:
            link_id = str(placement.get("link_id") or "")
            field_key = str(placement.get("field_key") or "")
            record = records.get(link_id)
            field_schema = linkable_fields.get(field_key)
            if record is None:
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "unknown_or_ineligible_link"})
                continue
            if field_schema is None:
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "field_not_linkable"})
                continue
            anchor = self._valid_anchor(record, str(placement.get("anchor_text") or ""))
            if record.target_url in seen_urls:
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "duplicate_target"})
                continue
            normalized_anchor = anchor.casefold()
            if normalized_anchor in seen_anchors:
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "duplicate_anchor"})
                continue
            max_links = getattr(field_schema, "max_internal_links", None)
            if max_links is not None and field_counts.get(field_key, 0) >= int(max_links):
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "field_link_budget_exceeded"})
                continue
            if placement.get("placement_mode") != "wrap_existing_text":
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "unsupported_placement_mode"})
                continue
            value = updated_acf.get(field_key)
            if not isinstance(value, str) or not value.strip():
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "empty_field"})
                continue
            match_text = str(placement.get("match_text") or "").strip() or anchor
            next_value = self._link_exact_match(
                value,
                record,
                anchor,
                match_text,
                minimum_words_between_links=minimum_words_between_links,
            )
            if next_value == value:
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "match_not_found_or_not_safe"})
                continue

            updated_acf[field_key] = next_value
            seen_urls.add(record.target_url)
            seen_anchors.add(normalized_anchor)
            field_counts[field_key] = field_counts.get(field_key, 0) + 1
            injected.append(
                {
                    "link_id": record.link_id,
                    "anchor_text": anchor,
                    "field_key": field_key,
                    "target_url": record.target_url,
                }
            )

        return InternalLinkInjectionResult(
            shared_fields={},
            acf_source_fields=updated_acf,
            injected=injected,
            skipped=skipped,
        )

    def _inject_one(
        self,
        record: InternalLinkRecord,
        anchor: str,
        *,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
    ) -> tuple[str, str, str] | None:
        for field_group, field_key, value in self._content_fields(shared_fields, acf_source_fields):
            if not isinstance(value, str) or not value.strip():
                continue
            next_value = self._link_first_match(value, record, anchor)
            if next_value != value:
                return field_group, field_key, next_value
        return None

    @classmethod
    def _content_fields(
        cls,
        shared_fields: dict[str, Any],
        acf_source_fields: dict[str, Any],
    ) -> list[tuple[str, str, Any]]:
        fields: list[tuple[str, str, Any]] = []
        for key in cls.BODY_FIELD_PRIORITY:
            if key in shared_fields and key not in cls.SKIP_FIELD_KEYS:
                fields.append(("shared", key, shared_fields[key]))
            if key in acf_source_fields and key not in cls.SKIP_FIELD_KEYS:
                fields.append(("acf", key, acf_source_fields[key]))
        for key, value in shared_fields.items():
            if key not in cls.SKIP_FIELD_KEYS and key not in cls.BODY_FIELD_PRIORITY:
                fields.append(("shared", key, value))
        for key, value in acf_source_fields.items():
            if (
                key not in cls.SKIP_FIELD_KEYS
                and key not in cls.BODY_FIELD_PRIORITY
                and not key.endswith("_h1")
                and not key.endswith("_h2")
                and not key.endswith("_question")
            ):
                fields.append(("acf", key, value))
        return fields

    def _link_first_match(
        self,
        value: str,
        record: InternalLinkRecord,
        selected_anchor: str,
    ) -> str:
        anchors = self._anchor_candidates(record, selected_anchor)
        protected_ranges = self._protected_ranges(value)
        for anchor in anchors:
            pattern = self._anchor_pattern(anchor)
            for match in pattern.finditer(value):
                if self._range_overlaps(match.start(), match.end(), protected_ranges):
                    continue
                href = html.escape(record.target_url, quote=True)
                linked = f'<a href="{href}">{html.escape(match.group(0))}</a>'
                return value[:match.start()] + linked + value[match.end():]
        return value

    def _link_exact_match(
        self,
        value: str,
        record: InternalLinkRecord,
        selected_anchor: str,
        match_text: str,
        *,
        minimum_words_between_links: int = 0,
    ) -> str:
        if not match_text:
            return value
        protected_ranges = self._protected_ranges(value)
        existing_link_ranges = self._existing_link_ranges(value)
        pattern = self._anchor_pattern(match_text)
        matches = [
            match
            for match in pattern.finditer(value)
            if not self._range_overlaps(match.start(), match.end(), protected_ranges)
        ]
        if len(matches) != 1:
            return value
        match = matches[0]
        if minimum_words_between_links and not self._has_minimum_word_distance(
            value,
            match.start(),
            match.end(),
            existing_link_ranges,
            minimum_words_between_links,
        ):
            return value
        href = html.escape(record.target_url, quote=True)
        linked = f'<a href="{href}">{html.escape(match.group(0))}</a>'
        return value[:match.start()] + linked + value[match.end():]

    @staticmethod
    def _anchor_candidates(record: InternalLinkRecord, selected_anchor: str) -> list[str]:
        candidates = [
            selected_anchor,
            record.anchor_text,
            *record.anchor_variants,
            record.keyword,
        ]
        seen: set[str] = set()
        unique: list[str] = []
        for candidate in candidates:
            normalized = str(candidate or "").strip()
            if not normalized or normalized.casefold() in seen:
                continue
            seen.add(normalized.casefold())
            unique.append(normalized)
        return unique

    @staticmethod
    def _valid_anchor(record: InternalLinkRecord, anchor_text: str) -> str:
        anchor = str(anchor_text or "").strip() or record.anchor_text
        if anchor not in {record.anchor_text, *record.anchor_variants}:
            return record.anchor_text
        return anchor

    @staticmethod
    def _anchor_pattern(anchor: str) -> re.Pattern[str]:
        return re.compile(rf"(?<!\w){re.escape(anchor)}(?!\w)", re.IGNORECASE)

    @staticmethod
    def _protected_ranges(value: str) -> list[tuple[int, int]]:
        ranges = [
            (match.start(), match.end())
            for match in re.finditer(r"<a\b[^>]*>.*?</a>", value, flags=re.IGNORECASE | re.DOTALL)
        ]
        ranges.extend(
            (match.start(), match.end())
            for match in re.finditer(r"<[^>]+>", value)
        )
        ranges.sort()
        return ranges

    @staticmethod
    def _range_overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
        return any(start < range_end and end > range_start for range_start, range_end in ranges)

    @staticmethod
    def _existing_link_ranges(value: str) -> list[tuple[int, int]]:
        return [
            (match.start(), match.end())
            for match in re.finditer(r"<a\b[^>]*>.*?</a>", value, flags=re.IGNORECASE | re.DOTALL)
        ]

    @staticmethod
    def _has_minimum_word_distance(
        value: str,
        start: int,
        end: int,
        link_ranges: list[tuple[int, int]],
        minimum_words: int,
    ) -> bool:
        plain_before = re.sub(r"<[^>]+>", " ", value[:start])
        plain_after = re.sub(r"<[^>]+>", " ", value[end:])
        for link_start, link_end in link_ranges:
            if link_end <= start:
                words = len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", value[link_end:start])))
            elif link_start >= end:
                words = len(re.findall(r"\w+", re.sub(r"<[^>]+>", " ", value[end:link_start])))
            else:
                return False
            if words < minimum_words:
                return False
        return bool(plain_before or plain_after or not link_ranges)
