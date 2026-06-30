from __future__ import annotations

from typing import Any

from app.v2.errors import DraftValidationError, ErrorDetail
from app.v2.knowledge_base.step_01_models import WorkbookSnapshot
from app.v2.models.step_01_session import ContentSession
from app.v2.workflow.step_04_generation_conditions import (
    GenerationConditionEvaluator,
    source_fact_dependencies_are_available,
)


class DraftValidator:
    def validate(
        self,
        snapshot: WorkbookSnapshot,
        *,
        post_type_key: str,
        shared_values: dict[str, Any],
        acf_source_values: dict[str, Any],
        no_eligible_links: bool = False,
        session: ContentSession | None = None,
    ) -> dict[str, Any]:
        errors: list[ErrorDetail] = []
        for row in snapshot.shared_fields:
            if not row.enabled:
                continue
            value = shared_values.get(row.field_key)
            allow_empty_links = (
                row.validation_rule == "allow_empty_if_no_eligible_links"
                and no_eligible_links
            )
            if row.required_for_output and self._empty(value) and not allow_empty_links:
                errors.append(self._detail(
                    "shared_fields_schema",
                    row.sheet_row,
                    row.field_key,
                    "missing_required_field",
                    "Required shared field is empty.",
                ))
            self._limits(errors, "shared_fields_schema", row.sheet_row, row.field_key, value,
                         row.min_words, row.max_words, row.min_characters, row.max_characters)
        for row in snapshot.acf_fields:
            if not row.enabled or row.post_type_key != post_type_key or row.field_role == "input_fact":
                continue
            if session is not None and not self._acf_field_is_eligible(row, session):
                continue
            value = acf_source_values.get(row.field_key)
            if row.required_for_output and self._empty(value):
                errors.append(self._detail(
                    "ACF_fields_schema",
                    row.sheet_row,
                    row.field_key,
                    "missing_required_field",
                    "Required ACF source field is empty.",
                ))
            self._limits(errors, "ACF_fields_schema", row.sheet_row, row.field_key, value,
                         row.min_words, row.max_words, None, None)
        if errors:
            raise DraftValidationError(
                f"Draft validation failed with {len(errors)} error(s).",
                details=errors,
            )
        return {"valid": True, "errors": []}

    @staticmethod
    def _acf_field_is_eligible(row: Any, session: ContentSession) -> bool:
        if not source_fact_dependencies_are_available(row, session):
            return False
        return GenerationConditionEvaluator().evaluate(
            row.generation_condition,
            session=session,
        )

    @staticmethod
    def _empty(value: Any) -> bool:
        return value is None or value == "" or value == []

    @staticmethod
    def _limits(
        errors: list[ErrorDetail],
        sheet: str,
        row: int,
        field_key: str,
        value: Any,
        min_words: int | None,
        max_words: int | None,
        min_characters: int | None,
        max_characters: int | None,
    ) -> None:
        if value is None or not isinstance(value, str):
            return
        word_count = len(value.split())
        if min_words is not None and word_count < min_words:
            errors.append(DraftValidator._detail(
                sheet, row, field_key, "minimum_words_not_met",
                f"Expected at least {min_words} words; received {word_count}.",
            ))
        if max_words is not None and word_count > max_words:
            errors.append(DraftValidator._detail(
                sheet, row, field_key, "maximum_words_exceeded",
                f"Expected at most {max_words} words; received {word_count}.",
            ))
        if min_characters is not None and len(value) < min_characters:
            errors.append(DraftValidator._detail(
                sheet, row, field_key, "minimum_characters_not_met",
                f"Expected at least {min_characters} characters; received {len(value)}.",
            ))
        if max_characters is not None and len(value) > max_characters:
            errors.append(DraftValidator._detail(
                sheet, row, field_key, "maximum_characters_exceeded",
                f"Expected at most {max_characters} characters; received {len(value)}.",
            ))

    @staticmethod
    def _detail(
        sheet: str,
        row: int,
        field_key: str,
        error_code: str,
        message: str,
    ) -> ErrorDetail:
        return ErrorDetail(
            sheet=sheet,
            row=row,
            column=field_key,
            error_code=error_code,
            message=message,
        )
