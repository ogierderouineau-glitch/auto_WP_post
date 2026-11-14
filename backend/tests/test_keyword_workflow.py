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

    def find_by_urls(self, urls):
        return {url: self.service.get(url) for url in urls}


class FakeSearchConsole:
    def __init__(self, fail=False):
        self.fail = fail

    def period_queries(self):
        if self.fail:
            raise RuntimeError("HTTP 403")
        return [QueryStat("solar battery", "2026-08-14..2026-11-13", 7, 90, 2)]


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
    assert refreshed.selected_keywords == ["solar battery", "my own phrase"]  # typed-in keywords stay
    # A keyword that was proposed earlier but is no longer listed is dropped.
    service.language_model = service.revision_language_model = FakeModel([candidate("heat pump")])
    changed = service.propose_keywords(refreshed.session_id, expected_version=refreshed.version)
    assert changed.selected_keywords == ["my own phrase"]


def with_proposal(service, session, selected):
    proposal = {
        "rows": [{"keyword": "solar battery", "alternatives": ["home storage"], "status": "free",
                  "related_urls": [], "rationale": ""}],
    }
    focus = {
        "Heat pump": ["https://energy.example/heat/"],
        "Roof solar": ["https://energy.example/own/", "https://energy.example/other/"],
    }
    return service.repository.save(
        session.model_copy(update={"keyword_proposal": proposal, "selected_keywords": selected,
                                   "site_focus_keyphrases": focus}),
        expected_version=session.version,
    )


def test_generation_context_carries_selection_alternatives_and_conflicts(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    session = with_proposal(service, session, ["Solar  Battery", "my own phrase"])
    context = service._keyword_context(session, current_url="https://www.energy.example/own")
    assert context["selected_keywords"] == ["Solar  Battery", "my own phrase"]
    assert context["keyword_alternatives"] == {"Solar  Battery": ["home storage"]}
    # the post's own URL is not a conflict when it is being updated
    assert context["keyword_conflicts"] == {
        "Heat pump": ["https://energy.example/heat/"],
        "Roof solar": ["https://energy.example/other/"],
    }


def test_generation_context_without_selection_still_lists_conflicts(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    session = with_proposal(service, session, [])
    context = service._keyword_context(session)
    assert "selected_keywords" not in context and "keyword_conflicts" in context


def test_generation_context_is_empty_without_any_keyword_work(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    assert service._keyword_context(session) == {}


class CapturingModel:
    def __init__(self):
        self.payloads = []

    def structured(self, *, task, context, schema):
        import json

        self.payloads.append(json.loads(context["messages"][1]["content"])["context"])
        return schema.model_validate({name: "draft" for name in schema.model_fields})


def test_keywords_reach_the_generation_model_call(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    model = CapturingModel()
    service.language_model = service.revision_language_model = model
    session = with_proposal(service, session, ["solar battery"])
    service.generate(
        session.session_id, shared_fields={}, acf_source_fields={}, selected_links=[],
        current_url=None, expected_version=session.version,
    )
    assert model.payloads
    for payload in model.payloads:
        assert payload["selected_keywords"] == ["solar battery"]
        assert payload["keyword_alternatives"] == {"solar battery": ["home storage"]}
        assert "Heat pump" in payload["keyword_conflicts"]


class CountingScanner(FakeScanner):
    def __init__(self, fail=False, **kwargs):
        super().__init__(**kwargs)
        self.scans, self.fail = 0, fail

    def scan_collection(self, wp_post_type, category_ids=None):
        self.scans += 1
        if self.fail:
            raise RuntimeError("site down")
        return [page(1, "case-one", focus="Roof solar")]


class ForbiddenSearchConsole:
    def period_queries(self):
        raise AssertionError("the automatic scan must not read Search Console")


def generate(service, session):
    return service.generate(
        session.session_id, shared_fields={}, acf_source_fields={}, selected_links=[],
        current_url=None, expected_version=session.version,
    )


def test_generation_scans_the_site_once_when_no_keyword_step_ran(tmp_path):
    scanner = CountingScanner(categories=[4])
    service, session = build(tmp_path, scanner=scanner, search_console=ForbiddenSearchConsole())
    model = CapturingModel()
    service.language_model = service.revision_language_model = model
    done = generate(service, session)
    assert scanner.scans == 1
    assert done.site_focus_keyphrases == {"Roof solar": ["https://energy.example/case-one/"]}
    assert done.site_scanned_at
    assert model.payloads[0]["keyword_conflicts"] == done.site_focus_keyphrases
    assert "selected_keywords" not in model.payloads[0]
    generate(service, done)
    assert scanner.scans == 1  # already scanned for this session


def test_failed_automatic_scan_does_not_block_generation(tmp_path):
    service, session = build(tmp_path, scanner=CountingScanner(fail=True))
    model = CapturingModel()
    service.language_model = service.revision_language_model = model
    done = generate(service, session)
    assert model.payloads and "keyword_conflicts" not in model.payloads[0]
    assert done.site_scanned_at is None


def test_proposal_records_site_scan_for_later_generation(tmp_path):
    service, session = build(tmp_path, scanner=CountingScanner(categories=[4]))
    saved = service.propose_keywords(session.session_id, expected_version=session.version)
    assert saved.site_focus_keyphrases == {"Roof solar": ["https://energy.example/case-one/"]}
    assert "focus_keyphrases" not in saved.keyword_proposal


def test_selected_keywords_steer_link_ranking(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    snapshot = service.knowledge.current()
    eligible = service.internal_links.eligible(
        snapshot, post_type_key=session.post_type_key, language="en", current_url=None
    )
    plain = service.internal_links.rank(eligible, source_text="solar battery installation", maximum=1)
    steered = service.internal_links.rank(
        eligible, source_text="solar battery installation", keywords=("solar delta",), maximum=1
    )
    assert plain[0]["link_id"] != "delta"
    assert steered[0]["link_id"] == "delta"


def test_keyword_phrases_include_alternatives_of_selected_keywords(tmp_path):
    service, session = build(tmp_path, scanner=FakeScanner())
    session = with_proposal(service, session, ["solar battery", "my own phrase"])
    assert service._keyword_phrases(session) == ("solar battery", "home storage", "my own phrase")


def test_keywords_typed_in_by_hand_get_search_console_numbers(tmp_path):
    stats = [
        QueryStat("my own phrase", "2026-08-14..2026-11-13", 4, 80, 1),
        QueryStat("my own phrase near me", "2026-08-14..2026-11-13", 0, 30, 0),
    ]

    class Console:
        def period_queries(self):
            return stats

    service, session = build(tmp_path, scanner=FakeScanner(categories=[4]), search_console=Console())
    proposed = service.propose_keywords(session.session_id, expected_version=session.version)
    chosen = service.select_keywords(
        proposed.session_id, keywords=["My  Own phrase", "solar battery"], expected_version=proposed.version
    )
    custom = chosen.keyword_proposal["custom"]
    assert list(custom) == ["My Own phrase"]  # proposed rows are measured in the table already
    assert (custom["My Own phrase"]["clicks"], custom["My Own phrase"]["impressions"]) == (4, 80)
    assert custom["My Own phrase"]["related_searches"][0]["query"] == "my own phrase near me"
