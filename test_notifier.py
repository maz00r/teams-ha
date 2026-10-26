import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "teams_browser"))

import notifier  # noqa: E402


class TitleCount(unittest.TestCase):
    def test_count(self):
        self.assertEqual(notifier.parse_title_count("(3) Czat | Microsoft Teams"), 3)
        self.assertEqual(notifier.parse_title_count("  (12) Aktywność"), 12)

    def test_no_count(self):
        self.assertEqual(notifier.parse_title_count("Czat | Microsoft Teams"), 0)
        self.assertEqual(notifier.parse_title_count(""), 0)
        self.assertEqual(notifier.parse_title_count(None), 0)
        self.assertEqual(notifier.parse_title_count("Spotkanie (2)"), 0)


class QuietHours(unittest.TestCase):
    def at(self, h, m=0):
        return datetime(2026, 10, 26, h, m)

    def test_over_midnight(self):
        spec = "22:00-07:00"
        self.assertTrue(notifier.in_quiet_hours(spec, self.at(23)))
        self.assertTrue(notifier.in_quiet_hours(spec, self.at(3)))
        self.assertFalse(notifier.in_quiet_hours(spec, self.at(7)))
        self.assertFalse(notifier.in_quiet_hours(spec, self.at(12)))

    def test_same_day(self):
        self.assertTrue(notifier.in_quiet_hours("12:00-13:30", self.at(13, 29)))
        self.assertFalse(notifier.in_quiet_hours("12:00-13:30", self.at(13, 30)))

    def test_invalid_or_empty(self):
        for spec in ("", None, "abc", "25:00-07:00", "22:00"):
            self.assertFalse(notifier.in_quiet_hours(spec, self.at(23)), spec)


class Services(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(notifier.parse_services("notify.mobile_app_a, mobile_app_b"),
                         [("notify", "mobile_app_a"), ("notify", "mobile_app_b")])

    def test_rejects_junk(self):
        self.assertEqual(notifier.parse_services("notify.../x, ../../api"), [])
        self.assertEqual(notifier.parse_services(""), [])


class Message(unittest.TestCase):
    def test_preview(self):
        self.assertEqual(notifier.build_message({"title": "Anna", "body": "Cześć"}, True),
                         ("Anna", "Cześć"))

    def test_no_preview(self):
        self.assertEqual(notifier.build_message({"title": "Anna", "body": "tajne"}, False),
                         ("Teams", "Nowa wiadomość: Anna"))

    def test_truncate(self):
        _, body = notifier.build_message({"title": "A", "body": "x" * 500}, True)
        self.assertEqual(len(body), 298)


class Dedup(unittest.TestCase):
    def test_window(self):
        d = notifier.Deduper(ttl=60)
        self.assertTrue(d.fresh("a", 0))
        self.assertFalse(d.fresh("a", 30))
        self.assertTrue(d.fresh("a", 100))


class Unread(unittest.TestCase):
    def test_fallback_after_grace(self):
        u = notifier.UnreadTracker()
        self.assertIsNone(u.update(0, 1000))
        self.assertIsNone(u.update(2, 1010))
        self.assertEqual(u.update(2, 1010 + notifier.FALLBACK_GRACE), 2)
        self.assertIsNone(u.update(2, 1100))

    def test_real_notification_suppresses(self):
        u = notifier.UnreadTracker()
        u.update(0, 1000)
        u.update(1, 1010)
        u.notified(1012)
        self.assertIsNone(u.update(1, 1050))

    def test_first_reading_is_baseline(self):
        u = notifier.UnreadTracker()
        self.assertIsNone(u.update(5, 1000))
        self.assertIsNone(u.update(5, 2000))

    def test_read_cancels(self):
        u = notifier.UnreadTracker()
        u.update(0, 1000)
        u.update(1, 1010)
        self.assertIsNone(u.update(0, 1020))
        self.assertIsNone(u.update(0, 1100))


class Hook(unittest.TestCase):
    def test_binding_inlined(self):
        self.assertIn(notifier.BINDING, notifier.HOOK_JS)
        self.assertNotIn("%(b)s", notifier.HOOK_JS)


if __name__ == "__main__":
    unittest.main()
