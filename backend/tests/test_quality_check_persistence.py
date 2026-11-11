"""Track applied field-level recommendations without discarding the rest of a review."""
import json
from types import SimpleNamespace

import pytest

from backend.app.errors import DraftValidationError
from backend.tests.test_link_workflow import fixture, edit, revise


class RevisionProvider:
    def __init__(self, mode="change"):
        self.mode = mode

    def structured(self, *, task, context, schema):
        if task == "content_quality_check":
            return schema.model_validate({"rating": "natural", "summary": "Fresh review", "findings": []})
        data = json.loads(context["messages"][1]["content"])["context"]
        previous = {**data.get("current_shared_fields", {}), **data.get("current_acf_source_fields", {})}
        return schema.model_validate({key: previous[key] if self.mode == "unchanged" else "" if self.mode == "invalid" else f"Revised {key}."
                                      for key in schema.model_fields})


def reviewed_fixture(tmp_path, mode="change"):
    service, session, snapshot = fixture(tmp_path, provider=RevisionProvider(mode))
    report = {
        "rating": "needs_polish", "summary": "Original editorial assessment.", "reviewed_at": "2026-11-11T10:00:00Z",
        "findings": [{"field_id": field, "category": "repetition", "severity": "medium",
                      "explanation": f"Repeated wording {index}", "suggestion": "Use more specific wording."}
                     for index, field in enumerate(("acf:detail_x", "acf:detail_x", "acf:detail_y", "shared:category"))],
    }
    session = service.repository.save(session.model_copy(update={"generation_trace": {"quality_check": report}}), expected_version=session.version)
    return service, session, snapshot


def apply(service, session, field):
    return service.generate(session.session_id, shared_fields={}, acf_source_fields={}, selected_links=session.selected_links,
                            current_url=None, revision_instruction="Apply the selected quality-check recommendations.",
                            revision_field_ids=[field], expected_version=session.version)


def test_successful_revisions_remove_only_applied_fields_and_persist_remaining_review(tmp_path):
    service, session, _ = reviewed_fixture(tmp_path)
    first = apply(service, session, "acf:detail_x")
    report = first.generation_trace["quality_check"]
    assert [finding["field_id"] for finding in report["findings"]] == ["acf:detail_y", "shared:category"]
    assert report["applied_finding_count"] == 2
    assert report["summary"] == session.generation_trace["quality_check"]["summary"]
    assert report["rating"] == "needs_polish"
    assert report["reviewed_at"] == session.generation_trace["quality_check"]["reviewed_at"]
    assert service.repository.get(session.session_id).generation_trace["quality_check"] == report
    second = apply(service, first, "acf:detail_y")
    final = apply(service, second, "shared:category")
    assert final.generation_trace["quality_check"]["findings"] == []
    assert final.generation_trace["quality_check"]["applied_finding_count"] == 4
    assert "quality_check" in service.get(session.session_id).generation_trace


def test_noop_revision_keeps_findings(tmp_path):
    service, session, _ = reviewed_fixture(tmp_path, mode="unchanged")
    revised = apply(service, session, "acf:detail_x")
    assert revised.generation_trace["quality_check"] == session.generation_trace["quality_check"]


def test_failed_revision_does_not_consume_recommendations(tmp_path):
    service, session, snapshot = reviewed_fixture(tmp_path, mode="invalid")
    snapshot = snapshot.model_copy(update={"acf_fields": tuple(row.model_copy(update={"required_for_output": True}) for row in snapshot.acf_fields)})
    service.knowledge = SimpleNamespace(by_hash=lambda _: snapshot, current=lambda: snapshot)
    with pytest.raises(DraftValidationError):
        apply(service, session, "acf:detail_x")
    assert service.repository.get(session.session_id) == session


def test_link_only_placement_and_removal_keep_unapplied_recommendations(tmp_path):
    service, session, _ = reviewed_fixture(tmp_path)
    session = edit(service, session, "add", "alpha")
    inserted = revise(service, session)
    removed = edit(service, inserted, "remove", "alpha")
    assert removed.generation_trace["quality_check"] == session.generation_trace["quality_check"]


def test_full_generation_invalidates_review_and_new_check_resets_applied_count(tmp_path):
    service, session, _ = reviewed_fixture(tmp_path)
    applied = apply(service, session, "acf:detail_x")
    refreshed = service.review_content_quality(applied.session_id, expected_version=applied.version)
    assert refreshed.generation_trace["quality_check"]["summary"] == "Fresh review"
    assert "applied_finding_count" not in refreshed.generation_trace["quality_check"]
    generated = service.generate(refreshed.session_id, shared_fields=refreshed.shared_fields, acf_source_fields=refreshed.acf_source_fields,
                                 selected_links=[], current_url=None, expected_version=refreshed.version)
    assert "quality_check" not in generated.generation_trace
