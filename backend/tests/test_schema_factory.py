from types import SimpleNamespace

from backend.app.content_generation.step_01_schema_factory import (
    _effective_maximum_words,
    _effective_minimum_words,
    build_fact_extraction_model,
    build_image_metadata_batch_model,
)
from backend.app.validation.step_01_draft import DraftValidator


def test_image_metadata_taxonomy_terms_are_limited_to_exact_candidates() -> None:
    model = build_image_metadata_batch_model(
        [],
        media_ids=("image-1",),
        taxonomy_candidates={
            "cocktails": ("Mojito", "Negroni"),
            "barkeeper": ("Florent",),
        },
    )

    result = model.model_validate({
        "images": [{
            "media_id": "image-1",
            "visible_taxonomy_terms": {
                "cocktails": ["Mojito"],
                "barkeeper": [],
            },
        }],
    })

    assert result.images[0].visible_taxonomy_terms.cocktails == ["Mojito"]


def test_minimum_word_tolerance_rounds_up() -> None:
    assert _effective_minimum_words(70) == 56
    assert _effective_minimum_words(75) == 60


def test_maximum_word_tolerance_rounds_down() -> None:
    assert _effective_maximum_words(80) == 96
    assert _effective_maximum_words(83) == 99


def test_final_draft_validation_uses_the_same_minimum_tolerance() -> None:
    accepted_errors = []
    accepted_warnings = []
    DraftValidator._limits(
        accepted_errors, accepted_warnings, "sheet", 1, "hero_intro", "word " * 56, 70, 80, None, None,
    )
    assert accepted_errors == []
    assert accepted_warnings == []

    rejected_errors = []
    rejected_warnings = []
    DraftValidator._limits(
        rejected_errors, rejected_warnings, "sheet", 1, "hero_intro", "word " * 55, 70, 80, None, None,
    )
    assert rejected_errors == []
    assert rejected_warnings[0].error_code == "minimum_words_not_met"


def test_final_draft_validation_uses_the_same_maximum_tolerance() -> None:
    accepted_errors = []
    accepted_warnings = []
    DraftValidator._limits(
        accepted_errors, accepted_warnings, "sheet", 1, "hero_intro", "word " * 96, 70, 80, None, None,
    )
    assert accepted_errors == []
    assert accepted_warnings == []

    rejected_errors = []
    rejected_warnings = []
    DraftValidator._limits(
        rejected_errors, rejected_warnings, "sheet", 1, "hero_intro", "word " * 97, 70, 80, None, None,
    )
    assert rejected_errors == []
    assert rejected_warnings[0].error_code == "maximum_words_exceeded"


def test_word_limit_warning_is_serialized_in_non_blocking_report() -> None:
    row = SimpleNamespace(
        enabled=True,
        field_key="hero_intro",
        validation_rule=None,
        required_for_output=False,
        sheet_row=3,
        min_words=70,
        max_words=80,
        min_characters=None,
        max_characters=None,
    )
    snapshot = SimpleNamespace(shared_fields=[row], acf_fields=[])

    report = DraftValidator().validate(
        snapshot,
        post_type_key="event",
        shared_values={"hero_intro": "Too short"},
        acf_source_values={},
    )

    assert report["valid"] is True
    assert report["errors"] == []
    assert report["warnings"][0]["error_code"] == "minimum_words_not_met"


def test_publish_time_derived_acf_is_not_required_in_content_draft() -> None:
    row = SimpleNamespace(
        enabled=True,
        post_type_key="event",
        field_role="direct_acf",
        field_key="event_video_upload",
        generation_stage="payload_construction",
        source_mode="derived",
        required_for_output=True,
        sheet_row=4,
        min_words=None,
        max_words=None,
    )
    snapshot = SimpleNamespace(shared_fields=[], acf_fields=[row])

    report = DraftValidator().validate(
        snapshot,
        post_type_key="event",
        shared_values={},
        acf_source_values={},
    )

    assert report == {"valid": True, "errors": [], "warnings": []}


def _fact_row(key: str, value_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        field_key=key, field_role="input_fact", enabled=True, value_type=value_type,
        description_de="", format_or_enum=None, min_words=None, max_words=None,
    )


def test_taxonomy_backed_facts_accept_only_existing_terms() -> None:
    # Unrelated industry on purpose: nothing here depends on one client's taxonomies.
    model = build_fact_extraction_model(
        [_fact_row("dish_types", "list"), _fact_row("chef", "string"), _fact_row("notes", "string")],
        term_choices={"dish_types": ("Risotto", "Tiramisu"), "chef": ("Anna",)},
    )

    ok = model.model_validate({"dish_types": ["Risotto"], "chef": "Anna", "notes": "free text"})
    assert ok.dish_types == ["Risotto"]
    for bad in ({"dish_types": ["Pizza"]}, {"chef": "Bob"}):
        try:
            model.model_validate(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} should have been rejected")


def test_fact_extraction_without_term_choices_stays_free_text() -> None:
    model = build_fact_extraction_model([_fact_row("dish_types", "list")])
    assert model.model_validate({"dish_types": ["anything"]}).dish_types == ["anything"]


def _choices(wordpress, snapshot_taxonomies):
    from backend.app.sessions.step_03_service import ContentSessionService  # noqa: PLC0415

    service = SimpleNamespace(wordpress=wordpress, _milestone=lambda *a: None)
    session = SimpleNamespace(post_type_key="recipe")
    snapshot = SimpleNamespace(taxonomies=snapshot_taxonomies)
    rows = [_fact_row("dish_types", "list")]
    return ContentSessionService._fact_term_choices(service, snapshot, session, rows)


def test_fact_term_choices_use_taxonomies_tab_and_fall_back_when_wordpress_fails() -> None:
    taxonomy = SimpleNamespace(post_type_key="recipe", wp_taxonomy="dish", taxonomy_term_source="acf:dish_types")
    other_type = SimpleNamespace(post_type_key="event", wp_taxonomy="dish", taxonomy_term_source="acf:dish_types")

    class Working:
        def taxonomy_term_names(self, name): return ["Risotto", "Risotto", "Tiramisu"]

    class Broken:
        def taxonomy_term_names(self, name): raise RuntimeError("site down")

    assert _choices(Working(), [taxonomy, other_type]) == {"dish_types": ("Risotto", "Tiramisu")}
    assert _choices(Broken(), [taxonomy]) == {}
    assert _choices(None, [taxonomy]) == {}
