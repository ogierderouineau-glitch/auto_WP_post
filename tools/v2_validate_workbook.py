from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.v2.errors import InvalidWorkbookError
from app.v2.knowledge_base.step_02_loader import WorkbookLoader
from app.v2.knowledge_base.step_03_validator import WorkbookValidator


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a FLAIRLAB V2 workbook.")
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    try:
        snapshot = WorkbookValidator().validate(WorkbookLoader().load(args.workbook))
    except InvalidWorkbookError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "valid": True,
                "filename": snapshot.version.filename,
                "sha256": snapshot.version.sha256,
                "post_types": len(snapshot.post_types),
                "shared_fields": len(snapshot.shared_fields),
                "acf_fields": len(snapshot.acf_fields),
                "blueprint_rows": len(snapshot.blueprint),
                "workflow_steps": len(snapshot.workflow_steps),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
