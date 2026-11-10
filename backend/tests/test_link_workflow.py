"""Link changes with unrelated client schemas, no workbook or provider credentials needed."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.app.api.step_02_routes import create_router, v2_error_handler
from backend.app.errors import InvalidInternalLinksError, SessionVersionConflictError, V2Error
from backend.app.internal_links.step_01_service import EligibleLinks, InternalLinkService
from backend.app.internal_links.step_02_editor import insert_link, link_urls, unlink_url
from backend.app.knowledge_base.step_01_models import (
    ACFFieldSchema, ApplicationState, InternalLinkRecord, InternalLinkRule,
    PostTypeConfig, SharedFieldSchema, WorkbookSnapshot, WorkbookVersion,
)
from backend.app.models.step_01_session import Approval, ContentSession
from backend.app.sessions.step_01_repository import FileSessionRepository
from backend.app.sessions.step_03_service import ContentSessionService
from backend.config import DEFAULT_CLIENT_ID, set_active_client


POST_TYPE = "battery_case_91"


def link(key, **changes):
    return InternalLinkRecord(
        sheet_row=2, link_id=key, post_type_key=POST_TYPE, keyword="solar battery",
        anchor_text=f"solar {key}", target_url=f"https://energy.example/{key}?a=1&b=2",
        link_role="service", category="storage", priority="high", active=True,
        usage_context="solar battery installation", language="en", **changes,
    )


def fixture(tmp_path, *, provider=None, maximum=2):
    common = dict(sheet_row=2, enabled=True, include_in_ai_schema=True, include_in_payload=True,
                  generation_stage="generation", source_mode="ai", required_for_output=False,
                  description_de="Battery installation")
    fields = tuple(ACFFieldSchema(
        **common, post_type_key=POST_TYPE, field_key=key, field_role="output",
        acf_field_name=f"wp_{key}", required_for_analysis=False, value_type="html",
        allow_internal_links=True, max_internal_links=2,
    ) for key in ("detail_x", "detail_y"))
    shared = tuple(SharedFieldSchema(
        **common, field_key=key, group="wordpress", destination_type="wordpress",
        destination_key=destination, value_type="string",
    ) for key, destination in (("status", "status"), ("category", "categories")))
    post = PostTypeConfig(
        sheet_row=2, post_type_key=POST_TYPE, display_name_de="Energy case", enabled=True,
        development_status="ready", wp_post_type="case_study", wp_category_name="Energy",
        default_language="en", default_status="draft", template_ready=True, generation_enabled=True,
        image_rules_profile="default", seo_profile="default", description_de="Storage case", user_selectable=True,
    )
    states = tuple(ApplicationState(
        sheet_row=2, state=state, terminal=False, allowed_next_states=next_states,
        entered_when_de="", ui_behavior_de="",
    ) for state, next_states in (("needs_review", ("generating",)), ("generating", ("needs_review",))))
    data = {key: () for key in WorkbookSnapshot.model_fields if key != "version"}
    data.update(post_types=(post,), acf_fields=fields, shared_fields=shared, application_states=states,
                internal_links=tuple(link(key) for key in ("alpha", "beta", "gamma", "delta")),
                internal_link_rules=(InternalLinkRule(
                    sheet_row=2, rule_id="budget", enabled=True, owner="app", action_type="limit",
                    applies_to="internal_links", operator="between", value=f"0;{maximum}", value_type="string",
                    instruction_de="", priority="high",
                ),))
    snapshot = WorkbookSnapshot(version=WorkbookVersion(filename="energy.xlsx", sha256="energy",
                               loaded_at=datetime.now(timezone.utc)), **data)
    repo = FileSessionRepository(tmp_path)
    session = repo.create(ContentSession(
        session_id="energy-session", user_id="energy-client", post_type_key=POST_TYPE,
        state="needs_review", workbook_hash="energy", language="en",
        shared_fields={"status": "draft", "category": "Energy"},
        acf_source_fields={"detail_x": "<p>Solar battery installation and solar alpha are available.</p>",
                           "detail_y": "<p>A storage system for the future.</p>"},
        wordpress_payload={"acf": {}}, approval=Approval(approved=True),
        manual_text="Solar battery installation",
    ))
    service = ContentSessionService(
        knowledge=SimpleNamespace(by_hash=lambda _: snapshot, current=lambda: snapshot),
        repository=repo, language_model=provider,
    )
    return service, session, snapshot


def edit(service, session, action, key=None):
    return service.edit_link_candidates(session.session_id, action=action, link_id=key, expected_version=session.version)


def revise(service, session, **kwargs):
    selections = [dict(item, revision_requested="true") for item in session.selected_links]
    return service.generate(
        session.session_id, shared_fields={}, acf_source_fields={}, selected_links=selections,
        current_url=None, revision_instruction="Place selected links", revision_field_ids=[],
        link_placement_only=True, expected_version=session.version, **kwargs,
    )


class MinimalProvider:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def structured(self, *, task, context, schema):
        payload = json.loads(context["messages"][1]["content"])["context"]
        self.calls.append((task, payload))
        assert task == "internal_link_revision"
        values = dict(payload["current_acf_source_fields"])
        if not self.fail:
            for assignment in payload["assignments"]:
                key = assignment["field_key"]
                values[key] += f' Choose {assignment["approved_anchors"][0]} for this solar system.'
        return schema.model_validate(values)


def test_candidate_limit_persistence_removal_and_manual_readdition(tmp_path):
    service, session, snapshot = fixture(tmp_path)
    first = edit(service, session, "add", "alpha")
    second = edit(service, first, "add", "beta")
    with pytest.raises(InvalidInternalLinksError, match="limit"):
        edit(service, second, "add", "gamma")
    removed = edit(service, second, "remove", "alpha")
    assert removed.excluded_link_ids == ["alpha"]
    assert service.get(session.session_id).selected_links == removed.selected_links
    refreshed = edit(service, removed, "refresh")
    assert len(refreshed.selected_links) <= 2
    assert "alpha" not in {item["link_id"] for item in refreshed.selected_links}
    cleared = refreshed
    for item in list(cleared.selected_links):
        cleared = edit(service, cleared, "remove", item["link_id"])
    readded = edit(service, cleared, "add", "alpha")
    assert "alpha" not in readded.excluded_link_ids
    assert service.link_options(session.session_id)["maximum"] == 2
    with pytest.raises(SessionVersionConflictError):
        edit(service, session, "add", "beta")


def test_placed_removal_preserves_inner_html_and_refresh_preserves_placed(tmp_path):
    service, session, snapshot = fixture(tmp_path)
    session = edit(service, session, "add", "alpha")
    session = revise(service, session)
    assert snapshot.internal_links[0].target_url in link_urls(session.acf_source_fields.values())
    before_text = unlink_url(session.acf_source_fields["detail_x"], snapshot.internal_links[0].target_url)
    session = edit(service, session, "add", "beta")
    refreshed = edit(service, session, "refresh")
    assert "alpha" in {item["link_id"] for item in refreshed.selected_links}
    assert "beta" not in {item["link_id"] for item in refreshed.selected_links}
    removed = edit(service, refreshed, "remove", "alpha")
    assert removed.acf_source_fields["detail_x"] == before_text
    assert snapshot.internal_links[0].target_url not in link_urls(removed.acf_source_fields.values())
    assert not removed.approval.approved


def test_deterministic_placement_uses_no_ai_and_changes_only_destination(tmp_path):
    provider = MinimalProvider()
    service, session, _ = fixture(tmp_path, provider=provider)
    session = edit(service, session, "add", "alpha")
    before = session.acf_source_fields["detail_y"]
    placed = revise(service, session)
    assert not provider.calls
    assert placed.acf_source_fields["detail_y"] == before
    assert "alpha" in service.link_options(session.session_id)["placed_link_ids"]


def test_fallback_rewrites_one_field_and_does_not_send_examples(tmp_path):
    provider = MinimalProvider()
    service, session, _ = fixture(tmp_path, provider=provider)
    session = edit(service, session, "add", "beta")
    before = dict(session.acf_source_fields)
    placed = revise(service, session)
    assert len(provider.calls) == 1
    task, context = provider.calls[0]
    assert "examples" not in context
    assert len(context["current_acf_source_fields"]) == 1
    changed = [key for key, value in placed.acf_source_fields.items() if before[key] != value]
    assert changed == ["detail_x"]
    assert "beta" in service.link_options(session.session_id)["placed_link_ids"]


def test_failed_fallback_leaves_saved_draft_unchanged(tmp_path):
    service, session, _ = fixture(tmp_path, provider=MinimalProvider(fail=True))
    session = edit(service, session, "add", "beta")
    before = service.get(session.session_id).model_dump()
    with pytest.raises(InvalidInternalLinksError, match="Could not place"):
        revise(service, session)
    assert service.get(session.session_id).model_dump() == before


def test_destination_relevance_and_capacity_are_local(tmp_path):
    service, session, snapshot = fixture(tmp_path)
    fields = service._linkable_acf_fields(snapshot, session)
    assert service.internal_links.choose_destination(snapshot.internal_links[0], fields, session.acf_source_fields) == "detail_x"
    full = {**session.acf_source_fields, "detail_x": '<a href="a">A</a><a href="b">B</a>'}
    assert service.internal_links.choose_destination(snapshot.internal_links[0], fields, full) == "detail_y"


def test_manual_external_link_inserts_without_rewriting_and_validates_url(tmp_path):
    service, session, _ = fixture(tmp_path)
    value = session.acf_source_fields["detail_x"]
    text = "Solar battery"
    start = value.index(text)
    linked = service.insert_manual_link(session.session_id, field_key="detail_x", url="https://external.example/guide",
                                        start=start, end=start + len(text), selected_text=text, expected_version=session.version)
    assert unlink_url(linked.acf_source_fields["detail_x"], "https://external.example/guide") == value
    assert not linked.approval.approved
    with pytest.raises(InvalidInternalLinksError):
        service.insert_manual_link(linked.session_id, field_key="detail_y", url="javascript:alert(1)",
                                   start=3, end=4, selected_text="A", expected_version=linked.version)


def test_markup_handles_entities_formatting_and_browser_unicode_offsets():
    source = '<p>😀 solar <a class="x" href="https://x.example/?a=1&amp;b=2"><strong>panel</strong></a>.</p>'
    assert unlink_url(source, "https://x.example/?a=1&b=2") == '<p>😀 solar <strong>panel</strong>.</p>'
    linked = insert_link(source, url="https://y.example", start=6, end=11, selected_text="solar")
    assert '<a href="https://y.example">solar</a>' in linked
    for start, end, text in [(2, 6, source[2:6]), (0, len(source), source)]:
        with pytest.raises(ValueError):
            insert_link(source, url="https://z.example", start=start, end=end, selected_text=text)


def test_link_api_is_scoped_and_rejects_cross_client_access(tmp_path):
    async def check():
        service, session, _ = fixture(tmp_path)
        app = FastAPI()
        app.add_exception_handler(V2Error, v2_error_handler)
        app.include_router(create_router(lambda: service))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            try:
                set_active_client("wrong-client")
                assert (await client.get(f"/api/content-sessions/{session.session_id}/links")).status_code == 403
                assert (await client.put(f"/api/content-sessions/{session.session_id}/link-candidates", json={"action":"add", "link_id":"alpha", "expected_version":1})).status_code == 403
                set_active_client("energy-client")
                assert (await client.get(f"/api/content-sessions/{session.session_id}/links")).status_code == 200
                assert (await client.put(f"/api/content-sessions/{session.session_id}/link-candidates", json={"action":"add", "link_id":"alpha", "expected_version":1})).status_code == 200
            finally:
                set_active_client(DEFAULT_CLIENT_ID)
    asyncio.run(check())


def test_refresh_empty_pool_and_exclusions_survive_full_regeneration(tmp_path):
    service, session, snapshot = fixture(tmp_path)
    for key in ("alpha", "beta", "gamma", "delta"):
        session = edit(service, session, "add", key)
        session = edit(service, session, "remove", key)
    refreshed = edit(service, session, "refresh")
    assert refreshed.selected_links == []
    generated = service.generate(
        refreshed.session_id, shared_fields=refreshed.shared_fields, acf_source_fields=refreshed.acf_source_fields,
        selected_links=[], current_url=None, expected_version=refreshed.version,
    )
    assert generated.selected_links == []
    assert set(generated.excluded_link_ids) == {row.link_id for row in snapshot.internal_links}


def test_no_field_capacity_fails_without_ai_or_draft_changes(tmp_path):
    provider = MinimalProvider()
    service, session, _ = fixture(tmp_path, provider=provider)
    full = {key: '<p><a href="https://one.example">One</a> <a href="https://two.example">Two</a></p>'
            for key in session.acf_source_fields}
    session = service.repository.save(session.model_copy(update={"acf_source_fields": full}), expected_version=session.version)
    session = edit(service, session, "add", "beta")
    before = session.model_dump()
    with pytest.raises(InvalidInternalLinksError):
        revise(service, session)
    assert not provider.calls
    assert service.get(session.session_id).model_dump() == before


def test_multiple_unresolved_candidates_share_one_small_ai_call(tmp_path):
    provider = MinimalProvider()
    service, session, _ = fixture(tmp_path, provider=provider)
    session = edit(service, session, "add", "beta")
    session = edit(service, session, "add", "gamma")
    placed = revise(service, session)
    assert len(provider.calls) == 1
    assert len(provider.calls[0][1]["current_acf_source_fields"]) == 1
    assert {"beta", "gamma"}.issubset(service.link_options(placed.session_id)["placed_link_ids"])


def test_ineligible_library_links_cannot_be_added(tmp_path):
    service, session, snapshot = fixture(tmp_path)
    extra = tuple(snapshot.internal_links[0].model_copy(update=change) for change in (
        {"link_id": "inactive", "active": False}, {"link_id": "other-language", "language": "fr"},
        {"link_id": "other-type", "post_type_key": "dentistry_guide"},
    ))
    revised = snapshot.model_copy(update={"internal_links": (*snapshot.internal_links, *extra)})
    service.knowledge = SimpleNamespace(by_hash=lambda _: revised, current=lambda: revised)
    library_ids = {row["link_id"] for row in service.link_options(session.session_id)["links"]}
    for row in extra:
        assert row.link_id not in library_ids
        with pytest.raises(InvalidInternalLinksError):
            edit(service, session, "add", row.link_id)


def test_raw_url_mentions_are_not_treated_as_placed_links(tmp_path):
    service, session, snapshot = fixture(tmp_path)
    session = service.repository.save(session.model_copy(update={
        "acf_source_fields": {"detail_x": snapshot.internal_links[0].target_url, "detail_y": "Other text"},
    }), expected_version=session.version)
    assert service.link_options(session.session_id)["placed_link_ids"] == []


def test_revision_places_only_checked_candidates_and_clears_stale_quality_report(tmp_path):
    service, session, _ = fixture(tmp_path)
    session = edit(service, session, "add", "alpha")
    session = edit(service, session, "add", "beta")
    session = service.repository.save(session.model_copy(update={
        "acf_source_fields": {**session.acf_source_fields, "detail_y": "We also offer solar beta."},
        "generation_trace": {"quality_check": {"summary": "Old content review"}},
    }), expected_version=session.version)
    selections = [dict(item, revision_requested="true") if item["link_id"] == "alpha" else dict(item)
                  for item in session.selected_links]
    revised = service.generate(
        session.session_id, shared_fields={}, acf_source_fields={}, selected_links=selections,
        current_url=None, revision_instruction="Place selected link", revision_field_ids=[],
        link_placement_only=True, expected_version=session.version,
    )
    assert service.link_options(session.session_id)["placed_link_ids"] == ["alpha"]
    assert len(revised.selected_links) == 2
    assert revised.acf_source_fields["detail_y"] == session.acf_source_fields["detail_y"]
    assert "quality_check" not in revised.generation_trace
