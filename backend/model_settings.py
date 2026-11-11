"""Shared model choices and compatibility for saved sessions/configuration."""
from typing import Literal

LanguageModel = Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]

_MODEL_REPLACEMENTS = {
    "gpt-5": "gpt-5.6-sol",
    "gpt-5-2025-08-07": "gpt-5.6-sol",
    "gpt-5.5": "gpt-5.6-sol",
    "gpt-5.5-2026-04-23": "gpt-5.6-sol",
    "gpt-5.6": "gpt-5.6-sol",
    "gpt-5-mini": "gpt-5.6-terra",
    "gpt-5-mini-2025-08-07": "gpt-5.6-terra",
}


def resolve_model(model: str | None) -> str | None:
    return _MODEL_REPLACEMENTS.get(model, model)


def resolve_reasoning_effort(effort: str | None) -> str | None:
    # The replacements no longer accept the legacy minimal effort.
    return "low" if effort == "minimal" else effort
