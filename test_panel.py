import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "teams_browser"))

import panel  # noqa: E402


class StaticPath(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.dir.name, "core"))
        with open(os.path.join(self.dir.name, "core", "rfb.js"), "w") as f:
            f.write("x")
        self.patch = mock.patch.object(panel, "NOVNC_DIR", self.dir.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def test_ok(self):
        self.assertTrue(panel.safe_static_path("/core/rfb.js").endswith("rfb.js"))

    def test_traversal(self):
        self.assertIsNone(panel.safe_static_path("/../../etc/passwd"))
        self.assertIsNone(panel.safe_static_path("/%2e%2e/%2e%2e/etc/passwd"))
        self.assertIsNone(panel.safe_static_path("/missing.js"))


class Actions(unittest.TestCase):
    def test_type_validates(self):
        self.assertEqual(panel.run_action("/api/type", {"text": ""})[0], 400)
        self.assertEqual(panel.run_action("/api/type", {"text": 5})[0], 400)
        self.assertEqual(panel.run_action("/api/type", {"text": "x" * 5000})[0], 400)

    def test_type_and_enter(self):
        with mock.patch.object(panel.cdp, "insert_text") as ins, \
             mock.patch.object(panel.cdp, "press_key") as key:
            code, _ = panel.run_action("/api/type", {"text": "Zażółć", "enter": True})
        self.assertEqual(code, 200)
        ins.assert_called_once_with("Zażółć")
        key.assert_called_once_with("Enter")

    def test_key_whitelist(self):
        self.assertEqual(panel.run_action("/api/key", {"key": "F12"})[0], 400)
        with mock.patch.object(panel.cdp, "press_key") as key:
            self.assertEqual(panel.run_action("/api/key", {"key": "Escape"})[0], 200)
        key.assert_called_once_with("Escape")

    def test_scroll_and_nav_validate(self):
        self.assertEqual(panel.run_action("/api/scroll", {"dir": "left"})[0], 400)
        self.assertEqual(panel.run_action("/api/nav", {"action": "javascript:alert(1)"})[0], 400)

    def test_unknown(self):
        self.assertEqual(panel.run_action("/api/nope", {})[0], 404)

    def test_heartbeat(self):
        panel.run_action("/api/heartbeat", {})
        self.assertTrue(panel.viewer_active())
        panel.run_action("/api/heartbeat", {"leaving": True})
        self.assertFalse(panel.viewer_active())


if __name__ == "__main__":
    unittest.main()
