"""External-link behavior is derived from the service's own configured WordPress host."""
from copy import deepcopy

import pytest

from backend.app.knowledge_base.step_01_models import ApplicationState
from backend.app.models.step_02_payload import WordPressPayload
from backend.app.payloads.step_02_builder import PayloadBuilder
from backend.app.payloads.step_03_link_targets import ExternalLinkTargets
from backend.app.sessions.step_03_service import ContentSessionService
from backend.tests.test_link_workflow import fixture


@pytest.mark.parametrize("href", [
    "https://external.example/guide", "http://external.example/guide", "//external.example/guide",
])
def test_external_http_links_open_in_new_tab(href):
    source = f'<p>Read <a href="{href}"><strong>this guide</strong></a>.</p>'
    result = ExternalLinkTargets("https://energy.example").apply(source)
    assert result == source.replace('><strong>', ' target="_blank" rel="noopener"><strong>')


@pytest.mark.parametrize("href", [
    "https://energy.example/page", "http://www.ENERGY.example/page", "//energy.example/path",
    "/relative", "relative/page", "#section", "?page=2", "mailto:help@external.example",
    "tel:+12345", "ftp://external.example/file", "javascript:void(0)", "https://[invalid",
])
def test_internal_relative_and_non_web_links_are_unchanged(href):
    source = f'<a class="x" href="{href}">Link</a>'
    assert ExternalLinkTargets("https://www.energy.example/site").apply(source) == source


def test_target_replacement_preserves_other_attributes_entities_and_inner_markup():
    source = "<p>😀 <A\n data-label=\"target='_self'\" href='https://other.example/?a=1&amp;b=2' TARGET='_self' rel='nofollow sponsored opener'><em>Guide &amp; details</em></A></p>"
    result = ExternalLinkTargets("https://energy.example").apply(source)
    assert result == source.replace("TARGET='_self'", 'target="_blank"').replace("rel='nofollow sponsored opener'", 'rel="nofollow sponsored noopener"')
    assert ExternalLinkTargets("https://energy.example").apply(result) == result


def test_duplicate_attributes_cannot_override_new_tab_or_noopener():
    source = '<a href="https://other.example" target="_self" target="_blank" rel="opener" rel="nofollow">Guide</a>'
    result = ExternalLinkTargets("https://energy.example").apply(source)
    assert 'target="_self"' not in result
    assert 'rel="opener"' not in result
    assert 'rel="nofollow noopener"' in result
    assert ExternalLinkTargets("https://energy.example").apply(result) == result


def test_existing_correct_attributes_and_non_html_values_are_preserved():
    policy = ExternalLinkTargets("https://energy.example")
    correct = '<a href="https://other.example" target=\'_blank\' rel="noopener nofollow">Guide</a>'
    assert policy.apply(correct) == correct
    assert policy.apply({"nested": [correct, 0, False, None]}) == {"nested": [correct, 0, False, None]}
    script = '<script>const sample = \'<a href="https://other.example">text</a>\';</script>'
    assert policy.apply(script) == script


def test_client_host_configuration_is_isolated_and_missing_config_does_not_guess():
    source = '<a href="https://alpha.example">Alpha</a><a href="https://beta.example">Beta</a>'
    alpha = ExternalLinkTargets("https://alpha.example").apply(source)
    beta = ExternalLinkTargets("https://beta.example").apply(source)
    assert '<a href="https://alpha.example">Alpha</a>' in alpha
    assert '<a href="https://beta.example">Beta</a>' in beta
    assert alpha != beta
    assert ExternalLinkTargets().apply(source) == source


def test_payload_preparation_handles_nested_acf_without_touching_source_or_metadata():
    source = '<a href="https://other.example">Guide</a>'
    original = {"wordpress": {"excerpt": source}, "acf": {"arbitrary_repeater_27": [{"body": source}]},
                "meta": {"literal_example": source}, "media": [{"caption": source}]}
    saved = deepcopy(original)
    result = PayloadBuilder("https://energy.example").prepare_payload(original)
    assert 'target="_blank"' in result["wordpress"]["excerpt"]
    assert 'target="_blank"' in result["acf"]["arbitrary_repeater_27"][0]["body"]
    assert result["meta"] == saved["meta"]
    assert result["media"] == saved["media"]
    assert original == saved


def test_payload_builder_applies_rule_after_configured_field_routing(tmp_path):
    _, session, snapshot = fixture(tmp_path)
    snapshot = snapshot.model_copy(update={"acf_fields": tuple(
        row.model_copy(update={"field_role": "direct_acf"}) for row in snapshot.acf_fields
    )})
    values = {"detail_x": '<p><a href="https://other.example">Guide</a></p>',
              "detail_y": '<a href="https://energy.example/page">Internal</a>'}
    payload = PayloadBuilder("https://energy.example").build(
        snapshot, post_type_key=session.post_type_key, shared_values=session.shared_fields, acf_source_values=values,
    )
    assert 'target="_blank" rel="noopener"' in payload.acf["wp_detail_x"]
    assert payload.acf["wp_detail_y"] == values["detail_y"]
    assert 'target="_blank"' not in values["detail_x"]


def test_existing_post_can_update_only_link_attributes_and_then_becomes_synced(tmp_path):
    existing, session, snapshot = fixture(tmp_path)
    states = tuple(ApplicationState(sheet_row=2, state=state, terminal=False,
                                    allowed_next_states=next_states, entered_when_de="", ui_behavior_de="")
                   for state, next_states in (("publishing", ("published",)), ("published", ("publishing",))))
    snapshot = snapshot.model_copy(update={"application_states": (*snapshot.application_states, *states)})
    class WordPressStub:
        def __init__(self): self.calls = []
        def publish(self, **kwargs):
            self.calls.append(kwargs)
            return {"post_id": 42, "status": "draft"}
    provider = WordPressStub()
    service = ContentSessionService(
        knowledge=existing.knowledge, repository=existing.repository, wordpress=provider,
        wordpress_site_url="https://energy.example",
    )
    from types import SimpleNamespace
    service.knowledge = SimpleNamespace(by_hash=lambda _: snapshot, current=lambda: snapshot)
    payload = WordPressPayload.model_validate({
        "wordpress": {"title": "Battery case", "status": "draft"},
        "acf": {"wp_detail_x": '<a href="https://other.example">Guide</a>'},
    }).model_dump()
    session = service.repository.save(session.model_copy(update={
        "state": "published", "wordpress_payload": deepcopy(payload),
        "published_wordpress_payload": deepcopy(payload), "wordpress_result": {"post_id": 42},
    }), expected_version=session.version)
    loaded = service.get(session.session_id)
    assert 'target="_blank"' in loaded.wordpress_payload["acf"]["wp_detail_x"]
    assert loaded.version == session.version
    assert service.repository.get(session.session_id).wordpress_payload == payload
    published = service.publish(session.session_id, idempotency_key="external-link-policy", expected_version=session.version,
                                target_post_id=42, partial_update=True)
    assert len(provider.calls) == 1
    assert "wp_detail_x" in provider.calls[0]["partial_update_fields"]["acf"]
    assert 'target="_blank"' in provider.calls[0]["payload"].acf["wp_detail_x"]
    assert published.acf_source_fields == session.acf_source_fields
    assert published.published_wordpress_payload == service.get(session.session_id).wordpress_payload
    service.publish(session.session_id, idempotency_key="same-post-again", expected_version=published.version,
                    target_post_id=42, partial_update=True)
    assert len(provider.calls) == 1
