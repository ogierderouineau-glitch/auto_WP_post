from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from backend.app.errors import UnknownTransformError

Transform = Callable[[str, str], str]


def fact_list_item_html(label: str, value: str) -> str:
    return f"<li><strong>{html.escape(label)}:</strong> {html.escape(value)}</li>"


def concatenate_paragraphs(_label: str, value: str) -> str:
    paragraphs = [part.strip() for part in value.split("\n\n") if part.strip()]
    return "".join(f"<p>{_escape_with_safe_links(part)}</p>" for part in paragraphs)


_ANCHOR_TAG = re.compile(
    r'<a\s+href=(?P<quote>["\'])(?P<href>https?://[^"\']+)(?P=quote)\s*>(?P<text>[^<>]*)</a>',
    re.IGNORECASE,
)


def _escape_with_safe_links(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _ANCHOR_TAG.finditer(value):
        parts.append(html.escape(value[cursor:match.start()]))
        href = match.group("href")
        parsed = urlsplit(href)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            parts.append(
                f'<a href="{html.escape(href, quote=True)}">'
                f'{html.escape(match.group("text"))}</a>'
            )
        else:
            parts.append(html.escape(match.group(0)))
        cursor = match.end()
    parts.append(html.escape(value[cursor:]))
    return "".join(parts)


TRANSFORMS: dict[str, Transform] = {
    "fact_list_item_html": fact_list_item_html,
    "concatenate_paragraphs": concatenate_paragraphs,
    "paragraphs_html": concatenate_paragraphs,
}


def apply_transform(transform_key: str, label: str, value: str) -> str:
    try:
        transform = TRANSFORMS[transform_key]
    except KeyError as exc:
        raise UnknownTransformError(f"Unknown aggregation transform: {transform_key}") from exc
    return transform(label, value)
