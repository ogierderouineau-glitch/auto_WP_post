from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, create_model

from app.v2.knowledge_base.step_01_models import (
    ACFFieldSchema,
    ImageAnalysisRule,
    ImageMetadataField,
    SharedFieldSchema,
)


class NormalizedFocalPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0, le=1)
    y: float = Field(..., ge=0, le=1)


class BooleanWithReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: bool
    reason: str


def _python_type(value_type: str, enum_values: tuple[Any, ...] = ()) -> Any:
    if value_type == "enum" and enum_values:
        return Literal.__getitem__(enum_values)
    return {
        "string": str,
        "integer": int,
        "float": float,
        "boolean": bool,
        "list": list[str],
        "date": str,
        "json": dict[str, Any],
        "ratio": str,
        "enum": str,
    }.get(value_type, str)


def _field_definition(
    schema: SharedFieldSchema | ACFFieldSchema,
    *,
    required: bool,
    enum_values: tuple[Any, ...] = (),
) -> tuple[type[Any], Field]:
    annotation = _python_type(schema.value_type, enum_values)
    if not required:
        annotation = annotation | None
    description_parts = [schema.description_de]
    if getattr(schema, "min_words", None) is not None:
        description_parts.append(f"Minimum {schema.min_words} words.")
    if getattr(schema, "max_words", None) is not None:
        description_parts.append(f"Maximum {schema.max_words} words.")
    if getattr(schema, "min_characters", None) is not None:
        description_parts.append(f"Minimum {schema.min_characters} characters.")
    if getattr(schema, "max_characters", None) is not None:
        description_parts.append(f"Maximum {schema.max_characters} characters.")
    if schema.value_type == "date":
        description_parts.append("Use German numeric date format dd.MM.yyyy.")
    constraints: dict[str, Any] = {
        "description": " ".join(part for part in description_parts if part),
    }
    if schema.value_type == "string":
        if getattr(schema, "min_characters", None) is not None:
            constraints["min_length"] = schema.min_characters
        if getattr(schema, "max_characters", None) is not None:
            constraints["max_length"] = schema.max_characters
    # OpenAI strict structured outputs require every property to be present.
    # Optional workbook values are represented as required nullable properties.
    return annotation, Field(default=..., **constraints)


def build_fact_extraction_model(
    rows: list[ACFFieldSchema],
    *,
    name: str = "FactExtractionResponse",
    enum_families: dict[str, tuple[Any, ...]] | None = None,
) -> type[BaseModel]:
    enum_families = enum_families or {}
    fields = {
        row.field_key: _field_definition(
            row,
            required=False,
            enum_values=enum_families.get(row.format_or_enum or "", ()),
        )
        for row in rows
        if row.enabled and row.field_role == "input_fact"
    }
    return create_model(
        name,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def build_generation_model(
    rows: list[SharedFieldSchema | ACFFieldSchema],
    *,
    name: str,
    enum_families: dict[str, tuple[Any, ...]] | None = None,
) -> type[BaseModel]:
    enum_families = enum_families or {}
    limits = {
        row.field_key: (row.min_words, row.max_words)
        for row in rows
        if row.value_type == "string"
        and (row.min_words is not None or row.max_words is not None)
    }
    raw_aggregation_fields = {
        row.field_key
        for row in rows
        if isinstance(row, ACFFieldSchema)
        and row.field_role == "aggregation_source"
        and row.transform_key
    }

    class WordLimitModel(BaseModel):
        model_config = ConfigDict(extra="forbid")

        @model_validator(mode="after")
        def validate_word_limits(self) -> "WordLimitModel":
            for field_key, (minimum, maximum) in limits.items():
                value = getattr(self, field_key, None)
                if not value:
                    continue
                count = len(str(value).split())
                if minimum is not None and count < minimum:
                    raise ValueError(f"{field_key} requires at least {minimum} words; received {count}.")
                if maximum is not None and count > maximum:
                    raise ValueError(f"{field_key} allows at most {maximum} words; received {count}.")
            for field_key in raw_aggregation_fields:
                value = getattr(self, field_key, None)
                if isinstance(value, str) and ("<" in value or ">" in value):
                    raise ValueError(
                        f"{field_key} must contain raw source text without HTML; "
                        "Python applies the declared transform."
                    )
            return self

    fields = {
        row.field_key: _field_definition(
            row,
            required=bool(row.required_for_output),
            enum_values=enum_families.get(row.format_or_enum or "", ()),
        )
        for row in rows
        if row.enabled and row.include_in_ai_schema
    }
    return create_model(
        name,
        __base__=WordLimitModel,
        **fields,
    )


class LinkSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: str
    anchor_text: str


class LinkSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[LinkSelection] = Field(default_factory=list)


def build_image_analysis_model(
    rows: list[ImageAnalysisRule],
    *,
    enum_families: dict[str, tuple[Any, ...]],
) -> type[BaseModel]:
    type_map: dict[str, Any] = {
        "short_text": str,
        "integer_0_100": int,
        "normalized_focal_point_or_none": NormalizedFocalPoint | None,
        "float_or_zero": float,
        "short_text_or_none": str | None,
        "group_id_or_none": str | None,
        "boolean_with_reason": BooleanWithReason,
    }
    fields: dict[str, tuple[Any, Field]] = {}
    for row in rows:
        if not row.enabled:
            continue
        if row.output_domain and row.expected_output == "enum_list":
            annotation = list[Literal.__getitem__(enum_families[row.output_domain])]
        elif row.output_domain:
            annotation = Literal.__getitem__(enum_families[row.output_domain])
        else:
            annotation = type_map.get(row.expected_output, Any)
        constraints: dict[str, Any] = {"description": row.intent_de}
        if row.expected_output == "integer_0_100":
            constraints.update(ge=0, le=100)
        fields[row.analysis_key] = (annotation, Field(..., **constraints))
    return create_model(
        "ImageAnalysisResponse",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def build_image_metadata_model(
    rows: list[ImageMetadataField],
    *,
    enum_families: dict[str, tuple[Any, ...]],
) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Field]] = {}
    rules: dict[str, str] = {}
    for row in rows:
        if not row.enabled or row.source_mode not in {"generated", "generated_from_image_analysis"}:
            continue
        annotation: Any = _python_type(row.value_type)
        rule = row.validation_rule or ""
        if rule.startswith("enum:"):
            annotation = Literal.__getitem__(tuple(rule.removeprefix("enum:").split("|")))
        if not row.required:
            annotation = annotation | None
        fields[row.field_key] = (
            annotation,
            Field(..., description=row.description_de),
        )
        if row.validation_rule:
            rules[row.field_key] = row.validation_rule

    class ImageMetadataBase(BaseModel):
        model_config = ConfigDict(extra="forbid")

        @model_validator(mode="after")
        def validate_rules(self) -> "ImageMetadataBase":
            for field_key, rule in rules.items():
                value = getattr(self, field_key, None)
                if value is None:
                    continue
                if rule.startswith("max_words:"):
                    maximum = int(rule.split(":", 1)[1])
                    if len(str(value).split()) > maximum:
                        raise ValueError(f"{field_key} allows at most {maximum} words.")
                if rule.startswith("regex:") and not re.fullmatch(rule.removeprefix("regex:"), str(value)):
                    raise ValueError(f"{field_key} does not match its workbook regex.")
            return self

    return create_model(
        "ImageMetadataResponse",
        __base__=ImageMetadataBase,
        **fields,
    )
