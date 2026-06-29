from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def compare(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    mappings = {
        "wordpress.title": (
            v1.get("title") or nested(v1, "wordpress", "title"),
            nested(v2, "wordpress", "title"),
        ),
        "wordpress.slug": (
            v1.get("slug") or nested(v1, "wordpress", "slug"),
            nested(v2, "wordpress", "slug"),
        ),
        "wordpress.excerpt": (
            v1.get("excerpt") or nested(v1, "wordpress", "excerpt"),
            nested(v2, "wordpress", "excerpt"),
        ),
        "acf.hero_h1": (
            nested(v1, "acf", "hero_h1"),
            nested(v2, "acf", "hero_h1"),
        ),
        "acf.verlauf_h2": (
            nested(v1, "acf", "verlauf_h2"),
            nested(v2, "acf", "verlauf_h2"),
        ),
        "acf.related_links_html": (
            nested(v1, "acf", "related_links_html"),
            nested(v2, "acf", "related_links_html"),
        ),
        "meta.yoast_wpseo_title": (
            nested(v1, "meta", "yoast_wpseo_title"),
            nested(v2, "meta", "yoast_wpseo_title"),
        ),
        "meta.yoast_wpseo_metadesc": (
            nested(v1, "meta", "yoast_wpseo_metadesc"),
            nested(v2, "meta", "yoast_wpseo_metadesc"),
        ),
    }
    rows = []
    for field, (old, new) in mappings.items():
        rows.append(
            {
                "field": field,
                "v1_present": old not in (None, "", []),
                "v2_present": new not in (None, "", []),
                "identical": old == new,
            }
        )
    required_v2 = [
        row["field"]
        for row in rows
        if row["field"] not in {"acf.related_links_html"} and not row["v2_present"]
    ]
    return {
        "required_v2_fields_missing": required_v2,
        "rows": rows,
        "intentional_text_differences_allowed": True,
        "pass": not required_v2,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare representative V1 and V2 payloads.")
    parser.add_argument("--v1", type=Path, required=True)
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare(
        json.loads(args.v1.read_text(encoding="utf-8")),
        json.loads(args.v2.read_text(encoding="utf-8")),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
