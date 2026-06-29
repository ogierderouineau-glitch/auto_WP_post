from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from app.v2.knowledge_base.step_01_models import WorkbookSnapshot
from app.v2.models.step_02_payload import WordPressFields, WordPressPayload
from app.v2.payloads.step_01_transforms import apply_transform


class PayloadBuilder:
    """Route values exclusively through workbook destination metadata."""

    def build(
        self,
        snapshot: WorkbookSnapshot,
        *,
        post_type_key: str,
        shared_values: dict[str, Any],
        acf_source_values: dict[str, Any],
        media: list[dict[str, Any]] | None = None,
    ) -> WordPressPayload:
        wordpress: dict[str, Any] = {}
        meta: dict[str, Any] = {}
        acf: dict[str, Any] = {}
        shared_by_key = {row.field_key: row for row in snapshot.shared_fields if row.enabled}
        for field_key, value in shared_values.items():
            schema = shared_by_key.get(field_key)
            if schema is None or not schema.include_in_payload:
                raise ValueError(f"Unknown or non-payload shared field: {field_key}")
            destination = {
                "wordpress": wordpress,
                "yoast": meta,
                "acf": acf,
            }.get(schema.destination_type)
            if destination is None:
                raise ValueError(f"Unknown shared destination: {schema.destination_type}")
            if schema.destination_key in {"categories", "tags"} and not isinstance(value, list):
                value = [part.strip() for part in str(value).split(";") if part.strip()]
            destination[schema.destination_key] = value

        acf_rows = [
            row
            for row in snapshot.acf_fields
            if row.enabled and row.post_type_key == post_type_key
        ]
        direct = {row.field_key: row for row in acf_rows if row.field_role == "direct_acf"}
        for field_key, schema in direct.items():
            if field_key in acf_source_values:
                acf[schema.acf_field_name or field_key] = acf_source_values[field_key]

        aggregation_rows: dict[str, list[Any]] = defaultdict(list)
        for row in acf_rows:
            if row.field_role == "aggregation_source" and row.aggregation_group:
                aggregation_rows[row.aggregation_group].append(row)
        for rows in aggregation_rows.values():
            parts: list[str] = []
            destination_key: str | None = None
            for row in sorted(rows, key=lambda item: item.aggregation_order or 0):
                value = acf_source_values.get(row.field_key)
                if value in (None, "", []):
                    continue
                destination_key = row.acf_field_name
                parts.append(
                    apply_transform(
                        row.transform_key or "",
                        self._aggregation_label(row),
                        str(value),
                    )
                )
            if destination_key and parts:
                if all(row.transform_key == "fact_list_item_html" for row in rows):
                    acf[destination_key] = "<ul>" + "".join(parts) + "</ul>"
                else:
                    acf[destination_key] = "".join(parts)

        return WordPressPayload(
            wordpress=WordPressFields.model_validate(wordpress),
            meta=meta,
            acf=acf,
            media=media or [],
        )

    @staticmethod
    def _aggregation_label(row: Any) -> str:
        guidance = row.guidance_de or ""
        match = re.search(r"<strong>([^:<]+):?</strong>", guidance)
        return match.group(1).strip() if match else row.description_de
