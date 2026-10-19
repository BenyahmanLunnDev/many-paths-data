import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builder"))
import ical  # noqa: E402

SOURCE = {"id": "na-test", "fellowship": "NA", "state": "ID", "timezone": "America/Denver", "website": "https://example.org/meetings/"}
TODAY = dt.date(2026, 10, 19)  # a Monday


def calendar(*events):
    return "BEGIN:VCALENDAR\r\nX-WR-TIMEZONE:America/Denver\r\n" + "".join(
        "BEGIN:VEVENT\r\n" + e.strip().replace("\n", "\r\n") + "\r\nEND:VEVENT\r\n" for e in events) + "END:VCALENDAR\r\n"


class CalendarTest(unittest.TestCase):

    def test_weekly_meeting(self):
        text = calendar("""
DTSTART;TZID=America/Denver:20221008T190000
DTEND;TZID=America/Denver:20221008T203000
RRULE:FREQ=WEEKLY;BYDAY=SA
EXDATE;TZID=America/Denver:20261024T190000
UID:abc123@google.com
SUMMARY:POCATELLO - Never Alone (O)(WC)
LOCATION:745 S 1st Ave\\, Pocatello\\, ID 83201\\, USA
DESCRIPTION:(BS)(1H+)\\nLibrary Room
LAST-MODIFIED:20250102T030405Z""")
        meetings, addresses = ical.meetings(text, SOURCE, TODAY)
        self.assertEqual(len(meetings), 1)
        m = meetings[0]
        self.assertEqual(m["name"], "Never Alone")
        self.assertEqual(m["day"], [6])
        self.assertEqual((m["time"], m["end_time"]), ("19:00", "20:30"))
        self.assertEqual(m["timezone"], "America/Denver")
        self.assertEqual(m["types"], ["O", "X", "Book study"])
        self.assertEqual(m["notes"], "Library Room")
        self.assertEqual(m["formatted_address"], "745 S 1st Ave, Pocatello, ID 83201")
        self.assertEqual(m["skip"], ["2026-10-24"])
        self.assertEqual(m["updated"], "2025-01-02")
        self.assertEqual(m["attendance_option"], "in_person")
        self.assertIn("745 s 1st ave|pocatello|id|83201", addresses)

    def test_ended_one_off_monthly_and_service_meetings_are_left_out(self):
        text = calendar(
            """DTSTART;TZID=America/Denver:20200101T190000
RRULE:FREQ=WEEKLY;UNTIL=20250101T000000Z;BYDAY=WE
SUMMARY:BLACKFOOT - Old Group
LOCATION:790 NE Main St\\, Blackfoot\\, ID 83221""",
            """DTSTART;TZID=America/Denver:20261031T190000
SUMMARY:Halloween Dance
LOCATION:790 NE Main St\\, Blackfoot\\, ID 83221""",
            """DTSTART;TZID=America/Denver:20250406T130000
RRULE:FREQ=MONTHLY;BYDAY=1SU
SUMMARY:Snake River Area Service Committee
LOCATION:790 NE Main St\\, Blackfoot\\, ID 83221""",
            """DTSTART;TZID=America/Denver:20250406T100000
RRULE:FREQ=WEEKLY;BYDAY=SU
SUMMARY:Snake River H&I Sub-committee
LOCATION:790 NE Main St\\, Blackfoot\\, ID 83221""",
            """DTSTART;TZID=America/Denver:20250406T100000
RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=SU
SUMMARY:BLACKFOOT - Every Other Week
LOCATION:790 NE Main St\\, Blackfoot\\, ID 83221""",
        )
        self.assertEqual(ical.meetings(text, SOURCE, TODAY)[0], [])

    def test_series_starting_later_skips_the_weeks_before(self):
        text = calendar("""DTSTART;TZID=America/Denver:20261102T183000
RRULE:FREQ=WEEKLY;WKST=SU;BYDAY=MO,TU
SUMMARY:TETON VALLEY-Just for Tonight
LOCATION:St Francis of the Tetons Church\\, 20 Alta School Rd\\, Alta\\, WY 83414\\, USA""")
        m = ical.meetings(text, SOURCE, TODAY)[0][0]
        self.assertEqual(m["day"], [1, 2])
        self.assertEqual(m["location"], "St Francis of the Tetons Church")
        self.assertEqual(m["skip"], ["2026-10-19", "2026-10-20", "2026-10-26", "2026-10-27"])

    def test_moved_instance_and_online_link(self):
        text = calendar(
            """DTSTART;TZID=America/Denver:20250101T120000
RRULE:FREQ=WEEKLY
UID:zoom1@google.com
SUMMARY:Lunchtime Recovery
DESCRIPTION:Join at https://us02web.zoom.us/j/123?pwd=x""",
            """DTSTART;TZID=America/Denver:20261028T130000
RECURRENCE-ID;TZID=America/Denver:20261028T120000
UID:zoom1@google.com
SUMMARY:Lunchtime Recovery""",
        )
        meetings, addresses = ical.meetings(text, SOURCE, TODAY)
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0]["day"], [3])  # 2025-01-01 was a Wednesday
        self.assertEqual(meetings[0]["attendance_option"], "online")
        self.assertEqual(meetings[0]["conference_url"], "https://us02web.zoom.us/j/123?pwd=x")
        self.assertEqual(meetings[0]["skip"], ["2026-10-28"])
        self.assertEqual(addresses, {})

    def test_addresses(self):
        self.assertEqual(ical.split_address("745 S 1st Ave Pocatello, ID 83201", "Pocatello", "ID"),
                         (None, "745 S 1st Ave", "Pocatello", "ID", "83201"))
        self.assertEqual(ical.split_address("237 N Water Room 206. Idaho Falls, ID", "Idaho Falls", "ID"),
                         (None, "237 N Water", "Idaho Falls", "ID", ""))
        self.assertEqual(ical.split_address("140 Antelope Drive, Elk Bend, Idaho  Off  Hwy 93", None, "ID")[1], None)


if __name__ == "__main__":
    unittest.main()
