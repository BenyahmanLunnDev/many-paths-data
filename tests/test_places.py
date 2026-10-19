import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "builder"))
import places  # noqa: E402


class PlacesTest(unittest.TestCase):

    def test_split_address(self):
        self.assertEqual(places.split_address("1166 Oak St, Eugene, OR 97401, USA"), ("Eugene", "OR", "97401"))
        self.assertEqual(places.split_address("12 Main St, Bend, OR 97701-1234"), ("Bend", "OR", "97701"))
        self.assertEqual(places.split_address("1 Ave SW, Calgary, AB T2P 1J9, Canada"), ("Calgary", "AB", None))
        self.assertEqual(places.split_address("Springfield, OR"), ("Springfield", "OR", None))
        self.assertIsNone(places.split_address("Online"))
        self.assertIsNone(places.split_address("123 Main St, 97401"))

    def test_build_uses_the_middle_meeting_and_skips_approximate_ones(self):
        meetings = [
            {"formatted_address": "1 A St, Eugene, OR 97401, USA", "latitude": 44.05, "longitude": -123.09},
            {"formatted_address": "2 B St, Eugene, OR 97401, USA", "latitude": "44.06", "longitude": "-123.10"},
            {"formatted_address": "3 C St, Eugene, OR 97402, USA", "latitude": 44.04, "longitude": -123.12},
            # Geocoded to the wrong coast: the median ignores it.
            {"formatted_address": "4 D St, Eugene, OR 97401, USA", "latitude": 40.7, "longitude": -74.0},
            {"formatted_address": "Eugene, OR, USA", "latitude": 44.0, "longitude": -123.0, "approximate": "yes"},
            {"formatted_address": "Online", "latitude": 0, "longitude": 0},
        ]
        with tempfile.TemporaryDirectory() as d:
            Path(d, "a.json").write_text(json.dumps(meetings), encoding="utf-8")
            Path(d, "bad.json").write_text("{}", encoding="utf-8")
            index = places.build(d)
        self.assertEqual(index["places"], [["Eugene", "OR", 44.045, -123.095, 4]])
        self.assertEqual(index["zips"]["97402"], [44.04, -123.12])
        self.assertEqual(index["zips"]["97401"], [44.05, -123.09])


if __name__ == "__main__":
    unittest.main()
