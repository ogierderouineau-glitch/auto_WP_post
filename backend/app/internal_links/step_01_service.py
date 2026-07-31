from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from backend.app.knowledge_base.step_01_models import InternalLinkRecord, WorkbookSnapshot


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
    SEARCH_STOP_TERMS = {
        "aber", "auch", "das", "der", "die", "ein", "eine", "einer", "eines",
        "für", "ist", "mit", "oder", "und", "von", "wenn", "wird", "zum", "zur",
        "event", "events",
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

    def rank(
        self,
        eligible: EligibleLinks,
        *,
        source_text: str,
        context_tags: tuple[str, ...] = (),
        content_signals: tuple[str, ...] = (),
        maximum: int | None = None,
    ) -> list[dict[str, str]]:
        """Rank curated candidates without an extra language-model request."""

        haystack = self._search_terms(
            " ".join((source_text, *context_tags, *content_signals))
        )
        priority_score = {"high": 3, "medium": 2, "low": 1}
        scored: list[tuple[int, int, str, InternalLinkRecord]] = []
        for row in eligible.candidates:
            keyword_terms = self._search_terms(
                " ".join(
                    (
                        row.keyword,
                        row.category,
                        row.usage_context,
                        row.city or "",
                        row.anchor_text,
                        *row.anchor_variants,
                    )
                )
            )
            overlap = len(haystack.intersection(keyword_terms))
            phrase_bonus = sum(
                4
                for phrase in (
                    row.keyword,
                    row.anchor_text,
                    *row.anchor_variants,
                    row.category,
                    row.city or "",
                )
                if phrase and phrase.casefold() in source_text.casefold()
            )
            score = overlap * 2 + phrase_bonus
            scored.append((score, priority_score.get(row.priority, 0), row.link_id, row))
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        limit = maximum if maximum is not None else len(scored)
        return [
            {"link_id": row.link_id, "anchor_text": row.anchor_text}
            for score, _, _, row in scored[:limit]
            if score >= 2
        ]

    @staticmethod
    def _search_terms(value: str) -> set[str]:
        return {
            term
            for term in re.findall(r"[\wäöüß-]+", value.casefold())
            if len(term) >= 3 and term not in InternalLinkService.SEARCH_STOP_TERMS
        }

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
        seen_urls = self._existing_link_urls(updated_acf.values())
        seen_anchors = self._existing_link_anchors(updated_acf.values())
        field_counts = {
            field_key: self._existing_link_count(updated_acf.get(field_key))
            for field_key in linkable_fields
        }

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
            value = updated_acf.get(field_key)
            if not isinstance(value, str) or not value.strip():
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "empty_field"})
                continue
            match_text = str(placement.get("match_text") or "").strip() or anchor
            placement_mode = str(placement.get("placement_mode") or "wrap_existing_text")
            if placement_mode == "rewrite_single_sentence":
                replacement = str(placement.get("replacement_sentence") or "").strip()
                sentence_index = placement.get("sentence_index")
                allowed_anchors = {record.anchor_text.casefold(), *(item.casefold() for item in record.anchor_variants)}
                if match_text.casefold() not in allowed_anchors:
                    skipped.append({"link_id": link_id, "field_key": field_key, "reason": "rewrite_anchor_not_approved"})
                    continue
                rewritten = self._replace_sentence(value, sentence_index, replacement)
                if rewritten is None:
                    skipped.append({"link_id": link_id, "field_key": field_key, "reason": "invalid_sentence_rewrite"})
                    continue
                value = rewritten
            elif placement_mode != "wrap_existing_text":
                skipped.append({"link_id": link_id, "field_key": field_key, "reason": "unsupported_placement_mode"})
                continue
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

    def inject_existing_anchors(
        self,
        eligible: EligibleLinks,
        selections: list[dict[str, str]],
        *,
        acf_source_fields: dict[str, Any],
        linkable_fields: dict[str, Any],
        minimum_words_between_links: int = 0,
    ) -> InternalLinkInjectionResult:
        """Plan each exact-anchor link against content updated by earlier injections."""
        updated_acf = dict(acf_source_fields)
        injected: list[dict[str, str]] = []
        skipped: list[dict[str, str]] = []
        selected_anchors = [
            str(selection.get("anchor_text") or "").strip().casefold()
            for selection in selections
        ]
        ordered_selections = [
            selection
            for _, selection in sorted(
                enumerate(selections),
                key=lambda item: (
                    any(
                        selected_anchors[item[0]]
                        and selected_anchors[item[0]] != other
                        and selected_anchors[item[0]] in other
                        for other in selected_anchors
                    ),
                    item[0],
                ),
            )
        ]
        for selection in ordered_selections:
            placements = self.existing_anchor_placements(
                eligible,
                [selection],
                acf_source_fields=updated_acf,
                linkable_fields=linkable_fields,
            )
            result = self.inject_placements(
                eligible,
                placements,
                acf_source_fields=updated_acf,
                linkable_fields=linkable_fields,
                minimum_words_between_links=minimum_words_between_links,
            )
            updated_acf = result.acf_source_fields
            injected.extend(result.injected)
            skipped.extend(result.skipped)
        return InternalLinkInjectionResult(
            shared_fields={},
            acf_source_fields=updated_acf,
            injected=injected,
            skipped=skipped,
        )

    def existing_anchor_placements(
        self,
        eligible: EligibleLinks,
        selections: list[dict[str, str]],
        *,
        acf_source_fields: dict[str, Any],
        linkable_fields: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Plan safe exact matches locally, honoring an explicitly requested ACF destination."""
        records = {row.link_id: row for row in eligible.candidates}
        placements: list[dict[str, Any]] = []
        for selection in selections:
            link_id = str(selection.get("link_id") or "")
            record = records.get(link_id)
            if record is None:
                continue
            destination = str(selection.get("destination_acf") or "")
            selected_anchor = self._valid_anchor(record, str(selection.get("anchor_text") or ""))
            approved = {record.anchor_text.casefold(), *(item.casefold() for item in record.anchor_variants)}
            anchors = [
                anchor for anchor in self._anchor_candidates(record, selected_anchor)
                if anchor.casefold() in approved
            ]
            placed = False
            for field_key, field_schema in linkable_fields.items():
                field_destination = str(getattr(field_schema, "acf_field_name", None) or field_key)
                if destination and field_destination != destination:
                    continue
                value = acf_source_fields.get(field_key)
                if not isinstance(value, str) or not value.strip():
                    continue
                protected_ranges = self._protected_ranges(value)
                for anchor in anchors:
                    matches = [
                        match
                        for match in self._anchor_pattern(anchor).finditer(value)
                        if not self._range_overlaps(match.start(), match.end(), protected_ranges)
                    ]
                    if len(matches) != 1:
                        continue
                    placements.append({
                        "link_id": link_id,
                        "field_key": field_key,
                        "match_text": matches[0].group(0),
                        "anchor_text": selected_anchor,
                        "placement_mode": "wrap_existing_text",
                    })
                    placed = True
                    break
                if placed:
                    break
        return placements

    @staticmethod
    def _existing_link_urls(values: Any) -> set[str]:
        urls: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            urls.update(
                html.unescape(match.group(1))
                for match in re.finditer(
                    r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>",
                    value,
                    flags=re.IGNORECASE,
                )
            )
        return urls

    @staticmethod
    def _existing_link_anchors(values: Any) -> set[str]:
        anchors: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            anchors.update(
                html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip().casefold()
                for match in re.finditer(
                    r"<a\b[^>]*>(.*?)</a>",
                    value,
                    flags=re.IGNORECASE | re.DOTALL,
                )
            )
        anchors.discard("")
        return anchors

    @staticmethod
    def _existing_link_count(value: Any) -> int:
        if not isinstance(value, str):
            return 0
        return len(re.findall(r"<a\b[^>]*\bhref=[\"'][^\"']+[\"'][^>]*>", value, re.IGNORECASE))

    @staticmethod
    def _replace_sentence(value: str, sentence_index: Any, replacement: str) -> str | None:
        if not isinstance(sentence_index, int) or sentence_index < 0 or not replacement:
            return None
        if "<" in replacement or ">" in replacement or re.search(r"https?://|www\.", replacement, re.IGNORECASE):
            return None
        sentences = list(re.finditer(r"\S(?:.*?\S)?(?:[.!?]+(?=\s|$)|$)", value, re.DOTALL))
        if sentence_index >= len(sentences):
            return None
        selected = sentences[sentence_index]
        return value[:selected.start()] + replacement + value[selected.end():]

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
