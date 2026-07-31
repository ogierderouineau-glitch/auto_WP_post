from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from backend.app.knowledge_base.step_01_models import WorkbookSnapshot
from backend.app.models.step_02_payload import WordPressFields, WordPressPayload
from backend.app.payloads.step_01_transforms import apply_transform


class PayloadBuilder:
    """Route values exclusively through workbook destination metadata."""

    def build(
        self,
        snapshot: WorkbookSnapshot,
        *,
        post_type_key: str,
        shared_values: dict[str, Any],
        acf_source_values: dict[str, Any],
        confirmed_facts: dict[str, Any] | None = None,
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

        taxonomies, media_taxonomies = self.taxonomy_terms(
            snapshot,
            post_type_key=post_type_key,
            shared_values=shared_values,
            acf_source_values=acf_source_values,
            confirmed_facts=confirmed_facts,
        )
        post_type = snapshot.post_type(post_type_key)
        generated_variables: dict[str, str] = {}
        for field_key in post_type.post_shortcode_variables if post_type else ():
            fact = (confirmed_facts or {}).get(field_key)
            if fact is None or not bool(getattr(fact, "confirmed", False)):
                continue
            value = getattr(fact, "value", None)
            if value in (None, "", []) or not isinstance(value, (str, int, float, bool)):
                continue
            generated_variables[field_key] = str(value)
        if generated_variables:
            meta["_generated_variables"] = generated_variables

        return WordPressPayload(
            wordpress=WordPressFields.model_validate(wordpress),
            meta=meta,
            acf=acf,
            taxonomies=taxonomies,
            media_taxonomies=media_taxonomies,
            media=media or [],
        )

    def taxonomy_terms(
        self,
        snapshot: WorkbookSnapshot,
        *,
        post_type_key: str,
        shared_values: dict[str, Any],
        acf_source_values: dict[str, Any],
        confirmed_facts: dict[str, Any] | None = None,
    ) -> tuple[dict[str, list[str]], list[str]]:
        post_type = snapshot.post_type(post_type_key)
        taxonomies: dict[str, list[str]] = {}
        media_taxonomies: list[str] = []
        taxonomy_configs = {
            (row.post_type_key, row.wp_taxonomy): row
            for row in snapshot.taxonomies
        }
        for wp_taxonomy in post_type.wp_taxonomies if post_type else ():
            taxonomy = (
                taxonomy_configs.get((post_type_key, wp_taxonomy))
                or taxonomy_configs[("*", wp_taxonomy)]
            )
            taxonomy_term_source = taxonomy.taxonomy_term_source
            source_kind, _, source_key = taxonomy_term_source.partition(":")
            if source_kind == "fixed":
                term_value: Any = source_key
            elif source_kind == "shared":
                term_value = shared_values.get(source_key)
            elif source_kind == "acf":
                term_value = acf_source_values.get(source_key)
                fact = (confirmed_facts or {}).get(source_key)
                if (
                    term_value in (None, "")
                    and fact is not None
                    and bool(getattr(fact, "confirmed", False))
                ):
                    term_value = getattr(fact, "value", None)
            else:
                fact = (confirmed_facts or {}).get(source_key)
                term_value = (
                    getattr(fact, "value", None)
                    if fact is not None and bool(getattr(fact, "confirmed", False))
                    else None
                )
            term_names = self._taxonomy_term_names(term_value)
            if term_names:
                taxonomies[wp_taxonomy] = term_names
                if post_type.assign_taxonomy_to_media or taxonomy.assign_taxonomy_to_media:
                    media_taxonomies.append(wp_taxonomy)
        return taxonomies, media_taxonomies

    @staticmethod
    def _taxonomy_term_names(value: Any) -> list[str]:
        raw_values = (
            value
            if isinstance(value, (list, tuple, set))
            else [value]
        )
        terms: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            for part in str(raw_value or "").replace(";", ",").split(","):
                term = part.strip()
                normalized = term.casefold()
                if term and normalized not in seen:
                    terms.append(term)
                    seen.add(normalized)
        return terms

    @staticmethod
    def _aggregation_label(row: Any) -> str:
        guidance = row.guidance_de or ""
        match = re.search(r"<strong>([^:<]+):?</strong>", guidance)
        return match.group(1).strip() if match else row.description_de
