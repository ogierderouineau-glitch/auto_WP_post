from __future__ import annotations

import unittest

from tools.activate_wordpress_plugin import PLUGIN_FILE


class PluginActivationToolTests(unittest.TestCase):
    def test_plugin_identifier_matches_package_layout(self) -> None:
        self.assertEqual(
            PLUGIN_FILE,
            "speech2post-rest-compat/speech2post-rest-compat.php",
        )
