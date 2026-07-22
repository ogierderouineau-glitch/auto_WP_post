from __future__ import annotations

import unittest
import json
from pathlib import Path
import tempfile

from app.v2.providers.image_pricing import image_output_price_usd
from scripts.update_openai_image_pricing import parse_pricing_html


class OpenAIImagePricingParserTests(unittest.TestCase):
    def test_runtime_lookup_reads_matching_output_price(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pricing_path = Path(temporary) / "pricing.json"
            pricing_path.write_text(json.dumps({"prices": [{
                "model": "gpt-image-2",
                "quality": "medium",
                "size": "1024x1536",
                "usd_per_image": 0.041,
            }]}))

            price = image_output_price_usd(
                "gpt-image-2",
                "medium",
                "1024x1536",
                pricing_path=pricing_path,
            )

        self.assertEqual(price, 0.041)

    def test_parses_rowspan_style_pricing_table(self) -> None:
        qualities = (
            ("Low", "0.006", "0.005", "0.005"),
            ("Medium", "0.053", "0.041", "0.041"),
            ("High", "0.211", "0.165", "0.165"),
        )
        rows = "".join(
            f"<tr>{'<td>GPT Image 2</td>' if index == 0 else ''}<td>{quality}</td>"
            f"<td>${square}</td><td>${portrait}</td><td>${landscape}</td></tr>"
            for index, (quality, square, portrait, landscape) in enumerate(qualities)
        )
        html = (
            "<table><tr><th>Model</th><th>Quality</th><th>1024 x 1024</th>"
            "<th>1024 x 1536</th><th>1536 x 1024</th></tr>"
            f"{rows}</table>"
        )

        prices = parse_pricing_html(html)

        self.assertEqual(len(prices), 9)
        self.assertIn(
            {
                "model": "gpt-image-2",
                "quality": "high",
                "size": "1024x1536",
                "usd_per_image": 0.165,
            },
            prices,
        )

    def test_rejects_unrelated_table(self) -> None:
        with self.assertRaisesRegex(ValueError, "was not found"):
            parse_pricing_html("<table><tr><th>Name</th><th>Price</th></tr></table>")
