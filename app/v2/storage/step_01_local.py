from __future__ import annotations

import os
import tempfile
import shutil
from pathlib import Path

from app.v2.providers.step_01_interfaces import ObjectStorageProvider


class LocalObjectStorageProvider(ObjectStorageProvider):
    """Local development storage with atomic writes and traversal protection."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, source: Path, key: str) -> str:
        destination = (self.root / key).resolve()
        if self.root not in destination.parents:
            raise ValueError("Object-storage key escapes the configured root.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".upload-",
            suffix=destination.suffix,
            dir=destination.parent,
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(source.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return str(destination)

    def get(self, uri: str, destination: Path) -> Path:
        source = Path(uri).resolve()
        if self.root not in source.parents:
            raise ValueError("Object URI is outside the configured local root.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return destination
