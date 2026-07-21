from app.v2.content_generation.step_01_schema_factory import (
    _effective_maximum_words,
    _effective_minimum_words,
)
from app.v2.validation.step_01_draft import DraftValidator


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
