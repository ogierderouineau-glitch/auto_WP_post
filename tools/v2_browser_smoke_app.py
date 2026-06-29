from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("CONTENT_PIPELINE_VERSION", "v2")
os.environ.setdefault("IMPORT_API_KEY", "browser-smoke-key")

import app.v2.api.step_03_container as container
from app.v2.knowledge_base.step_04_service import KnowledgeBaseService
from app.v2.providers.step_01_interfaces import LanguageModelProvider
from app.v2.sessions.step_01_repository import FileSessionRepository
from app.v2.sessions.step_03_service import ContentSessionService
from app.v2.storage.step_01_local import LocalObjectStorageProvider


class BrowserSmokeLanguageModel(LanguageModelProvider):
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot

    def structured(self, *, task: str, context: dict[str, Any], schema: type[Any]) -> Any:
        if task == "fact_extraction":
            data = {
                row.field_key: (
                    self._value(
                        row.value_type,
                        getattr(row, "min_words", None),
                        getattr(row, "max_characters", None),
                        field_key=row.field_key,
                    )
                    if row.required_for_analysis and row.field_key != "venue"
                    else None
                )
                for row in self.snapshot.acf_fields
                if row.enabled
                and row.post_type_key == "event"
                and row.field_role == "input_fact"
            }
        elif task == "shared_field_generation":
            data = {
                row.field_key: (
                    self._value(
                        row.value_type,
                        getattr(row, "min_words", None),
                        getattr(row, "max_characters", None),
                        field_key=row.field_key,
                    )
                    if row.required_for_output
                    else None
                )
                for row in self.snapshot.shared_fields
                if row.enabled and row.include_in_ai_schema
            }
        elif task == "acf_field_generation":
            allowed = set(schema.model_fields)
            data = {
                row.field_key: (
                    self._value(
                        row.value_type,
                        getattr(row, "min_words", None),
                        getattr(row, "max_characters", None),
                        field_key=row.field_key,
                    )
                    if row.required_for_output
                    else None
                )
                for row in self.snapshot.acf_fields
                if row.enabled
                and row.post_type_key == "event"
                and row.field_role != "input_fact"
                and row.include_in_ai_schema
                and row.field_key in allowed
            }
        elif task == "internal_link_ranking":
            user = json.loads(context["messages"][1]["content"])
            data = {
                "selections": [
                    {
                        "link_id": item["link_id"],
                        "anchor_text": item["anchor_text"],
                    }
                    for item in user["context"]["candidates"][:2]
                ]
            }
        else:
            raise AssertionError(f"Unexpected browser-smoke task: {task}")
        return schema.model_validate(data)

    @staticmethod
    def _value(
        value_type: str,
        minimum_words: int | None,
        maximum_characters: int | None,
        *,
        field_key: str,
    ) -> Any:
        exact = {
            "event_year": 2026,
            "event_month": "Juni",
            "event_date": "2026-06-24",
            "city": "Berlin",
            "venue": "Musterlocation Berlin",
            "event_type": "Firmen-Sommerfest",
            "client_type": "company",
            "guest_count": 120,
            "service_type": "Cocktailcatering",
            "status": "draft",
            "category": "auto event post",
        }
        if field_key in exact:
            return exact[field_key]
        if value_type == "integer":
            return 2026
        if value_type == "float":
            return 1.0
        if value_type == "boolean":
            return True
        if value_type == "list":
            return ["Berlin"]
        if value_type == "date":
            return "24.06.2026"
        if value_type == "enum":
            return "company"
        text = " ".join(["Testinhalt"] * max(minimum_words or 1, 1))
        if maximum_characters is not None:
            text = text[:maximum_characters].rstrip()
        return text


root = Path(os.getenv("V2_BROWSER_SMOKE_ROOT", "/tmp/flairlab-v2-browser-smoke"))
workbook = Path(
    os.getenv(
        "V2_KNOWLEDGE_WORKBOOK_PATH",
        "data/knowledge/FLAIRLAB_Knowledge_Base_Revised_V5.xlsm",
    )
)
knowledge = KnowledgeBaseService(workbook)
snapshot = knowledge.current()
container._service = ContentSessionService(
    knowledge=knowledge,
    repository=FileSessionRepository(root / "sessions"),
    language_model=BrowserSmokeLanguageModel(snapshot),
    object_storage=LocalObjectStorageProvider(root / "objects"),
)

from app_main import app

__all__ = ["app"]
