from __future__ import annotations

import json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from app.v2.errors import SessionNotFoundError, SessionVersionConflictError
from app.v2.models.step_01_session import ContentSession


class SessionRepository(ABC):
    @abstractmethod
    def create(self, session: ContentSession) -> ContentSession: ...

    @abstractmethod
    def get(self, session_id: str) -> ContentSession: ...

    @abstractmethod
    def save(self, session: ContentSession, *, expected_version: int) -> ContentSession: ...

    @abstractmethod
    def list(self) -> list[ContentSession]: ...

    @abstractmethod
    def delete(self, session_id: str) -> bool: ...


class FileSessionRepository(SessionRepository):
    """Atomic JSON repository; replaceable by GCS or database adapters."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, session: ContentSession) -> ContentSession:
        path = self._path(session.session_id)
        if path.exists():
            raise SessionVersionConflictError(f"Session already exists: {session.session_id}")
        self._write(path, session)
        return session

    def get(self, session_id: str) -> ContentSession:
        path = self._path(session_id)
        if not path.is_file():
            raise SessionNotFoundError(f"V2 session not found: {session_id}")
        return ContentSession.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, session: ContentSession, *, expected_version: int) -> ContentSession:
        current = self.get(session.session_id)
        if current.version != expected_version:
            raise SessionVersionConflictError(
                f"Session {session.session_id} changed from version "
                f"{expected_version} to {current.version}."
            )
        updated = session.model_copy(update={"version": expected_version + 1})
        self._write(self._path(session.session_id), updated)
        return updated

    def list(self) -> list[ContentSession]:
        sessions: list[ContentSession] = []
        for path in self.root.glob("*/state.json"):
            if not path.is_file():
                continue
            try:
                sessions.append(ContentSession.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sessions

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        shutil.rmtree(path.parent)
        return True

    def _path(self, session_id: str) -> Path:
        safe_id = Path(session_id).name
        if safe_id != session_id or not safe_id:
            raise SessionNotFoundError("Invalid session identifier.")
        return self.root / safe_id / "state.json"

    @staticmethod
    def _write(path: Path, session: ContentSession) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(session.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
