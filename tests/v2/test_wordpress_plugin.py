from __future__ import annotations

import unittest
from pathlib import Path


class WordPressPluginTests(unittest.TestCase):
    def test_compatibility_plugin_contains_required_contract_names(self) -> None:
        path = Path("wordpress/flairlab-v2-rest-compat/flairlab-v2-rest-compat.php")
        source = path.read_text(encoding="utf-8")
        self.assertIn("'name' => 'related_links_html'", source)
        self.assertIn("'show_in_rest' => 1", source)
        self.assertIn("'yoast_wpseo_opengraph_title'", source)
        self.assertIn("'yoast_wpseo_opengraph_description'", source)
        self.assertIn("'_yoast_wpseo_opengraph-title'", source)
        self.assertIn("'_yoast_wpseo_opengraph-description'", source)
        self.assertNotIn("'name' => 'gallery_html'", source)
