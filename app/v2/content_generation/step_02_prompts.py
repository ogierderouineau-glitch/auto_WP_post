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
    user = {
        "context": context,
        "validation_feedback": validation_feedback or [],
    }
    return [
        {"role": "system", "content": json.dumps(system, ensure_ascii=False)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ]
