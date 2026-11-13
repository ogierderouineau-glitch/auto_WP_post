"""Live SEO data sources: a WordPress site scan and Google Search Console.

Both are built per client with that client's own credentials. Nothing is cached.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, urlparse

import requests

FOCUS_KEY = "_yoast_wpseo_focuskw"
SYNONYMS_KEY = "_yoast_wpseo_keywordsynonyms"
DESCRIPTION_KEY = "_yoast_wpseo_metadesc"
SCAN_FIELDS = "id,type,slug,title,link,meta"
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


@dataclass(frozen=True)
class SiteEntry:
    wp_id: int
    post_type: str
    slug: str
    title: str
    url: str
    focus_keyphrase: str = ""
    synonyms: str = ""
    meta_description: str = ""

    @property
    def source(self) -> str:
        """`yoast` when a real focus keyphrase was read, else the slug/title fallback."""
        return "yoast" if self.focus_keyphrase else "slug_title"


@dataclass(frozen=True)
class QueryStat:
    query: str
    month: str  # "YYYY-MM"
    clicks: int
    impressions: int
    clicks_delta: int | None  # versus the previous month; None without that month


def _text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("raw") or value.get("rendered")
    return str(value or "").strip()


def _synonyms(value: Any) -> str:
    """Yoast Premium stores synonyms as a JSON list string such as ["a",""]."""
    text = _text(value)
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    return ", ".join(str(item).strip() for item in parsed if str(item).strip()) if isinstance(parsed, list) else text


def _entry(record: dict[str, Any], post_type: str = "") -> SiteEntry:
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    return SiteEntry(
        wp_id=int(record.get("id") or 0),
        post_type=str(record.get("type") or post_type),
        slug=str(record.get("slug") or ""),
        title=_text(record.get("title")),
        url=str(record.get("link") or ""),
        focus_keyphrase=_text(meta.get(FOCUS_KEY)),
        synonyms=_synonyms(meta.get(SYNONYMS_KEY)),
        meta_description=_text(meta.get(DESCRIPTION_KEY)),
    )


class WordPressSiteScanner:
    """Read-only REST scan using one client's own WordPress credentials."""

    def __init__(
        self,
        base_url: str,
        username: str,
        app_password: str,
        *,
        session: Any | None = None,
        timeout: int = 30,
    ) -> None:
        if not (base_url and username and app_password):
            raise ValueError("WordPress base URL and credentials are required for a site scan.")
        token = base64.b64encode(f"{username}:{app_password}".encode()).decode("ascii")
        self._base = base_url.rstrip("/") + "/wp-json/wp/v2"
        self._headers = {"Authorization": f"Basic {token}"}
        self._session = session or requests.Session()
        self._timeout = timeout
        self._types: dict[str, Any] | None = None  # per scanner, so per run

    def _get_types(self) -> dict[str, Any]:
        if self._types is None:
            self._types = self._get("/types", {"context": "edit"}).json()
        return self._types

    def _get(self, path: str, params: dict[str, Any]) -> requests.Response:
        response = self._session.get(
            self._base + path, params=params, headers=self._headers, timeout=self._timeout
        )
        if response.status_code > 400:  # 400 is handled by callers (past the last page)
            raise RuntimeError(f"WordPress scan failed (GET {path}, HTTP {response.status_code}).")
        return response

    def rest_base_for(self, wp_post_type: str) -> str:
        """The REST collection name WordPress reports for a post type (for example
        `page` is served at `pages`)."""
        for type_info in self._get_types().values():
            if type_info.get("slug") == wp_post_type and type_info.get("rest_base"):
                return str(type_info["rest_base"])
        return wp_post_type

    def category_ids(self, *names: str) -> list[int]:
        """IDs of categories whose name equals any given name (case-insensitive)."""
        wanted = {name.strip().lower() for name in names if name.strip()}
        found: list[int] = []
        for name in sorted(wanted):
            for item in self._get("/categories", {"search": name, "per_page": 100}).json():
                if str(item.get("name") or "").strip().lower() in wanted and int(item["id"]) not in found:
                    found.append(int(item["id"]))
        return found

    def scan_collection(
        self, wp_post_type: str, category_ids: list[int] | None = None
    ) -> list[SiteEntry]:
        """All published entries of one post type (optionally limited to categories), following
        REST pagination."""
        entries: list[SiteEntry] = []
        rest_base = self.rest_base_for(wp_post_type)
        extra = {"categories": ",".join(map(str, category_ids))} if category_ids else {}
        page = 1
        while True:
            response = self._get(
                f"/{rest_base}",
                {
                    **extra,
                    "per_page": 100,
                    "page": page,
                    "status": "publish",
                    "context": "edit",
                    "_fields": SCAN_FIELDS,
                },
            )
            if response.status_code == 400:  # WordPress answers 400 past the last page
                break
            entries.extend(_entry(item, wp_post_type) for item in response.json())
            if page >= int(response.headers.get("X-WP-TotalPages", 1)):
                break
            page += 1
        return entries

    def find_by_urls(self, urls: list[str]) -> dict[str, SiteEntry | None]:
        """Resolve URLs by slug with one request per viewable REST type. Matching is on
        the URL path, since staging and live domains mirror each other."""
        slugs = {url: urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] for url in urls}
        wanted = sorted({slug for slug in slugs.values() if slug})
        found: dict[str, SiteEntry] = {}
        for type_info in self._get_types().values() if wanted else ():
            if type_info.get("viewable") is False or not type_info.get("rest_base"):
                continue
            response = self._get(
                f"/{type_info['rest_base']}",
                {"slug": ",".join(wanted), "per_page": 100, "status": "publish",
                 "context": "edit", "_fields": SCAN_FIELDS},
            )
            if response.status_code == 400:
                continue
            for item in response.json():
                found.setdefault(
                    urlparse(str(item.get("link") or "")).path.rstrip("/"),
                    _entry(item, str(type_info.get("slug") or "")),
                )
        return {url: found.get(urlparse(url).path.rstrip("/")) for url in urls}

    def find_by_url(self, url: str) -> SiteEntry | None:
        return self.find_by_urls([url])[url]


def _month_start(day: date, months_back: int) -> date:
    index = day.year * 12 + day.month - 1 - months_back
    return date(index // 12, index % 12 + 1, 1)


class SearchConsoleProvider:
    """Monthly query clicks for one client's property (read-only service account)."""

    def __init__(
        self,
        property_url: str,
        credentials_file: str,
        *,
        session: Any | None = None,
        timeout: int = 30,
    ) -> None:
        if not (property_url and credentials_file):
            raise ValueError("Search Console property and credentials file are required.")
        self._endpoint = (
            "https://www.googleapis.com/webmasters/v3/sites/"
            f"{quote(property_url, safe='')}/searchAnalytics/query"
        )
        self._timeout = timeout
        if session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(
                credentials_file, scopes=[SEARCH_CONSOLE_SCOPE]
            )
            session = AuthorizedSession(credentials)
        self._session = session

    def _month_rows(self, first: date, last: date, row_limit: int) -> dict[str, tuple[int, int]]:
        response = self._session.post(
            self._endpoint,
            json={
                "startDate": first.isoformat(),
                "endDate": last.isoformat(),
                "dimensions": ["query"],
                "rowLimit": row_limit,
            },
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Search Console request failed (HTTP {response.status_code}).")
        return {
            row["keys"][0]: (int(row.get("clicks", 0)), int(row.get("impressions", 0)))
            for row in response.json().get("rows", [])
        }

    def monthly_queries(
        self, *, months: int = 3, row_limit: int = 500, today: date | None = None
    ) -> list[QueryStat]:
        """The last `months` complete months, oldest first, each with its change versus
        the month before (None for the oldest fetched month)."""
        today = today or date.today()
        stats: list[QueryStat] = []
        previous: dict[str, tuple[int, int]] | None = None
        for back in range(months, 0, -1):
            first = _month_start(today, back)
            last = _month_start(today, back - 1) - timedelta(days=1)
            rows = self._month_rows(first, last, row_limit)
            label = first.strftime("%Y-%m")
            stats.extend(
                QueryStat(
                    query=query,
                    month=label,
                    clicks=clicks,
                    impressions=impressions,
                    clicks_delta=None if previous is None else clicks - previous.get(query, (0, 0))[0],
                )
                for query, (clicks, impressions) in rows.items()
            )
            previous = rows
        return stats
