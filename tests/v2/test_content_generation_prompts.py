from __future__ import annotations

import json

from app.v2.content_generation.step_02_prompts import structured_task_input


def _system_prompt(task: str, policy: str) -> dict[str, object]:
    messages = structured_task_input(
        task=task,
        instructions=[{"instruction_de": "Fill every required field."}],
        context={
            "post_type": {
                "post_type_key": "cocktail",
                "knowledge_enrichment": policy,
            }
        },
    )
    return json.loads(messages[0]["content"])


def test_allowed_policy_enables_knowledge_for_generated_content() -> None:
    system = _system_prompt("content_generation", "allowed")

    assert system["knowledge_enrichment"] == "allowed"
    assert any(
        "established general knowledge" in constraint
        for constraint in system["constraints"]
    )
    assert any(
        "Never use that knowledge to create input facts" in constraint
        for constraint in system["constraints"]
    )


def test_allowed_policy_applies_to_acf_generation_batches() -> None:
    system = _system_prompt("acf_field_generation:story", "allowed")

    assert system["knowledge_enrichment"] == "allowed"


def test_allowed_policy_never_enriches_fact_extraction() -> None:
    system = _system_prompt("fact_extraction", "allowed")

    assert system["knowledge_enrichment"] == "forbidden"
    assert "Do not invent facts" in " ".join(system["constraints"])


def test_forbidden_policy_keeps_generated_content_evidence_bound() -> None:
    system = _system_prompt("content_generation", "forbidden")

    assert system["knowledge_enrichment"] == "forbidden"
    assert "Do not invent facts" in " ".join(system["constraints"])
