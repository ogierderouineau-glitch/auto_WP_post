from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from backend.app.context.step_01_builder import GenerationContextBuilder
from backend.app.knowledge_base.step_01_models import PostExample
from backend.app.knowledge_base.step_02_loader import WorkbookLoader
from backend.app.models.step_01_session import ContentSession, FactValue


def example(example_id, tags="", quality=5, **overrides):
    return PostExample(
        sheet_row=2, example_id=example_id, post_type_key="event", enabled=True,
        approved=True, quality_score=quality, retrieval_tags=tuple(tags.split(";")),
        example_content="hero_intro: Approved copy", **overrides,
    )


def build(examples, *, tags=(), facts=None, task="generation", post_type_key="event"):
    snapshot = SimpleNamespace(
        post_type=lambda key: SimpleNamespace(model_dump=lambda **kwargs: {"post_type_key": key}),
        shared_fields=(), acf_fields=(), blueprint=(), agent_instructions=(),
        story_patterns=(), post_examples=examples,
    )
    session = ContentSession(
        session_id="test", user_id="test", post_type_key=post_type_key, state="draft",
        workbook_hash="test", language="de-DE", context_tags=set(tags),
        confirmed_facts=facts or {}, manual_text="festival", transcript="festival",
    )
    return GenerationContextBuilder().build(
        snapshot=snapshot, task=task, post_type_key=post_type_key, session=session,
    ).examples


def test_loader_reads_new_columns_and_semicolon_separated_tags():
    sheet = Workbook().active
    sheet.title = "post_examples"
    sheet.append(["post_type_key", "example_id", "enabled", "approved", "quality_score",
                  "input_facts_text", "post_title", "example_content", "learning_for_gpt",
                  "retrieval_tags", "url"])
    sheet.append(["event", 1, True, True, 5, "Location: Hotel", "Hotel event",
                  "hero_intro: Text", "Discreet service", " Hotel; luxury; ", None])
    row, = WorkbookLoader()._models(sheet, PostExample)
    assert row.example_id == "1"
    assert row.retrieval_tags == ("Hotel", "luxury")
    assert row.example_content == "hero_intro: Text"


def test_relevance_beats_quality_and_matches_descriptive_tags():
    selected = build(
        [example("festival", "Festival", quality=5),
         example("hotel", "private Luxus-Veranstaltung / Hotel-Event", quality=4)],
        tags=["luxury_hotel"],
    )
    assert selected[0]["example_id"] == "hotel"


def test_selection_supports_unrelated_industries_and_arbitrary_post_types():
    examples = [
        example("sensor", "industrial sensor", 4),
        example("medicine", "clinical research", 5),
    ]
    examples = [row.model_copy(update={"post_type_key": "product_guide"}) for row in examples]
    selected = build(examples, tags=["industrial_sensor"], post_type_key="product_guide")
    assert selected[0]["example_id"] == "sensor"


def test_confirmed_facts_are_used_but_raw_text_and_unconfirmed_facts_are_not():
    facts = {
        "venue": FactValue(value="Hotel", source="manual_text", confidence=1, confirmed=True),
        "other": FactValue(value="Festival", source="manual_text", confidence=1),
    }
    assert build([example("festival", "festival"), example("hotel", "hotel")],
                 facts=facts)[0]["example_id"] == "hotel"


@pytest.mark.parametrize("tags", [(), ("hotel",)])
def test_quality_breaks_relevance_ties_and_provides_no_match_fallback(tags):
    selected = build([example("low", "hotel", 3), example("high", "hotel", 5)], tags=tags)
    assert selected[0]["example_id"] == "high"


def test_ties_are_stable_and_duplicate_words_do_not_inflate_relevance():
    selected = build([example("b", "hotel;hotel hotel"), example("a", "hotel")], tags=["hotel"])
    assert selected[0]["example_id"] == "a"


def test_ineligible_examples_are_filtered_and_legacy_extras_are_not_sent():
    valid = example("valid", "hotel", featured_image_alt_or_caption="Unrelated photo")
    others = [valid.model_copy(update=changes) for changes in [
        {"example_id": "disabled", "enabled": False, "quality_score": 10},
        {"example_id": "unapproved", "approved": False, "quality_score": 10},
        {"example_id": "cocktail", "post_type_key": "cocktail", "quality_score": 10},
    ]]
    selected = build([*others, valid], tags=["hotel"])
    assert selected[0]["example_id"] == "valid"
    assert "featured_image_alt_or_caption" not in selected[0]
    assert build(others) == []


@pytest.mark.parametrize("task", ["image_metadata", "image_metadata_batch", "analysis"])
def test_post_examples_are_excluded_from_other_tasks(task):
    assert build([example("event")], task=task) == []
