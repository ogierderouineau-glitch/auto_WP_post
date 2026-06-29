from __future__ import annotations

from pathlib import Path
from threading import RLock

from app.v2.knowledge_base.step_01_models import WorkbookSnapshot
from app.v2.knowledge_base.step_02_loader import WorkbookLoader
from app.v2.knowledge_base.step_03_validator import WorkbookValidator


class KnowledgeBaseService:
    """Own validated immutable workbook snapshots for new V2 sessions."""

    def __init__(self, workbook_path: str | Path) -> None:
        self.workbook_path = Path(workbook_path)
        self._loader = WorkbookLoader()
        self._validator = WorkbookValidator()
        self._snapshots: dict[str, WorkbookSnapshot] = {}
        self._current_hash: str | None = None
        self._lock = RLock()

    def current(self) -> WorkbookSnapshot:
        with self._lock:
            if self._current_hash is not None:
                return self._snapshots[self._current_hash]
        return self.reload()

    def reload(self) -> WorkbookSnapshot:
        snapshot = self._validator.validate(self._loader.load(self.workbook_path))
        with self._lock:
            self._snapshots[snapshot.version.sha256] = snapshot
            self._current_hash = snapshot.version.sha256
        return snapshot

    def by_hash(self, workbook_hash: str) -> WorkbookSnapshot:
        with self._lock:
            snapshot = self._snapshots.get(workbook_hash)
        if snapshot is None:
            current = self.current()
            if current.version.sha256 == workbook_hash:
                return current
        if snapshot is None:
            raise KeyError(f"Workbook snapshot is not loaded: {workbook_hash}")
        return snapshot
