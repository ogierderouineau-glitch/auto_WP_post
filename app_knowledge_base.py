import re
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {
    "user field name": "user_field_name",
    "acf field name": "acf_field_name",
    "ai guidance": "ai_guidance",
}


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_lookup(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def merged_cell_value(sheet: Any, row: int, column: int) -> Any:
    cell = sheet.cell(row=row, column=column)
    if cell.value not in (None, ""):
        return cell.value

    for merged_range in sheet.merged_cells.ranges:
        if cell.coordinate in merged_range:
            return sheet.cell(merged_range.min_row, merged_range.min_col).value
    return cell.value


def find_header_row(sheet: Any) -> tuple[int, dict[str, int]] | None:
    for row_index in range(1, min(sheet.max_row, 30) + 1):
        headers: dict[str, int] = {}
        for column_index in range(1, sheet.max_column + 1):
            value = merged_cell_value(sheet, row_index, column_index)
            normalized = normalize_key(str(value or ""))
            if normalized in REQUIRED_COLUMNS:
                headers[REQUIRED_COLUMNS[normalized]] = column_index
        if set(headers) == set(REQUIRED_COLUMNS.values()):
            return row_index, headers
    return None


def sheet_score(sheet_name: str, preferred_sheet: str | None) -> int:
    normalized = normalize_key(sheet_name)
    if preferred_sheet and normalize_key(preferred_sheet) == normalized:
        return 100
    score = 0
    if "acf" in normalized:
        score += 20
    if "output" in normalized:
        score += 10
    if "post" in normalized:
        score += 5
    return score


def load_workbook_guidance(
    workbook_path: str | Path | None,
    preferred_sheet: str | None = None,
) -> dict[str, Any]:
    if not workbook_path:
        return {"source": None, "items": []}

    path = Path(workbook_path)
    if not path.exists():
        return {"source": str(path), "error": "Workbook file not found.", "items": []}

    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError:
        return {"source": str(path), "error": "openpyxl is not installed.", "items": []}

    workbook = load_workbook(path, read_only=False, data_only=True, keep_vba=True)
    candidates = []
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        header = find_header_row(sheet)
        if header:
            candidates.append((sheet_score(sheet_name, preferred_sheet), sheet_name, sheet, header))

    if not candidates:
        return {"source": str(path), "error": "No sheet with User field name, ACF field name, AI guidance columns found.", "items": []}

    _, sheet_name, sheet, (header_row, headers) = sorted(candidates, key=lambda item: item[0], reverse=True)[0]
    items = []
    for row_index in range(header_row + 1, sheet.max_row + 1):
        user_field_name = str(merged_cell_value(sheet, row_index, headers["user_field_name"]) or "").strip()
        acf_field_name = str(merged_cell_value(sheet, row_index, headers["acf_field_name"]) or "").strip()
        ai_guidance = str(merged_cell_value(sheet, row_index, headers["ai_guidance"]) or "").strip()
        if not any((user_field_name, acf_field_name, ai_guidance)):
            continue
        if not ai_guidance:
            continue
        items.append({
            "user_field_name": user_field_name,
            "acf_field_name": acf_field_name,
            "ai_guidance": ai_guidance,
        })

    return {
        "source": str(path),
        "sheet": sheet_name,
        "items": items,
    }


def guidance_for_field(guidance_data: dict[str, Any], user_field_name: str, acf_field_name: str) -> list[str]:
    items = guidance_data.get("items", [])
    user_lookup = normalize_lookup(user_field_name)
    acf_lookup = normalize_lookup(acf_field_name)
    matches: list[str] = []
    for item in items:
        item_user = normalize_lookup(item.get("user_field_name", ""))
        item_acf = normalize_lookup(item.get("acf_field_name", ""))
        if item_user and item_user == user_lookup:
            matches.append(item["ai_guidance"])
        elif item_acf and item_acf == acf_lookup:
            matches.append(item["ai_guidance"])
    return matches
