"""Deterministic SEO check of a draft, driven by the client's workbook.

Yoast and WordPress fields are found through their destination keys (standard names,
not client names). Which ACF fields are the heading, introduction or body, and which
length limits apply, come from `seo_rules` rows with action_type `check_role` or
`check_length`. Nothing here uses a model, so the check is instant and free.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from backend.app.internal_links.step_02_editor import link_urls
from backend.app.keywords.step_01_models import normalize_phrase
from backend.app.models.step_01_session import ContentSession

Status = Literal["pass", "fail", "skipped"]
Severity = Literal["high", "medium", "low"]

ROLES = ("heading", "introduction", "body")
DENSITY_RANGE = (0.5, 3.0)  # percent of words, as Yoast recommends
MIN_WORDS_FOR_DENSITY = 100

FOCUS = ("yoast", "yoast_wpseo_focuskw")
SEO_TITLE = ("yoast", "yoast_wpseo_title")
META_DESCRIPTION = ("yoast", "yoast_wpseo_metadesc")
POST_TITLE = ("wordpress", "title")
SLUG = ("wordpress", "slug")


@dataclass
class SeoFinding:
    check_id: str
    label: str
    status: Status
    severity: Severity
    message: str
    field_ids: list[str] = field(default_factory=list)


def plain_text(value: Any) -> str:
    """Visible text: drops HTML tags, shortcodes and template markers like {{ }}."""
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\[/?[A-Za-z_][^\]]*\]", " ", text)  # shortcodes
    text = text.replace("{{", "").replace("}}", "")
    text = re.sub(r"&nbsp;|&amp;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold())


def _same_word(left: str, right: str) -> bool:
    if left == right:
        return True
    short, long = sorted((left, right), key=len)
    return len(short) >= 4 and long.startswith(short) and len(long) - len(short) <= 3


def occurrences(text: str, phrase: str) -> int:
    """How often the phrase appears: word by word (small endings allowed) or, for long
    phrases, as a compound ("Kaffee-Catering" = "Kaffeecatering")."""
    words, target = _tokens(text), _tokens(phrase)
    if not target:
        return 0
    count = sum(
        1
        for start in range(len(words) - len(target) + 1)
        if all(_same_word(words[start + i], target[i]) for i in range(len(target)))
    )
    if count == 0 and len(normalize_phrase(phrase)) >= 8 and normalize_phrase(phrase) in normalize_phrase(text):
        return 1
    return count


def _slug_fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").casefold().replace("ß", "ss"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"ae|oe|ue", lambda m: m.group(0)[0], text)  # ä/ö/ü written as ae/oe/ue
    return re.sub(r"[\W_]+", "", text)


def _slug_covers(slug: str, phrase: str) -> bool:
    """Every longer word of the phrase is in the slug (short function words may be dropped)."""
    folded = _slug_fold(slug)
    needed = [w for w in _tokens(phrase) if len(w) >= 4]
    return bool(needed) and all(_slug_fold(w) in folded for w in needed)


class SeoChecker:
    def check(
        self,
        session: ContentSession,
        snapshot: Any,
        *,
        current_url: str | None = None,
    ) -> list[SeoFinding]:
        fields = {**session.shared_fields, **session.acf_source_fields}
        acf_keys = {row.field_key for row in snapshot.acf_fields if row.post_type_key == session.post_type_key}

        def field_id(key: str) -> str:
            return f"{'acf' if key in acf_keys else 'shared'}:{key}"

        by_destination = {
            (row.destination_type, row.destination_key): row.field_key
            for row in snapshot.shared_fields
            if row.enabled
        }

        def standard(destination: tuple[str, str]) -> tuple[str | None, str]:
            key = by_destination.get(destination)
            return key, plain_text(fields.get(key)) if key else ""

        rules = [
            row for row in snapshot.seo_rules
            if row.enabled and row.post_type_key in {"*", session.post_type_key} and row.target_type == "field"
        ]
        roles = {role: [r.target_key for r in rules if r.action_type == "check_role" and str(r.value).strip() == role
                        and r.target_key in fields] for role in ROLES}
        limits = {}
        for rule in rules:
            if rule.action_type == "check_length" and rule.target_key in fields:
                low, _, high = str(rule.value).partition(";")
                if low.strip().isdigit() and high.strip().isdigit():
                    limits[rule.target_key] = (int(low), int(high))

        focus_key, focus = standard(FOCUS)
        published = bool(session.wordpress_result.get("post_id"))
        findings: list[SeoFinding] = []

        def add(check_id, label, ok, severity, message, ids=(), skipped=False):
            findings.append(SeoFinding(
                check_id, label, "skipped" if skipped else "pass" if ok else "fail", severity, message, list(ids),
            ))

        add("focus_keyphrase", "Focus keyphrase set", bool(focus), "high",
            "A focus keyphrase is set." if focus else "No focus keyphrase is set. Select keywords on the Keywords screen or revise the focus keyword field.",
            [field_id(focus_key)] if focus_key else [])
        if not focus:
            return findings

        # Is this phrase already another page's focus keyphrase?
        own_path = urlparse(current_url or str(session.wordpress_result.get("view_url") or "")).path.rstrip("/")
        taken = [
            url for phrase, urls in session.site_focus_keyphrases.items()
            if normalize_phrase(phrase) == normalize_phrase(focus)
            for url in urls if urlparse(url).path.rstrip("/") != own_path
        ]
        add("focus_unique", "Focus keyphrase not used elsewhere", not taken, "high",
            "No other scanned page uses this focus keyphrase." if not taken
            else f"{len(taken)} other page(s) already use this focus keyphrase (for example {taken[0]}). Choose another keyword or an alternative.",
            [field_id(focus_key)], skipped=not session.site_focus_keyphrases)

        alternatives = [a for row in (session.keyword_proposal or {}).get("rows") or []
                        if normalize_phrase(row["keyword"]) == normalize_phrase(focus) for a in row.get("alternatives") or []]

        for label, destination, check_id, severity in (
            ("Focus keyphrase in post title", POST_TITLE, "in_post_title", "high"),
            ("Focus keyphrase in SEO title", SEO_TITLE, "in_seo_title", "high"),
            ("Focus keyphrase in meta description", META_DESCRIPTION, "in_meta_description", "medium"),
        ):
            key, text = standard(destination)
            ok = bool(text) and occurrences(text, focus) > 0
            add(check_id, label, ok, severity,
                f"The focus keyphrase appears in the {label.split(' in ')[1]}." if ok
                else f"The focus keyphrase is missing in the {label.split(' in ')[1]}.",
                [field_id(key)] if key else [], skipped=key is None or not text)

        key, slug = standard(SLUG)
        in_slug = _slug_covers(slug, focus)
        add("in_slug", "Focus keyphrase in slug", in_slug, "medium",
            "The slug contains the focus keyphrase." if in_slug else
            "The slug does not contain the focus keyphrase." + (" A published URL is kept to avoid breaking links." if published else ""),
            [] if published or not key else [field_id(key)], skipped=key is None or not slug)

        seo_key, seo_title = standard(SEO_TITLE)
        position = normalize_phrase(seo_title).find(normalize_phrase(focus)) if seo_title else -1
        early = 0 <= position <= max(10, len(normalize_phrase(seo_title)) // 3)
        add("seo_title_start", "Focus keyphrase near the start of the SEO title", early, "low",
            "The SEO title starts with the focus keyphrase." if early else "Place the focus keyphrase near the start of the SEO title.",
            [field_id(seo_key)] if seo_key else [], skipped=position < 0 or not seo_key)

        for key in roles["introduction"]:
            sentences = re.split(r"(?<=[.!?])\s+", plain_text(fields[key]))
            ok = occurrences(" ".join(sentences[:2]), focus) > 0
            add(f"in_introduction:{key}", "Focus keyphrase in the introduction", ok, "high",
                "The introduction names the focus keyphrase in its first sentences." if ok
                else "Use the focus keyphrase in the first one or two sentences of the introduction.", [field_id(key)])
        for key in roles["heading"]:
            text = plain_text(fields[key])
            ok = any(occurrences(text, phrase) for phrase in (focus, *alternatives))
            add(f"in_heading:{key}", "Focus keyphrase (or a variant) in the main heading", ok, "medium",
                "The main heading contains the focus keyphrase or a variant." if ok
                else "Work the focus keyphrase or one of its alternatives into the main heading.", [field_id(key)])

        for key, (low, high) in limits.items():
            length = len(plain_text(fields[key]))
            add(f"length:{key}", f"Length of {key}", low <= length <= high, "medium",
                f"{length} characters, within {low}-{high}." if low <= length <= high
                else f"{length} characters; the target is {low}-{high}.", [field_id(key)])

        text_keys = [k for role in ROLES for k in roles[role]]
        body = " ".join(plain_text(fields[k]) for k in text_keys)
        words = len(_tokens(body))
        if text_keys and words >= MIN_WORDS_FOR_DENSITY:
            density = 100 * occurrences(body, focus) * len(_tokens(focus)) / words
            low, high = DENSITY_RANGE
            ok = low <= density <= high
            add("density", "Focus keyphrase density", ok, "low",
                f"The focus keyphrase makes up {density:.1f}% of the text (target {low}-{high}%).",
                [field_id(k) for k in text_keys], skipped=False)

        others = [k for k in session.selected_keywords if normalize_phrase(k) != normalize_phrase(focus)]
        if others:
            everything = " ".join(plain_text(v) for v in fields.values() if isinstance(v, str))
            missing = [k for k in others if occurrences(everything, k) == 0]
            add("other_keywords", "Other selected keywords used", not missing, "medium",
                "Every other selected keyword appears in the text." if not missing
                else "These selected keywords do not appear yet: " + ", ".join(missing) + ".",
                [field_id(k) for k in (roles["introduction"] + roles["body"])[:1]])

        if session.selected_links:
            placed = link_urls([v for v in fields.values() if isinstance(v, str)])
            add("internal_links", "Internal links placed", bool(placed), "low",
                f"{len(placed)} internal link(s) are placed." if placed else "Candidates are selected, but no internal link is placed yet.",
                [])
        return findings

    @staticmethod
    def revision_instruction(session: ContentSession, findings: list[SeoFinding]) -> str:
        failed = [f for f in findings if f.status == "fail" and f.field_ids]
        if not failed:
            return ""
        return (
            "Improve the selected fields so these SEO checks pass. Keep confirmed facts, HTML structure, links and the "
            "meaning. Write naturally; do not stuff keywords.\n"
            + "\n".join(f"- {f.label}: {f.message}" for f in failed)
        )
