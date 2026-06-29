from __future__ import annotations

import unittest

from tools.v2_activate_wordpress_plugin import PLUGIN_FILE


class PluginActivationToolTests(unittest.TestCase):
    def test_plugin_identifier_matches_package_layout(self) -> None:
        self.assertEqual(
            PLUGIN_FILE,
            "flairlab-v2-rest-compat/flairlab-v2-rest-compat.php",
        )
