from __future__ import annotations

from backend.app.errors import InvalidStateTransitionError
from backend.app.knowledge_base.step_01_models import WorkbookSnapshot
from backend.app.models.step_01_session import ContentSession


class SessionStateMachine:
    def __init__(self, snapshot: WorkbookSnapshot) -> None:
        self._states = {row.state: row for row in snapshot.application_states}

    def transition(self, session: ContentSession, target_state: str) -> ContentSession:
        current = self._states.get(session.state)
        if current is None or target_state not in current.allowed_next_states:
            raise InvalidStateTransitionError(
                f"Cannot transition session from {session.state!r} to {target_state!r}."
            )
        return session.model_copy(update={"state": target_state})
