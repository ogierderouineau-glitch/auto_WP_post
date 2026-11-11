"""Repair required outputs from workbook changes during a targeted revision."""
import json
from types import SimpleNamespace

import pytest

from backend.app.errors import DraftValidationError
from backend.app.models.step_01_session import FactValue
from backend.tests.test_link_workflow import fixture, edit, revise


class RepairProvider:
    def __init__(self, fail_missing=False):
        self.calls = []
        self.fail_missing = fail_missing

    def structured(self, *, task, context, schema):
        data = json.loads(context["messages"][1]["content"])["context"]
        self.calls.append(data)
        return schema.model_validate({
            key: "" if self.fail_missing and key.startswith("new_") else f"Generated {key}."
            for key in schema.model_fields
        })


def upgraded(service, old, *rows, shared=()):
    current = old.model_copy(update={
        "version": old.version.model_copy(update={"sha256": "upgraded-schema"}),
        "acf_fields": (*old.acf_fields, *rows), "shared_fields": (*old.shared_fields, *shared),
    })
    service.knowledge = SimpleNamespace(by_hash=lambda _: current, current=lambda: current)
    return current


def required_row(base, key, **changes):
    return base.model_copy(update={"field_key": key, "acf_field_name": f"wp_{key}",
                                   "field_role": "direct_acf", "required_for_output": True, **changes})


def revise_field(service, session):
    return service.generate(
        session.session_id, shared_fields={}, acf_source_fields={}, selected_links=[], current_url=None,
        revision_instruction="Revise only the selected paragraph.", revision_field_ids=["acf:detail_x"],
        expected_version=session.version,
    )


def test_revision_inserts_missing_required_outputs_without_overwriting_other_content(tmp_path):
    provider = RepairProvider()
    service, session, old = fixture(tmp_path, provider=provider)
    summary = old.shared_fields[0].model_copy(update={
        "field_key": "new_summary_8", "required_for_output": True,
        "destination_type": "yoast", "destination_key": "custom_summary",
    })
    upgraded(service, old, required_row(old.acf_fields[0], "new_heading_27"),
             required_row(old.acf_fields[0], "new_details_31"),
             required_row(old.acf_fields[0], "optional_new", required_for_output=False), shared=(summary,))
    session = service.repository.save(session.model_copy(update={
        "acf_source_fields": {**session.acf_source_fields, "new_details_31": ""},
    }), expected_version=session.version)
    updated = revise_field(service, session)
    assert updated.validation_report["valid"]
    assert updated.workbook_hash == "upgraded-schema"
    assert updated.acf_source_fields["detail_y"] == session.acf_source_fields["detail_y"]
    assert updated.shared_fields["status"] == session.shared_fields["status"]
    assert updated.shared_fields["category"] == session.shared_fields["category"]
    assert updated.wordpress_payload["acf"]["wp_new_heading_27"] == "Generated new_heading_27."
    assert updated.wordpress_payload["acf"]["wp_new_details_31"] == "Generated new_details_31."
    assert updated.wordpress_payload["meta"]["custom_summary"] == "Generated new_summary_8."
    assert "optional_new" not in updated.acf_source_fields
    assert len(provider.calls) == 1
    assert set(provider.calls[0]["fields"]) == {"detail_x", "new_heading_27", "new_details_31", "new_summary_8"}
    assert set(provider.calls[0]["draft_revision"]["additional_required_field_ids"]) == {
        "acf:new_heading_27", "acf:new_details_31", "shared:new_summary_8",
    }


def test_missing_derived_output_uses_confirmed_facts_without_an_ai_call(tmp_path):
    provider = RepairProvider()
    service, session, old = fixture(tmp_path, provider=provider)
    session = edit(service, session, "add", "alpha")
    session = service.repository.save(session.model_copy(update={
        "confirmed_facts": {"capacity_fact_43": FactValue(value=88, source="user_correction", confidence=1, confirmed=True)},
    }), expected_version=session.version)
    upgraded(service, old, required_row(old.acf_fields[0], "new_capacity_52", source_mode="derived_from_facts",
                                        source_fact_keys=("capacity_fact_43",), include_in_ai_schema=False))
    updated = revise(service, session)
    assert updated.acf_source_fields["new_capacity_52"] == "88"
    assert updated.wordpress_payload["acf"]["wp_new_capacity_52"] == "88"
    assert not provider.calls


def test_link_only_revision_also_repairs_missing_generated_fields(tmp_path):
    provider = RepairProvider()
    service, session, old = fixture(tmp_path, provider=provider)
    session = edit(service, session, "add", "alpha")
    upgraded(service, old, required_row(old.acf_fields[0], "new_heading_27"))
    updated = revise(service, session)
    assert updated.acf_source_fields["new_heading_27"] == "Generated new_heading_27."
    assert "alpha" in service.link_options(session.session_id)["placed_link_ids"]
    assert len(provider.calls) == 1
    assert set(provider.calls[0]["fields"]) == {"new_heading_27"}
    assert updated.acf_source_fields["detail_y"] == session.acf_source_fields["detail_y"]


def test_failed_repair_still_preserves_the_saved_draft(tmp_path):
    service, session, old = fixture(tmp_path, provider=RepairProvider(fail_missing=True))
    upgraded(service, old, required_row(old.acf_fields[0], "new_heading_27"))
    with pytest.raises(DraftValidationError):
        revise_field(service, session)
    assert service.get(session.session_id) == session


def test_missing_slots_are_listed_without_writes_and_can_be_manually_saved(tmp_path):
    service, session, old = fixture(tmp_path)
    upgraded(service, old, required_row(old.acf_fields[0], "new_heading_27"))
    listed = service.draft_field_options(session.session_id)
    assert "new_heading_27" in {row["field_key"] for row in listed["acf_fields"]}
    assert service.get(session.session_id) == session
    saved = service.update_draft_fields(session.session_id, shared_fields={},
                                       acf_source_fields={"new_heading_27": "User-written heading"}, expected_version=session.version)
    assert saved.acf_source_fields["new_heading_27"] == "User-written heading"
    assert saved.wordpress_payload["acf"]["wp_new_heading_27"] == "User-written heading"
    assert saved.workbook_hash == "upgraded-schema"
    assert saved.acf_source_fields["detail_y"] == session.acf_source_fields["detail_y"]


def test_field_list_uses_only_eligible_output_fields_for_this_post_type(tmp_path):
    service, session, old = fixture(tmp_path)
    base = old.acf_fields[0]
    upgraded(service, old,
             required_row(base, "new_heading_27"),
             required_row(base, "input_only", field_role="input_fact"),
             required_row(base, "inactive", enabled=False),
             required_row(base, "other_industry", post_type_key="medical_guide"),
             required_row(base, "publication_id", generation_stage="payload_construction", source_mode="derived"),
             required_row(base, "unavailable_facts", source_fact_keys=("unknown_fact",), source_mode="derived_from_facts"))
    keys = {row["field_key"] for row in service.draft_field_options(session.session_id)["acf_fields"]}
    assert keys == {"detail_x", "detail_y", "new_heading_27"}


def test_new_blank_slot_can_be_explicitly_selected_for_ai_revision(tmp_path):
    provider = RepairProvider()
    service, session, old = fixture(tmp_path, provider=provider)
    upgraded(service, old, required_row(old.acf_fields[0], "new_heading_27", required_for_output=False))
    saved = service.generate(session.session_id, shared_fields={}, acf_source_fields={}, selected_links=[], current_url=None,
                             revision_instruction="Write this missing field.", revision_field_ids=["acf:new_heading_27"],
                             expected_version=session.version)
    assert saved.acf_source_fields["new_heading_27"] == "Generated new_heading_27."
    assert saved.acf_source_fields["detail_x"] == session.acf_source_fields["detail_x"]
    assert set(provider.calls[0]["fields"]) == {"new_heading_27"}
