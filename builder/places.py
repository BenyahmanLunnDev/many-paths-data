"""
A small index of towns and ZIP codes, built from the addresses of the meetings themselves,
so the web version can find "Eugene, OR" or "97401" without sending what someone typed
to a search service. Every place in it has at least one meeting, which is the point.

    {"places": [["Eugene", "OR", 44.052, -123.091, 312], ...],   # town, state, lat, lng, meetings
     "zips": {"97401": [44.05, -123.09], ...}}
"""
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

# A Google "plus code" some lists put in front of the town: "PW9G+RRP Hilo".
PLUS_CODE = re.compile(r"^[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,3}\s+")

# Places people name that aren't a town in any address: islands, and towns in places whose AA
# lists aren't shared yet (NA's meetings there still come from NA's own database, asked live).
# [name, state, lat, lng, radius in miles that counts as "on" it]
EXTRA = [
    ["Maui", "HI", 20.80, -156.33, 30],
    ["Oahu", "HI", 21.47, -157.98, 25],
    ["Kauai", "HI", 22.06, -159.50, 20],
    ["Hawaii Island (Big Island)", "HI", 19.60, -155.50, 60],
    ["Molokai", "HI", 21.13, -157.02, 25],
    ["Lanai", "HI", 20.83, -156.92, 12],
    ["Honolulu", "HI", 21.307, -157.858, 3],
    ["Kailua (Oahu)", "HI", 21.402, -157.739, 3],
    ["Pearl City", "HI", 21.397, -157.975, 3],
    ["San Juan", "PR", 18.466, -66.106, 4],
    ["Ponce", "PR", 18.011, -66.614, 4],
    ["Mayaguez", "PR", 18.201, -67.140, 4],
    ["Bayamon", "PR", 18.399, -66.155, 4],
    ["Hagatna", "GU", 13.475, 144.750, 4],
    ["Tamuning", "GU", 13.488, 144.781, 4],
    ["Charlotte Amalie", "VI", 18.342, -64.931, 4],
]

# "OR 97401", "OR 97401-1234", "AB T2P 1J9", or just "OR"
STATE_ZIP = re.compile(r"^([A-Z]{2})(?:\s+(\d{5})(?:-\d{4})?|\s+([A-Z]\d[A-Z])\s?\d[A-Z]\d)?$")
COUNTRY = {"usa", "us", "united states", "canada"}


def split_address(address):
    """(town, state, zip) from "1166 Oak St, Eugene, OR 97401, USA", else None."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if parts and parts[-1].lower() in COUNTRY:
        parts = parts[:-1]
    if len(parts) < 2:
        return None
    m = STATE_ZIP.match(parts[-1])
    if not m:
        return None
    town = PLUS_CODE.sub("", parts[-2]).strip()
    if not re.search(r"[A-Za-z]", town) or re.match(r"^\d", town) or len(town) > 40:
        return None
    return town, m.group(1), m.group(2)


def _miles(lat1, lng1, lat2, lng2):
    from math import asin, cos, radians, sin, sqrt
    a = sin(radians(lat2 - lat1) / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lng2 - lng1) / 2) ** 2
    return 2 * 3958.8 * asin(sqrt(min(1, a)))


def coordinate(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v != 0 else None


def build(feed_dir):
    towns = defaultdict(list)
    zips = defaultdict(list)
    names = {}
    for path in Path(feed_dir).glob("*.json"):
        try:
            meetings = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(meetings, list):
            continue
        for m in meetings:
            if not isinstance(m, dict) or str(m.get("approximate", "")).lower() == "yes":
                continue
            lat, lng = coordinate(m.get("latitude")), coordinate(m.get("longitude"))
            address = m.get("formatted_address")
            if lat is None or lng is None or not isinstance(address, str):
                continue
            found = split_address(address)
            if not found:
                continue
            town, state, zip_code = found
            key = (town.lower(), state)
            names.setdefault(key, town)
            towns[key].append((lat, lng))
            if zip_code:
                zips[zip_code].append((lat, lng))

    def middle(points):
        # The median shrugs off the odd meeting geocoded to the wrong side of the country.
        return round(statistics.median(p[0] for p in points), 3), round(statistics.median(p[1] for p in points), 3)

    places = [[names[k], k[1], *middle(v), len(v)] for k, v in towns.items()]
    known = {(p[0].lower(), p[1]) for p in places}
    for name, state, lat, lng, radius in EXTRA:
        if (name.lower(), state) in known:
            continue
        # How many listed meetings are on the island (or in the town), so busy ones sort first.
        count = sum(p[4] for p in places if p[1] == state and _miles(lat, lng, p[2], p[3]) <= radius)
        places.append([name, state, lat, lng, count])
    places.sort(key=lambda p: -p[4])
    return {"places": places, "zips": {z: list(middle(v)) for z, v in sorted(zips.items())}}
