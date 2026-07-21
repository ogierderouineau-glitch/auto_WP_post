from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from app.v2.errors import UnknownTransformError

Transform = Callable[[str, str], str]


def build_gallery_html(gallery_media: list[dict[str, object]]) -> str:
    """Build the gallery markup after WordPress has assigned media URLs."""
    if not gallery_media:
        return ""

    slides: list[str] = []
    for item in gallery_media:
        alt = html.escape(str(item.get("image_alt") or item.get("alt_text") or ""), quote=True)
        title = html.escape(str(item.get("image_title") or item.get("title") or ""), quote=True)
        src = html.escape(str(item.get("source_url") or ""), quote=True)
        title_attr = f' title="{title}"' if title else ""
        slides.append(
            '<div class="swiper-slide" role="group">'
            '<figure class="swiper-slide-inner">'
            f'<img class="swiper-slide-image" src="{src}" alt="{alt}"{title_attr} loading="lazy" decoding="async">'
            '</figure>'
            '</div>'
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
