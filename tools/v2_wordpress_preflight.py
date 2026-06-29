from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.v2.knowledge_base.step_02_loader import WorkbookLoader
from app.v2.knowledge_base.step_03_validator import WorkbookValidator
from app.v2.models.step_01_session import ContentSession
from app.v2.models.step_02_payload import WordPressFields, WordPressPayload
from app.v2.providers.step_03_wordpress import ExistingWordPressProvider
from step_40_wordpress_api import find_term, preflight_wordpress_permissions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only V2 contract preflight against staging WordPress."
    )
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--post-type", default="event")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = WorkbookValidator().validate(WorkbookLoader().load(args.workbook))
    post_type = snapshot.post_type(args.post_type)
    if post_type is None:
        raise SystemExit(f"Unknown post type: {args.post_type}")
    acf_destinations = {
        row.acf_field_name
        for row in snapshot.acf_fields
        if row.enabled
        and row.post_type_key == args.post_type
        and row.include_in_payload
        and row.acf_field_name
    }
    acf_destinations.update(
        row.destination_key
        for row in snapshot.shared_fields
        if row.enabled and row.include_in_payload and row.destination_type == "acf"
    )
    meta_destinations = {
        row.destination_key
        for row in snapshot.shared_fields
        if row.enabled and row.include_in_payload and row.destination_type == "yoast"
    }
    session = ContentSession(
        session_id="preflight",
        user_id="preflight",
        post_type_key=args.post_type,
        wordpress_post_type=post_type.wp_post_type,
        state="created",
        workbook_hash=snapshot.version.sha256,
        language=post_type.default_language,
    )
    provider = ExistingWordPressProvider()
    contract = provider.contract_report(
        session=session,
        payload=WordPressPayload(
            wordpress=WordPressFields(),
            meta={key: "preflight" for key in meta_destinations},
            acf={key: "preflight" for key in acf_destinations},
        ),
    )
    authentication = preflight_wordpress_permissions(strict=False)
    category = find_term("categories", post_type.wp_category_name)
    report = {
        "ready": bool(
            contract["ready"]
            and authentication.get("authenticated")
            and not authentication.get("missing_capabilities")
            and category
        ),
        "workbook_sha256": snapshot.version.sha256,
        "post_type_key": args.post_type,
        "authentication": authentication,
        "category": {
            "name": post_type.wp_category_name,
            "found": bool(category),
            "id": category.get("id") if category else None,
        },
        "contract": contract,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
