from __future__ import annotations

import json
from typing import Any


def structured_task_input(
    *,
    task: str,
    instructions: list[dict[str, Any]],
    context: dict[str, Any],
    validation_feedback: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Create neutral transport text from workbook-filtered context.

    Business rules and writing instructions come from the workbook context.
    The code adds only task framing and structured-output boundaries.
    """

    system = {
        "task": task,
        "rules": [row.get("instruction_de") for row in instructions],
        "constraints": [
            "Return only values allowed by the supplied response schema.",
            "Do not invent facts, URLs, identities, destinations, or field keys.",
        ],
    }
    if task in {"image_metadata", "image_metadata_batch"}:
        system["constraints"].extend(
            [
                "Treat image_context_transcript as the primary description of the selected picture.",
                "Use only transcript statements that describe the picture; ignore surrounding event, article, or logistical context unless a supplied workbook rule explicitly requires it.",
                "Use image_analysis only when it is present and do not invent visible details.",
                "Use approved_context_facts only when they are relevant to what image_context_transcript says this selected picture shows.",
                "If context.must_use_when_natural contains matching rules with confirmed_source_facts, apply those workbook rules in the target fields whenever the wording remains natural.",
                "When image_analysis is absent, apply a transcript_match_rule only if image_context_transcript clearly establishes the subject or action described by that rule; then use its confirmed_source_facts naturally in its target fields.",
                "For German human-readable metadata, use standard German Unicode orthography, including ä, ö, ü, Ä, Ö, Ü, and ß where linguistically correct; do not transliterate umlauts as ae, oe, or ue, or ß as ss. Technical filename/slug fields are exempt.",
            ]
        )
    user = {
        "context": context,
        "validation_feedback": validation_feedback or [],
    }
    return [
        {"role": "system", "content": json.dumps(system, ensure_ascii=False)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ]
