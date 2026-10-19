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
    town = parts[-2]
    if not re.search(r"[A-Za-z]", town) or re.match(r"^\d", town) or len(town) > 40:
        return None
    return town, m.group(1), m.group(2)


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
    places.sort(key=lambda p: -p[4])
    return {"places": places, "zips": {z: list(middle(v)) for z, v in sorted(zips.items())}}
