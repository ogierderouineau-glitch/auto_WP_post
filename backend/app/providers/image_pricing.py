from __future__ import annotations

import json
from pathlib import Path


DEFAULT_PRICING_PATH = Path(__file__).resolve().parents[3] / "data" / "openai_image_pricing.json"


def image_output_price_usd(
    model: str,
    quality: str,
    size: str,
    *,
    pricing_path: Path = DEFAULT_PRICING_PATH,
) -> float | None:
    try:
        payload = json.loads(pricing_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    normalized = (model.lower(), quality.lower(), size.lower().replace(" ", ""))
    for row in payload.get("prices", []):
        key = (
            str(row.get("model") or "").lower(),
            str(row.get("quality") or "").lower(),
            str(row.get("size") or "").lower().replace(" ", ""),
        )
        if key == normalized:
            try:
                return float(row["usd_per_image"])
            except (KeyError, TypeError, ValueError):
                return None
    return None
