#!/usr/bin/env python3
"""Refresh the local OpenAI image-output pricing table from official docs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen


SOURCE_URL = "https://developers.openai.com/api/docs/guides/image-generation#calculating-costs"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "openai_image_pricing.json"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _model_id(label: str) -> str:
    return label.lower().replace("gpt image", "gpt-image").replace(" ", "-")


def parse_pricing_html(html: str) -> list[dict[str, object]]:
    parser = _TableParser()
    parser.feed(html)
    table = next(
        (
            rows
            for rows in parser.tables
            if rows and len(rows[0]) >= 3 and rows[0][:2] == ["Model", "Quality"]
        ),
        None,
    )
    if table is None:
        raise ValueError("OpenAI image pricing table was not found; the page structure may have changed.")

    sizes = [re.sub(r"\s*x\s*", "x", value.lower()) for value in table[0][2:]]
    current_model = ""
    prices: list[dict[str, object]] = []
    for row in table[1:]:
        if len(row) == len(sizes) + 2:
            current_model = _model_id(row[0].replace("Additional sizes available", "").strip())
            quality, values = row[1], row[2:]
        elif len(row) == len(sizes) + 1 and current_model:
            quality, values = row[0], row[1:]
        else:
            continue
        for size, raw_price in zip(sizes, values):
            match = re.fullmatch(r"\$([0-9]+(?:\.[0-9]+)?)", raw_price)
            if not match:
                raise ValueError(f"Unexpected price {raw_price!r} for {current_model} {quality} {size}.")
            prices.append(
                {
                    "model": current_model,
                    "quality": quality.lower(),
                    "size": size,
                    "usd_per_image": float(match.group(1)),
                }
            )
    _validate(prices)
    return prices


def _validate(prices: list[dict[str, object]]) -> None:
    keys = {(row["model"], row["quality"], row["size"]) for row in prices}
    required = {
        ("gpt-image-2", quality, size)
        for quality in ("low", "medium", "high")
        for size in ("1024x1024", "1024x1536", "1536x1024")
    }
    if not required.issubset(keys):
        raise ValueError("Pricing table is incomplete: required GPT Image 2 prices are missing.")
    if any(float(row["usd_per_image"]) <= 0 for row in prices):
        raise ValueError("Pricing table contains a non-positive price.")


def _write_atomic(destination: Path, payload: dict[str, object]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    request = Request(SOURCE_URL.split("#", 1)[0], headers={"User-Agent": "SPEECH2POST pricing updater/1.0"})
    with urlopen(request, timeout=args.timeout) as response:
        document = response.read()
    prices = parse_pricing_html(document.decode("utf-8"))
    payload = {
        "schema_version": 1,
        "source_url": SOURCE_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sha256(document).hexdigest(),
        "currency": "USD",
        "unit": "per_output_image",
        "notes": "Output-image estimates only; text and image input tokens may add cost.",
        "prices": prices,
    }
    _write_atomic(args.output.resolve(), payload)
    print(f"Stored {len(prices)} validated prices in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
