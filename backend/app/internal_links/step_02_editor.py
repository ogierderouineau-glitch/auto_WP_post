"""Small HTML edits that preserve source formatting and never rewrite surrounding text."""
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit


class LinkMarkup(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = [0]
        self.line_offsets.extend(index + 1 for index, char in enumerate(source) if char == "\n")
        self.links: list[tuple[str, tuple[int, int], tuple[int, int]]] = []
        self.text_ranges: list[tuple[int, int]] = []
        self.anchors: list[tuple[str, tuple[int, int]]] = []
        self.anchor_tags: list[tuple[str, list[tuple[str, str | None]], int]] = []
        self.protected: list[str] = []
        self.feed(source)

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "code", "pre"}:
            self.protected.append(tag)
        if tag == "a":
            start = self.source_offset()
            self.anchor_tags.append((self.get_starttag_text(), attrs, start))
            self.anchors.append((dict(attrs).get("href") or "", (start, start + len(self.get_starttag_text()))))

    def handle_endtag(self, tag):
        if tag in self.protected:
            self.protected.remove(tag)
        if tag == "a" and self.anchors:
            url, opening = self.anchors.pop()
            start = self.source_offset()
            end = self.source.find(">", start)
            if end >= 0:
                self.links.append((url, opening, (start, end + 1)))

    def handle_data(self, data):
        if not self.anchors and not self.protected:
            start = self.source_offset()
            self.text_ranges.append((start, start + len(data)))


def link_urls(values) -> set[str]:
    return {url for value in values if isinstance(value, str) for url, _, _ in LinkMarkup(value).links}


def unlink_url(value: str, url: str) -> str:
    ranges = [span for href, opening, closing in LinkMarkup(value).links if href == url for span in (opening, closing)]
    for start, end in sorted(ranges, reverse=True):
        value = value[:start] + value[end:]
    return value


def insert_link(value: str, *, url: str, start: int, end: int, selected_text: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or any(char.isspace() or ord(char) < 32 for char in url):
        raise ValueError("Paste a complete HTTP(S) URL.")
    # Browser selection offsets count UTF-16 units rather than Python characters.
    try:
        encoded = value.encode("utf-16-le")
        if start < 0 or end > len(encoded) // 2:
            raise ValueError("The selected text is outside this field.")
        first = len(encoded[:start * 2].decode("utf-16-le"))
        last = len(encoded[:end * 2].decode("utf-16-le"))
    except UnicodeError as exc:
        raise ValueError("Select complete text characters.") from exc
    if start < 0 or end <= start or not selected_text.strip() or value[first:last] != selected_text:
        raise ValueError("The selected text changed. Select it again before adding a link.")
    if not any(left <= first < last <= right for left, right in LinkMarkup(value).text_ranges):
        raise ValueError("Select text within one paragraph, without HTML tags or existing links.")
    return value[:first] + f'<a href="{escape(url, quote=True)}">' + value[first:last] + "</a>" + value[last:]


def protect_links(value: str) -> tuple[str, dict[str, str]]:
    """Hide existing link markup from a model while leaving opaque, restorable slots."""
    from uuid import uuid4
    nonce = uuid4().hex
    replacements = {}
    for index, (_, opening, closing) in reversed(list(enumerate(LinkMarkup(value).links))):
        token = f"__S2P_LINK_{nonce}_{index}__"
        replacements[token] = value[opening[0]:closing[1]]
        value = value[:opening[0]] + token + value[closing[1]:]
    return value, replacements


def restore_links(value: str, replacements: dict[str, str]) -> str:
    """Restore exact HTML only when each link slot survives once in ordinary text."""
    # All original links were masked. Any links returned by the model are new:
    # keep their text, but let deterministic placement supply approved URLs.
    for url in link_urls([value]):
        value = unlink_url(value, url)
    markup = LinkMarkup(value)
    for token in replacements:
        start = value.find(token)
        if value.count(token) != 1 or not any(left <= start and start + len(token) <= right for left, right in markup.text_ranges):
            raise ValueError("The link revision could not preserve an existing link. Try a different destination field. Draft unchanged.")
    for token, html in replacements.items():
        value = value.replace(token, html)
    return value
