from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.v2.models.step_01_session import ContentSession
from app.v2.models.step_02_payload import WordPressPayload


class SpeechToTextProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path) -> str: ...


class LanguageModelProvider(ABC):
    @abstractmethod
    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any: ...


class VisionProvider(ABC):
    @abstractmethod
    def analyze(
        self,
        image_path: Path,
        schema: type[Any],
        context: dict[str, Any],
    ) -> Any: ...


class ImageEditingProvider(ABC):
    @abstractmethod
    def edit(self, source: Path, destination: Path, instructions: dict[str, Any]) -> Path: ...


class ObjectStorageProvider(ABC):
    @abstractmethod
    def put(self, source: Path, key: str) -> str: ...

    @abstractmethod
    def get(self, uri: str, destination: Path) -> Path: ...


class WordPressProvider(ABC):
    @abstractmethod
    def publish(
        self,
        *,
        session: ContentSession,
        payload: WordPressPayload,
        idempotency_key: str,
        target_post_id: int | None = None,
        force_create_new: bool = False,
    ) -> dict[str, Any]: ...
