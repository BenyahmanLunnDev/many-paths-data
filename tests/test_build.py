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


class DueTest(unittest.TestCase):

    def test_weekly_copies_wait_for_their_weekday(self):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        eight_days = {"status": "ok", "fetchedAt": (now - dt.timedelta(days=8)).isoformat()}
        two_days = {"status": "ok", "fetchedAt": (now - dt.timedelta(days=2)).isoformat()}
        fifteen = {"status": "ok", "fetchedAt": (now - dt.timedelta(days=15)).isoformat()}
        monday, tuesday = dt.date(2026, 10, 19), dt.date(2026, 10, 20)
        weekly = {"refreshDays": 7, "weekday": 0}
        self.assertTrue(build.due(weekly, eight_days, monday))
        self.assertFalse(build.due(weekly, eight_days, tuesday))
        self.assertFalse(build.due(weekly, two_days, monday))
        self.assertTrue(build.due(weekly, fifteen, tuesday))  # never left stale for long
        self.assertTrue(build.due(weekly, {}, tuesday))  # never copied yet
        self.assertTrue(build.due({"refreshDays": 1}, two_days, tuesday))


class PublicPageTest(unittest.TestCase):

    ROW = ('<tr><td class="time"><span>Monday</span><span>6:30 am</span></td>'
           '<td class="name"><a href="https://x.org/meetings/early-birds/">Early Birds</a> <small>Women</small></td>'
           '<td class="location"><div class="location-name">First Church</div></td>'
           # Newer versions of the plugin break the cell across lines.
           '<td class="address notranslate"\n                    data-sort="{key}">\n    12 Main St    </td>'
           '<td class="region">Salt Lake City</td><td class="types">Open, Discussion</td></tr>')

    def test_state_and_zip_come_from_the_sort_key_in_both_formats(self):
        import extra
        for key in ("12-main-st-salt-lake-city-ut-84101-usa", "12-main-st-salt-lake-city-ut-84101-usa-1-06:30"):
            meetings, addresses = extra.parse_tsml_page(self.ROW.format(key=key), {})
            m = meetings[0]
            self.assertEqual(m["name"], "Early Birds")
            self.assertEqual(m["formatted_address"], "12 Main St, Salt Lake City, UT 84101")
            self.assertEqual(m["_state"], "UT")
            self.assertEqual(m["types"], ["O", "D"])
            self.assertIn("12 main st|salt lake city|ut|84101", addresses)
        self.assertEqual(extra.timezone_for("UT", 40.76, -111.89), "America/Denver")


if __name__ == "__main__":
    unittest.main()
