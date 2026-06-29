from __future__ import annotations

from collections.abc import Callable

from app.v2.models.step_01_session import ContentSession

ConditionHandler = Callable[[ContentSession], bool]

CONDITION_HANDLERS: dict[str, ConditionHandler] = {
    "always": lambda session: True,
    "audio_count_gt_0": lambda session: bool(session.audio_refs),
    "image_count_gt_0": lambda session: bool(session.image_refs),
}


def condition_matches(condition: str, session: ContentSession) -> bool:
    try:
        handler = CONDITION_HANDLERS[condition]
    except KeyError as exc:
        raise ValueError(f"Unknown V2 condition: {condition}") from exc
    return handler(session)
