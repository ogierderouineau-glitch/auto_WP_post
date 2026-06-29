from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from step_40_wordpress_api import request_json

PLUGIN_FILE = "flairlab-v2-rest-compat/flairlab-v2-rest-compat.php"
PLUGIN_FILES = {
    PLUGIN_FILE,
    "flairlab-v2-rest-compat/flairlab-v2-rest-compat",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check or activate the already-uploaded FLAIRLAB V2 REST compatibility "
            "plugin. This tool does not upload plugin files."
        )
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Activate the plugin through WordPress REST. Without this flag, read-only.",
    )
    args = parser.parse_args()
    plugins = request_json(
        "GET",
        "/wp-json/wp/v2/plugins",
        params={"context": "edit", "per_page": 100},
    )
    plugin = next(
        (row for row in plugins if row.get("plugin") in PLUGIN_FILES),
        None,
    )
    if plugin is None:
        print(
            json.dumps(
                {
                    "present": False,
                    "active": False,
                    "plugin": sorted(PLUGIN_FILES)[0],
                    "next_action": (
                        "Upload dist/flairlab-v2-rest-compat.zip in WordPress Admin, "
                        "then rerun this tool."
                    ),
                },
                indent=2,
            )
        )
        return 1
    if args.activate and plugin.get("status") != "active":
        plugin = request_json(
            "POST",
            f"/wp-json/wp/v2/plugins/{plugin['plugin']}",
            json={"status": "active"},
        )
    report = {
        "present": True,
        "active": plugin.get("status") == "active",
        "plugin": plugin.get("plugin"),
        "name": plugin.get("name"),
        "version": plugin.get("version"),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["active"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
