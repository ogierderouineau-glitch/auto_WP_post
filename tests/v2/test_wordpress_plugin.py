from __future__ import annotations

import unittest
from pathlib import Path


class WordPressPluginTests(unittest.TestCase):
    def test_compatibility_plugin_contains_required_contract_names(self) -> None:
        path = Path("wordpress/flairlab-v2-rest-compat/flairlab-v2-rest-compat.php")
        source = path.read_text(encoding="utf-8")
        self.assertIn("'show_in_rest' => true", source)
        self.assertIn("'yoast_wpseo_opengraph_title'", source)
        self.assertIn("'yoast_wpseo_opengraph_description'", source)
        self.assertIn("'_yoast_wpseo_opengraph-title'", source)
        self.assertIn("'_yoast_wpseo_opengraph-description'", source)
        self.assertNotIn("acf_add_local_field_group", source)
        self.assertNotIn("'name' => 'gallery_html'", source)

    def test_dynamic_shortcode_uses_registered_meta_object_and_escapes_values(self) -> None:
        path = Path(
            "wordpress/flairlab-dynamic-shortcodes/flairlab-dynamic-shortcodes.php"
        )
        source = path.read_text(encoding="utf-8")
        self.assertIn("add_shortcode('post_variable'", source)
        self.assertIn("register_post_meta(", source)
        self.assertIn("'_generated_variables'", source)
        self.assertIn("'type' => 'object'", source)
        self.assertIn("'show_in_rest' => [", source)
        self.assertIn("$post_id = get_the_ID();", source)
        self.assertIn(
            "get_post_meta($post_id, '_generated_variables', true)",
            source,
        )
        self.assertIn("return esc_html((string) $value);", source)
