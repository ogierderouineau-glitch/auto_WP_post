from __future__ import annotations

import html
from dataclasses import dataclass
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


class InternalLinkService:
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

    def render(
        self,
        eligible: EligibleLinks,
        selections: list[dict[str, str]],
        *,
        minimum_links: int = 0,
        maximum_links: int | None = None,
    ) -> str:
        records = {row.link_id: row for row in eligible.candidates}
        seen_urls: set[str] = set()
        seen_anchors: set[str] = set()
        links: list[str] = []
        for selection in selections:
            link_id = selection.get("link_id", "")
            anchor = selection.get("anchor_text", "").strip()
            record = records.get(link_id)
            if record is None:
                raise ValueError(f"Unknown or ineligible internal-link candidate: {link_id}")
            normalized_anchor = anchor.casefold()
            if record.target_url in seen_urls or normalized_anchor in seen_anchors:
                raise ValueError("Duplicate internal-link target or anchor.")
            allowed_anchors = {record.anchor_text, *record.anchor_variants}
            if anchor not in allowed_anchors:
                raise ValueError(f"Anchor is not registered for {link_id}.")
            seen_urls.add(record.target_url)
            seen_anchors.add(normalized_anchor)
            links.append(
                f'<a href="{html.escape(record.target_url, quote=True)}">'
                f"{html.escape(anchor)}</a>"
            )
        if not links:
            if eligible.empty_reason:
                return ""
            if minimum_links:
                raise ValueError("Eligible internal links exist but none were selected.")
            return ""
        required_minimum = min(minimum_links, len(eligible.candidates))
        if len(links) < required_minimum:
            raise ValueError(
                f"At least {required_minimum} eligible internal links are required."
            )
        if maximum_links is not None and len(links) > maximum_links:
            raise ValueError(f"At most {maximum_links} internal links are allowed.")
        return '<div class="post-tags"><span class="tag-links">Mehr entdecken: ' + ", ".join(links) + "</span></div>"
