from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.v2.knowledge_base.step_02_loader import WorkbookLoader


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _families(snapshot: Any) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for row in snapshot.validation_values:
        values = grouped.setdefault(row.list_name, [])
        if row.allowed_value not in values:
            values.append(row.allowed_value)
    return grouped


def _render_markdown(snapshot: Any) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    families = _families(snapshot)
    lines = [
        "# V2 Validation Choices",
        "",
        f"- Generated at: {generated_at}",
        f"- Workbook: {snapshot.version.filename}",
        f"- Workbook SHA-256: {snapshot.version.sha256}",
        "",
        "This file is generated from the loaded workbook snapshot.",
        "",
    ]
    for family in sorted(families):
        lines.append(f"## {family}")
        lines.append("")
        lines.append("| # | allowed_value |")
        lines.append("|---|---|")
        for index, value in enumerate(families[family], start=1):
            lines.append(f"| {index} | `{_json_value(value)}` |")
        lines.append("")
    return "\n".join(lines)


def _write_csv(snapshot: Any, output: Path) -> None:
    families = _families(snapshot)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["list_name", "position", "allowed_value", "allowed_value_json"])
        for family in sorted(families):
            for index, value in enumerate(families[family], start=1):
                writer.writerow([family, index, _display_value(value), _json_value(value)])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export V2 validation_lists as markdown and CSV references.",
    )
    parser.add_argument("workbook", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/v2/validation_choices.md"),
        help="Markdown output path.",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=Path("docs/v2/validation_choices.csv"),
        help="CSV output path.",
    )
    args = parser.parse_args()

    snapshot = WorkbookLoader().load(args.workbook)

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(snapshot), encoding="utf-8")
    _write_csv(snapshot, args.csv_output)
    print(str(output))
    print(str(args.csv_output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())