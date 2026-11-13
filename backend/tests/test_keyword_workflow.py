"""Keyword proposal workflow with an energy-industry fixture (no real providers)."""
from types import SimpleNamespace

import pytest

from backend.app.errors import (
    DraftValidationError,
    InvalidUploadError,
    MissingRequiredFactsError,
    SessionVersionConflictError,
)
from backend.app.keywords.step_01_models import KeywordCandidate, KeywordProposalOutput
from backend.app.keywords.step_03_sources import SeoSources
from backend.app.models.step_01_session import FactValue
from backend.app.providers.step_04_seo_sources import QueryStat, SiteEntry
from backend.tests.test_link_workflow import fixture


def page(wp_id, slug, focus="", kind="case_study"):
    return SiteEntry(wp_id, kind, slug, slug, f"https://energy.example/{slug}/", focus)


class FakeScanner:
    def __init__(self, categories=(), collection=(), service=None):
        self.categories, self.collection = list(categories), list(collection)
        self.service = service or {}
        self.scanned_with = "unset"

    def category_ids(self, *names):
        self.names = names
        return self.categories

    def scan_collection(self, wp_post_type, category_ids=None):
        self.scanned_with = category_ids
        return self.collection

    def find_by_url(self, url):
        return self.service.get(url)


class FakeSearchConsole:
    def __init__(self, fail=False):
        self.fail = fail

    def monthly_queries(self):
        if self.fail:
            raise RuntimeError("HTTP 403")
        return [QueryStat("solar battery", "2026-10", 7, 90, 2)]


class FakeModel:
    def __init__(self, candidates):
        self.candidates = candidates

    def structured(self, *, task, context, schema):
        return KeywordProposalOutput(candidates=self.candidates)


def candidate(keyword, **kw):
    return KeywordCandidate(keyword=keyword, status=kw.pop("status", "free"), rationale="fits", **kw)


def build(tmp_path, *, scanner=None, search_console=None, sources=True, service_category="storage"):
    service, session, _ = fixture(tmp_path, provider=FakeModel(
        [candidate("solar battery", alternatives=["home storage"]), candidate("heat pump")]
    ))
    if sources:
        service.seo_sources = SeoSources(
            scanner_factory=lambda: scanner,
            search_console_factory=lambda: search_console,
            service_category=service_category,
        )
    facts = {"system": FactValue(value="10 kWh battery", source="manual_text", confidence=1)}
    session = service.repository.save(
        session.model_copy(update={"extracted_facts": facts}), expected_version=session.version
    )
    return service, session


def test_proposal_is_saved_with_stages_notes_and_measurements(tmp_path):
    service_page = page(9, "storage-service", kind="page")
    scanner = FakeScanner(
        categories=[4], collection=[page(1, "case-one", focus="Solar Battery")],
        service={"https://energy.example/alpha?a=1&b=2": service_page},
    )
    service, session = build(tmp_path, scanner=scanner, search_console=FakeSearchConsole())
    stages = []
    saved = service.propose_keywords(session.session_id, expected_version=session.version, progress=stages.append)
    proposal = saved.keyword_proposal
    assert stages == ["Scanning WordPress", "Reading Search Console", "Analysing keywords"]
    assert scanner.scanned_with == [4]
    assert proposal["scanned_pages"] == 2  # one post of the type + one service page
    assert proposal["sources"] == ["wordpress", "search_console"]
    first, second = proposal["rows"]
    assert first["status"] == "focus_elsewhere"  # exact Yoast match beats the model's "free"
    assert (first["clicks"], first["clicks_delta"]) == (7, 2)
    assert second["clicks"] is None
    assert saved.version == session.version + 1


def test_search_console_failure_is_reported_not_fatal(tmp_path):
    scanner = FakeScanner(categories=[4])
    service, session = build(tmp_path, scanner=scanner, search_console=FakeSearchConsole(fail=True))
    saved = service.propose_keywords(session.session_id, expected_version=session.version)
    assert any("Search Console could not be read" in note for note in saved.keyword_proposal["notes"])
    assert saved.keyword_proposal["sources"] == ["wordpress"]


def test_custom_post_type_without_category_match_scans_whole_collection(tmp_path):
    scanner = FakeScanner(categories=[], collection=[page(1, "case-one")])
    service, session = build(tmp_path, scanner=scanner, service_category="")
    saved = service.propose_keywords(session.session_id, expected_version=session.version)
    assert scanner.scanned_with is None
    assert saved.keyword_proposal["scanned_pages"] == 1
    assert any("No service page category" in n for n in saved.keyword_proposal["notes"])
    assert any("Search Console is not configured" in n for n in saved.keyword_proposal["notes"])


def test_post_type_without_matching_category_scans_nothing():
    scanner = FakeScanner(categories=[], collection=[page(1, "unrelated", kind="post")])
    post_type = SimpleNamespace(display_name_de="Case", wp_category_name="Cases", wp_post_type="post")
    snapshot = SeoSources(
        scanner_factory=lambda: scanner, search_console_factory=lambda: None
    ).gather(post_type=post_type, internal_links=[])
    assert snapshot.entries == []
    assert any("No WordPress category matches" in n for n in snapshot.notes)


def test_guards(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    with pytest.raises(SessionVersionConflictError):
        service.propose_keywords(session.session_id, expected_version=session.version + 5)
    no_facts = service.repository.save(
        session.model_copy(update={"extracted_facts": {}}), expected_version=session.version
    )
    with pytest.raises(MissingRequiredFactsError):
        service.propose_keywords(no_facts.session_id, expected_version=no_facts.version)
    service.seo_sources = None
    with pytest.raises(DraftValidationError):
        service.propose_keywords(no_facts.session_id, expected_version=no_facts.version)


def test_selection_is_validated_stored_and_pruned_on_new_proposal(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner(categories=[4]))
    saved = service.select_keywords(
        session.session_id, keywords=[" solar  battery ", "solar battery", "my own phrase"],
        expected_version=session.version,
    )
    assert saved.selected_keywords == ["solar battery", "my own phrase"]
    cleared = service.select_keywords(saved.session_id, keywords=[], expected_version=saved.version)
    assert cleared.selected_keywords == []
    with pytest.raises(InvalidUploadError):
        service.select_keywords(cleared.session_id, keywords=["x" * 81], expected_version=cleared.version)
    with pytest.raises(InvalidUploadError):
        service.select_keywords(cleared.session_id, keywords=[str(i) for i in range(13)], expected_version=cleared.version)
    again = service.propose_keywords(cleared.session_id, expected_version=cleared.version)
    assert again.selected_keywords == []
    selected = service.select_keywords(
        again.session_id, keywords=["solar battery", "my own phrase"], expected_version=again.version
    )
    refreshed = service.propose_keywords(selected.session_id, expected_version=selected.version)
    assert refreshed.selected_keywords == ["solar battery"]  # the free-text one is not in the new list
