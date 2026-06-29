from __future__ import annotations

import html
from collections.abc import Callable

from app.v2.errors import UnknownTransformError

Transform = Callable[[str, str], str]


def fact_list_item_html(label: str, value: str) -> str:
    return f"<li><strong>{html.escape(label)}:</strong> {html.escape(value)}</li>"


def concatenate_paragraphs(_label: str, value: str) -> str:
    paragraphs = [part.strip() for part in value.split("\n\n") if part.strip()]
    return "".join(f"<p>{html.escape(part)}</p>" for part in paragraphs)


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
