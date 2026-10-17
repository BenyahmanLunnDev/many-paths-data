import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builder"))
import build  # noqa: E402


class BuildTest(unittest.TestCase):

    def test_trim_keeps_only_what_the_app_reads(self):
        record = {"id": 1, "name": "Never Alone", "day": 2, "time": "19:00", "edit_url": "x", "venmo": "@me",
                  "author": "admin", "notes": "", "types": []}
        self.assertEqual(build.trim(record), {"id": 1, "name": "Never Alone", "day": 2, "time": "19:00"})

    def test_restricted_lists_need_a_key(self):
        evi = {"id": "aa-eviaa", "kind": "TSML", "url": "https://www.eviaa.org/wp-admin/admin-ajax.php?action=meetings",
               "restricted": True}
        self.assertFalse(build.wanted(evi, {}))
        self.assertTrue(build.wanted(evi, {"aa-eviaa": "abc"}))
        self.assertTrue(build.request_url(evi, {"aa-eviaa": "abc"}).endswith("action=meetings&key=abc"))

    def test_only_feeds_are_fetched(self):
        self.assertFalse(build.wanted({"id": "na", "kind": "BMLT_NEARBY", "url": "https://x"}, {}))
        self.assertFalse(build.wanted({"id": "link", "kind": "LINK"}, {}))
        self.assertTrue(build.wanted({"id": "refuge", "kind": "TSML", "url": "https://x"}, {}))

    def test_keys_secret_format(self):
        self.assertEqual(build.parse_keys("aa-eviaa=abc; aa-pdx = def ;junk"), {"aa-eviaa": "abc", "aa-pdx": "def"})
        self.assertEqual(build.parse_keys(None), {})

    def test_hand_written_sources_win(self):
        sources = build.load_sources()
        ids = [s["id"] for s in sources]
        self.assertEqual(len(ids), len(set(ids)))
        keys = [build.feed_key(s["url"]) for s in sources if s.get("url") and s["kind"] == "TSML"]
        self.assertEqual(len(keys), len(set(keys)), "the same feed is listed twice")

    def test_no_keys_in_the_repo(self):
        text = "".join(p.read_text(encoding="utf-8") for p in (Path(build.ROOT) / "sources").glob("*.json"))
        self.assertNotIn("key=", text)


if __name__ == "__main__":
    unittest.main()
