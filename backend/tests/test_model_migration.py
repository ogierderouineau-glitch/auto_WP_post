from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from backend.app.api.step_01_models import GenerationSettingsRequest
from backend.app.models.step_01_session import ContentSession
from backend.app.providers.step_02_openai import (
    OpenAILanguageModelProvider, OpenAIVisionProvider, _estimate_cost_usd,
)
from backend.model_settings import resolve_model


@pytest.mark.parametrize("old,new", [
    ("gpt-5", "gpt-5.6-sol"),
    ("gpt-5-2025-08-07", "gpt-5.6-sol"),
    ("gpt-5.5", "gpt-5.6-sol"),
    ("gpt-5.5-2026-04-23", "gpt-5.6-sol"),
    ("gpt-5.6", "gpt-5.6-sol"),
    ("gpt-5-mini", "gpt-5.6-terra"),
    ("gpt-5-mini-2025-08-07", "gpt-5.6-terra"),
])
def test_legacy_settings_and_saved_sessions_migrate(old, new):
    settings = GenerationSettingsRequest(
        expected_version=1, language_model=old, reasoning_effort="minimal",
    )
    assert (settings.language_model, settings.reasoning_effort) == (new, "low")
    session = ContentSession.model_validate(dict(
        session_id="legacy", user_id="user", post_type_key="arbitrary_type",
        state="created", workbook_hash="hash", language="en",
        language_model=old, reasoning_effort="minimal",
    ))
    assert (session.language_model, session.reasoning_effort) == (new, "low")


def test_providers_send_replacement_without_changing_structured_request():
    client = Mock()
    schema = Mock()
    client.responses.parse.return_value = SimpleNamespace(output_parsed={"ok": True}, usage=None)
    with patch("backend.app.providers.step_02_openai.OpenAI", return_value=client):
        provider = OpenAILanguageModelProvider(api_key="test", model="gpt-5-mini", reasoning_effort="minimal")
        provider.structured(task="test", context={"messages": []}, schema=schema)
        client.responses.parse.assert_called_once_with(
            model="gpt-5.6-terra", input=[], text_format=schema, reasoning={"effort": "low"},
        )
        assert OpenAIVisionProvider(api_key="test", model="gpt-5-mini").model == "gpt-5.6-terra"
    assert resolve_model("custom-model") == "custom-model"
    assert resolve_model(None) is None


def test_costs_do_not_use_generic_gpt5_prices_for_unknown_models():
    assert _estimate_cost_usd("gpt-5.6-terra", 1000, 1000) == 0.014
    assert _estimate_cost_usd("gpt-5-mini", 1000, 1000) == 0.00225
    assert _estimate_cost_usd("gpt-5.6-unknown", 1000, 1000) is None
    assert _estimate_cost_usd("gpt-5.6-terra", 300000, 1000) == 1.218


def test_current_effort_and_model_choices_remain_validated():
    from pydantic import ValidationError

    settings = GenerationSettingsRequest(
        expected_version=1, language_model="gpt-5.6-terra", reasoning_effort="none",
    )
    assert settings.reasoning_effort == "none"
    with pytest.raises(ValidationError):
        GenerationSettingsRequest(
            expected_version=1, language_model="unconfigured-model", reasoning_effort="low",
        )
