"""Set external-link targets without rewriting surrounding HTML or field values."""
from html import escape, unescape
import re
from typing import Any
from urllib.parse import urlsplit

from backend.app.internal_links.step_02_editor import LinkMarkup

_ATTRIBUTE = re.compile(r'''([^\s/>=]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?''')


def _hostname(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
        return host.rstrip(".").lower().removeprefix("www.").encode("idna").decode("ascii")
    except ValueError:
        return ""


def _external_tag(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    rel = list(dict.fromkeys(token for name, value in attrs if name == "rel"
                            for token in (value or "").split() if token.lower() != "opener"))
    if not any(token.lower() == "noopener" for token in rel):
        rel.append("noopener")
    desired = {"target": "_blank", "rel": " ".join(rel)}
    edits = []
    seen = set()
    for match in _ATTRIBUTE.finditer(tag, 2):
        name = match.group(1).lower()
        if name not in desired:
            continue
        seen.add(name)
        parts = re.split(r"\s*=\s*", match.group(0), maxsplit=1)
        current = unescape(parts[1].strip("\"'")) if len(parts) == 2 else ""
        if current != desired[name]:
            edits.append((match.start(), match.end(), f'{name}="{escape(desired[name], quote=True)}"'))
    suffix = "".join(f' {name}="{escape(value, quote=True)}"' for name, value in desired.items() if name not in seen)
    position = len(tag) - (2 if tag.endswith("/>") else 1)
    edits.append((position, position, suffix))
    for start, end, replacement in sorted(edits, reverse=True):
        tag = tag[:start] + replacement + tag[end:]
    return tag


class ExternalLinkTargets:
    def __init__(self, wordpress_site_url: str = "") -> None:
        self.site_host = _hostname(wordpress_site_url)

    def apply(self, value: Any) -> Any:
        if not self.site_host:
            return value
        if isinstance(value, dict):
            return {key: self.apply(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.apply(item) for item in value]
        if not isinstance(value, str) or "<a" not in value.lower():
            return value
        edits = []
        for tag, attrs, start in LinkMarkup(value).anchor_tags:
            href = next((url for name, url in attrs if name == "href"), "") or ""
            try:
                parsed = urlsplit(href)
            except ValueError:
                continue
            host = _hostname(href)
            if parsed.scheme.lower() not in {"", "http", "https"} or not host or host == self.site_host:
                continue
            edits.append((start, start + len(tag), _external_tag(tag, attrs)))
        for start, end, replacement in reversed(edits):
            value = value[:start] + replacement + value[end:]
        return value
