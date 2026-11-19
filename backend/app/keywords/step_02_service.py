from __future__ import annotations

from typing import Any, Callable, Sequence

from backend.app.content_generation.step_02_prompts import structured_task_input
from backend.app.keywords.step_01_models import (
    KeywordProposalOutput,
    KeywordProposalRow,
    normalize_phrase,
)
from backend.app.keywords.step_04_measure import measure
from backend.app.providers.step_04_seo_sources import QueryStat, SiteEntry

MAX_CANDIDATES = 12
MAX_QUERIES = 150

APP_INSTRUCTIONS: tuple[dict[str, str], ...] = (
    {
        "instruction_de": (
            "Schlage Keywords und Keyphrasen vor, die zu den bestatigten Fakten des neuen "
            "Beitrags passen. Nenne zu jedem Keyword passende Alternativen (Varianten, "
            "Synonyme), damit mehrere Seiten unterschiedliche Begriffe abdecken."
        )
    },
    {
        "instruction_de": (
            "Pruefe anhand von existing_pages, ob ein Begriff schon als Fokus-Keyphrase "
            "(focus_keyphrase) einer anderen Seite dient (status focus_elsewhere) oder dort nur "
            "im Titel/Slug vorkommt (mentioned_elsewhere). Ist die Seite nur uber Slug und "
            "Titel bekannt (source slug_title), ist das eine Schatzung. Verwende sonst free."
        )
    },
    {
        "instruction_de": (
            "Bevorzuge Begriffe, die noch keine andere Seite als Fokus-Keyphrase nutzt, um "
            "Kannibalisierung zu vermeiden. search_console_queries zeigt reale Suchanfragen "
            "mit Klicks und Impressionen. Fehlen Messwerte, darf ein passender Begriff "
            "trotzdem vorgeschlagen werden."
        )
    },
    {
        "instruction_de": (
            "Nenne in related_refs nur Refs aus existing_pages. Erfinde weder Seiten noch "
            "Zahlen. Schreibe die Begrundung (rationale) in der Sprache language."
        )
    },
)


class KeywordService:
    """Proposes keywords for a new post from live site and Search Console data.

    `structured` is the existing retrying structured-call function of the session
    service: structured(task=..., messages=..., schema=...).
    """

    def __init__(self, structured: Callable[..., Any]) -> None:
        self._structured = structured

    def propose(
        self,
        *,
        facts: dict[str, Any],
        language: str,
        post_type_name: str,
        entries: Sequence[SiteEntry],
        stats: Sequence[QueryStat],
        client_instructions: Sequence[dict[str, str]] = (),
    ) -> list[KeywordProposalRow]:
        refs = {f"p{index}": entry for index, entry in enumerate(entries, start=1)}
        strongest = self._strongest_first(stats)
        output = self._structured(
            task="keyword_proposal",
            messages=structured_task_input(
                task="keyword_proposal",
                instructions=[*APP_INSTRUCTIONS, *client_instructions],
                context={
                    "language": language,
                    "post_type": post_type_name,
                    "confirmed_facts": facts,
                    "max_candidates": MAX_CANDIDATES,
                    "existing_pages": [
                        {
                            "ref": ref,
                            "page_type": entry.post_type,
                            "focus_keyphrase": entry.focus_keyphrase or None,
                            "synonyms": entry.synonyms or None,
                            "slug": entry.slug,
                            "title": entry.title,
                            "source": entry.source,
                        }
                        for ref, entry in refs.items()
                    ],
                    "search_console_queries": [
                        {
                            "query": stat.query,
                            "period": stat.period,
                            "clicks": stat.clicks,
                            "impressions": stat.impressions,
                            "clicks_delta": stat.clicks_delta,
                        }
                        for stat in strongest[:MAX_QUERIES]
                    ],
                },
            ),
            schema=KeywordProposalOutput,
        )
        return self._verify(output, refs, strongest)

    @staticmethod
    def _strongest_first(stats: Sequence[QueryStat]) -> list[QueryStat]:
        return sorted(stats, key=lambda s: (-s.clicks, -s.impressions, s.query))

    @staticmethod
    def _verify(
        output: KeywordProposalOutput,
        refs: dict[str, SiteEntry],
        stats: Sequence[QueryStat],
    ) -> list[KeywordProposalRow]:
        """Application facts win over model claims: an exact focus keyphrase match is
        `focus_elsewhere`, unknown refs are dropped, numbers come from Search Console."""
        focus_urls: dict[str, list[str]] = {}
        for entry in refs.values():
            if entry.focus_keyphrase:
                focus_urls.setdefault(normalize_phrase(entry.focus_keyphrase), []).append(entry.url)
        rows: list[KeywordProposalRow] = []
        seen: set[str] = set()
        for candidate in output.candidates:
            key = normalize_phrase(candidate.keyword)
            if not key or key in seen:
                continue
            seen.add(key)
            urls = [refs[ref].url for ref in candidate.related_refs if ref in refs]
            status = candidate.status
            if key in focus_urls:
                status = "focus_elsewhere"
                urls = [*dict.fromkeys([*focus_urls[key], *urls])]
            elif status == "focus_elsewhere":
                status = "mentioned_elsewhere" if urls else "free"  # no exact Yoast evidence
            numbers = measure(candidate.keyword, stats)
            rows.append(
                KeywordProposalRow(
                    keyword=candidate.keyword.strip(),
                    alternatives=[a.strip() for a in candidate.alternatives if a.strip()],
                    status=status,
                    related_urls=urls,
                    rationale=candidate.rationale,
                    clicks=numbers.clicks,
                    impressions=numbers.impressions,
                    clicks_delta=numbers.clicks_delta,
                    period=numbers.period,
                    related_searches=[r.model_dump() for r in numbers.related_searches],
                )
            )
        return rows[:MAX_CANDIDATES]
