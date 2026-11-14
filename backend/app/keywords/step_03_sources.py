from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from backend.app.knowledge_base.step_01_models import InternalLinkRecord, PostTypeConfig
from backend.app.providers.step_04_seo_sources import (
    QueryStat,
    SearchConsoleProvider,
    SiteEntry,
    WordPressSiteScanner,
)

Progress = Callable[[str], None]


@dataclass
class SeoSnapshot:
    entries: list[SiteEntry] = field(default_factory=list)
    stats: list[QueryStat] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


class SeoSources:
    """Gathers live scan and Search Console data for one client. Nothing is cached.

    Providers come from factories so a missing credential only disables that source.
    """

    def __init__(
        self,
        *,
        scanner_factory: Callable[[], WordPressSiteScanner | None],
        search_console_factory: Callable[[], SearchConsoleProvider | None],
        service_category: str = "",
    ) -> None:
        self._scanner_factory = scanner_factory
        self._search_console_factory = search_console_factory
        self._service_category = service_category.strip().lower()

    def yoast_scores(self, wp_post_type: str, post_id: int) -> dict[str, Any] | None:
        scanner = self._scanner_factory()
        return scanner.yoast_scores(wp_post_type, post_id) if scanner else None

    def gather(
        self,
        *,
        post_type: PostTypeConfig,
        internal_links: Iterable[InternalLinkRecord],
        progress: Progress | None = None,
        with_search_console: bool = True,
    ) -> SeoSnapshot:
        say = progress or (lambda _stage: None)
        snapshot = SeoSnapshot()
        scanner = self._scanner_factory()
        if scanner is None:
            raise RuntimeError("WordPress credentials are not configured for this client.")

        say("Scanning WordPress")
        snapshot.sources.append("wordpress")
        names = [post_type.display_name_de, post_type.wp_category_name]
        category_ids = scanner.category_ids(*names)
        if category_ids or post_type.wp_post_type != "post":
            entries = scanner.scan_collection(post_type.wp_post_type, category_ids or None)
        else:  # posts are told apart by category; without a match nothing is comparable
            entries = []
            snapshot.notes.append(
                f"No WordPress category matches {', '.join(repr(n) for n in names if n)}."
            )
        seen = {(e.wp_id, e.post_type) for e in entries}
        snapshot.entries.extend(entries)

        if self._service_category:
            urls = [
                row.target_url
                for row in internal_links
                if row.category.strip().lower() == self._service_category
                and row.active
                and row.target_url.startswith("http")
            ]
            resolved = scanner.find_by_urls(urls)
            unresolved = sum(1 for url in urls if resolved.get(url) is None)
            for found in resolved.values():
                if found is not None and (found.wp_id, found.post_type) not in seen:
                    seen.add((found.wp_id, found.post_type))
                    snapshot.entries.append(found)
            if unresolved:
                snapshot.notes.append(f"{unresolved} service page URL(s) were not found on the site.")
        else:
            snapshot.notes.append("No service page category is configured for this client.")

        if not with_search_console:
            return snapshot
        say("Reading Search Console")
        provider = self._search_console_factory()
        if provider is None:
            snapshot.notes.append("Search Console is not configured; no measured values.")
        else:
            try:
                snapshot.stats = provider.period_queries()
                snapshot.sources.append("search_console")
            except Exception as exc:  # optional source: report and continue
                snapshot.notes.append(f"Search Console could not be read: {exc}")
        return snapshot
