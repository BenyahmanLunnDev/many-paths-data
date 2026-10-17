"""
Lists that aren't served as a Meeting Guide feed, turned into one:

  tsml_page  the public meeting page of a 12 Step Meeting List site whose feed isn't shared
             (read like a visitor reads it; the restricted feed itself is never touched)
  sheet      a public Google Sheet in (roughly) the Meeting Guide column layout

Addresses get coordinates from the US Census Bureau geocoder, cached between runs.
"""
import csv
import datetime as dt
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
import uuid

DAYS = {d: i for i, d in enumerate(["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"])}
DAYS.update({d[:3]: i for d, i in list(DAYS.items())})

# Words the 12 Step Meeting List shows on public pages, back to Meeting Guide type codes.
TYPE_CODES = {
    "open": "O", "closed": "C", "wheelchair access": "X", "wheelchair accessible": "X", "online meeting": "ONL",
    "online": "ONL", "big book": "B", "literature": "LIT", "12 steps & 12 traditions": "12x12", "women": "W",
    "men": "M", "spanish": "S", "wheelchair-accessible bathroom": "XB", "discussion": "D", "young people": "Y",
    "lgbtq": "LGBTQ", "speaker": "SP", "babysitting available": "BA", "people of color": "POC", "meditation": "MED",
    "candlelight": "CAN", "english": "EN", "fragrance free": "FF", "outdoor": "OUT", "child-friendly": "CF",
    "tradition study": "TR", "indigenous": "NDG", "dual diagnosis": "DD", "step study": "ST", "newcomer": "BE",
    "location temporarily closed": "TC", "temporary closure": "TC", "secular": "A", "native american": "N",
    "as bill sees it": "ABSI", "daily reflections": "DR", "grapevine": "GR", "living sober": "LS",
    "transgender": "T", "gay": "G", "lesbian": "L", "seniors": "SEN", "professionals": "P", "11th step meditation": "11",
}


def type_codes(words):
    out = []
    for w in words:
        w = w.strip()
        if w:
            out.append(TYPE_CODES.get(w.lower(), w))
    return out


def clock(text):
    """'7:00 am', '19:00', '7 PM', 'Noon' -> '07:00' / '19:00' / '12:00'; None if unreadable."""
    word = (text or "").strip().lower()
    if word in ("noon", "12 noon", "12:00 noon"):
        return "12:00"
    if word == "midnight":
        return "00:00"
    m = re.match(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?\s*m?\.?", (text or "").lower())
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "p" and h < 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mins:02d}" if h < 24 and mins < 60 else None


# ---------------------------------------------------------------- geocoding

CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


def geocode(addresses, cache, ua):
    """addresses: {key: (street, city, state, zip)}. Fills cache[key] = [lat, lng] or None."""
    todo = {k: v for k, v in addresses.items() if k not in cache and v[0]}
    if not todo:
        return
    keys = list(todo)
    for start in range(0, len(keys), 5000):
        chunk = keys[start:start + 5000]
        ids = {str(i): k for i, k in enumerate(chunk)}
        rows = io.StringIO()
        w = csv.writer(rows)
        for i, k in ids.items():
            w.writerow([i, *todo[k]])
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\nPublic_AR_Current\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"addressFile\"; filename=\"a.csv\"\r\n"
            f"Content-Type: text/csv\r\n\r\n{rows.getvalue()}\r\n--{boundary}--\r\n"
        ).encode("utf-8")
        req = urllib.request.Request(CENSUS_BATCH, data=body, headers={
            "User-Agent": ua, "Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=600) as r:
            result = r.read().decode("utf-8", "replace")
        for row in csv.reader(io.StringIO(result)):
            if len(row) >= 6 and row[0] in ids:
                key = ids[row[0]]
                if row[2] == "Match" and "," in row[5]:
                    lng, lat = (float(x) for x in row[5].split(","))
                    cache[key] = [round(lat, 6), round(lng, 6)]
                else:
                    cache[key] = None


def address_key(street, city, state, zip_code):
    return "|".join(x.strip().lower() for x in (street, city, state, zip_code))


# ---------------------------------------------------------------- 12 Step Meeting List public page

def read_tsml_page(source, fetch_text, cache, ua):
    page = fetch_text(source["page"])
    today = dt.date.today().isoformat()
    meetings, addresses = [], {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = dict(re.findall(r'<td class="([a-z]+)[^"]*"[^>]*>(.*?)</td>', row, re.S))
        if "name" not in cells or "time" not in cells:
            continue
        text = lambda c: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cells.get(c, "")))).strip()
        spans = [html.unescape(s).strip() for s in re.findall(r"<span>(.*?)</span>", cells["time"], re.S)]
        day = DAYS.get(spans[0].lower()) if spans else None
        start = clock(spans[1]) if len(spans) > 1 else None
        link = re.search(r'href="([^"]+)"', cells["name"])
        attendance = re.search(r'attendance-([a-z_]+)', cells.get("location", ""))
        attendance = attendance.group(1) if attendance else "in_person"
        if day is None or start is None or attendance == "inactive":
            continue
        location = re.search(r'location-name[^>]*>(.*?)</div>', cells.get("location", ""), re.S)
        # The ZIP code only appears in the address cell's sort key: "1166-oak-st-eugene-or-97401-usa".
        sort_key = re.search(r'<td class="address[^"]*" data-sort="([^"]*)"', row)
        zip_match = re.search(r"-(\d{5})-usa", sort_key.group(1)) if sort_key else None
        zip_code = zip_match.group(1) if zip_match else ""
        street, city = text("address"), text("region")
        url = link.group(1).split("?")[0] if link else source.get("website")
        m = {
            "id": url.rstrip("/").rsplit("/", 1)[-1] if url else f"{day}-{start}",
            # Just the link text: the cell also carries small tags like "Women".
            "name": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", link_text.group(1)))).strip()
            if (link_text := re.search(r"<a[^>]*>(.*?)</a>", cells["name"], re.S)) else text("name"),
            "day": day, "time": start, "timezone": source["timezone"],
            "attendance_option": attendance, "types": type_codes(text("types").split(",")),
            "location": html.unescape(re.sub(r"\s+", " ", location.group(1))).strip() if location else "",
            "url": url, "updated": today,
        }
        if street and attendance != "online":
            m["formatted_address"] = f"{street}, {city}, {source['state']} {zip_code}".strip()
            key = address_key(street, city, source["state"], zip_code)
            addresses[key] = (street, city, source["state"], zip_code)
            m["_geo"] = key
        meetings.append(m)
    add_details(meetings, fetch_text)
    return finish(meetings, addresses, cache, ua)


JOIN = re.compile(r'href="(https?://[^"]*(?:zoom\.us|meet\.google|teams\.microsoft|teams\.live|webex|gotomeet)[^"]*)"')


def page_text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def add_details(meetings, fetch_text, pause=0.5):
    """Each meeting's own page has the join link and notes like which door to use.
    Read them one at a time with a short pause, as a person clicking through would."""
    seen = {}
    for m in meetings:
        url = m.get("url")
        if not url or "/meetings/" not in url:
            continue
        if url not in seen:
            try:
                page = fetch_text(url)
                main = page[page.find("<main"):] if "<main" in page else page
                details = {}
                join = JOIN.search(main)
                if join:
                    details["conference_url"] = html.unescape(join.group(1))
                for cls, field in (("location-notes", "location_notes"), ("meeting-notes", "notes")):
                    block = re.search(rf'class="[^"]*{cls}[^"]*"[^>]*>(.*?)</(?:div|section|p|li)>', main, re.S)
                    if block and page_text(block.group(1)):
                        details[field] = page_text(block.group(1))[:600]
                seen[url] = details
            except Exception:  # noqa: BLE001 - the list entry is still useful without its details
                seen[url] = {}
            time.sleep(pause)
        for k, v in seen[url].items():
            m.setdefault(k, v)


# ---------------------------------------------------------------- Google Sheets

HEADERS = {
    "day": ["day"], "time": ["time", "time (pt)", "start time", "start"], "end_time": ["end time", "end"],
    "name": ["name", "meeting name"], "location": ["location", "location name"], "address": ["address", "street"],
    "formatted_address": ["formatted address"], "city": ["city"], "state": ["state"],
    "zip": ["postal code", "zip", "zip code"], "types": ["types", "type"], "notes": ["notes"],
    "conference_url": ["conference url", "meeting link", "zoom link"], "conference_url_notes": ["conference url notes"],
    "conference_phone": ["conference phone"], "id": ["id", "slug"], "timezone": ["timezone"], "url": ["url"],
}


def read_sheet(source, fetch_text, cache, ua):
    rows = list(csv.reader(io.StringIO(fetch_text(source["sheet"]))))
    header_at = next(i for i, r in enumerate(rows[:10]) if sum(1 for c in r if c.strip()) >= 4)
    header = [re.sub(r"\s+", " ", h).strip().lower() for h in rows[header_at]]
    col = {}
    for field, names in HEADERS.items():
        for n in names:
            if n in header:
                col[field] = header.index(n)
                break
    get = lambda r, f: r[col[f]].strip() if f in col and col[f] < len(r) else ""
    today = dt.date.today().isoformat()
    meetings, addresses = [], {}
    for n, r in enumerate(rows[header_at + 1:]):
        name, start = get(r, "name"), clock(get(r, "time"))
        days = [DAYS[d.strip().lower()] for d in re.split(r"[,/&]| and ", get(r, "day")) if d.strip().lower() in DAYS]
        if not name or not start or not days:
            continue
        link = get(r, "conference_url")
        street, city, state, zip_code = get(r, "address"), get(r, "city"), get(r, "state") or source["state"], get(r, "zip")
        if not street and get(r, "formatted_address"):
            # "2590 1st St, Napa, CA 94558, USA" -> street, city, state, ZIP. A bare "Napa, CA, USA" has no street.
            parts = [p.strip() for p in get(r, "formatted_address").split(",")]
            if len(parts) >= 3 and re.match(r"\d", parts[0]):
                street, city = parts[0], parts[1]
                sz = re.match(r"([A-Z]{2})\s*(\d{5})?", parts[2])
                if sz:
                    state, zip_code = sz.group(1), sz.group(2) or ""
        for day in days:
            m = {
                "id": get(r, "id") or f"row{n}", "name": name, "day": day, "time": start,
                "end_time": clock(get(r, "end_time")), "timezone": get(r, "timezone") or source["timezone"],
                "types": type_codes(re.split(r"[,;]", get(r, "types"))), "location": get(r, "location"),
                "notes": get(r, "notes"), "conference_url": link if link.startswith("http") else "",
                "conference_url_notes": get(r, "conference_url_notes"), "conference_phone": get(r, "conference_phone"),
                "url": get(r, "url") or source.get("website"), "updated": today,
            }
            if street:
                m["formatted_address"] = ", ".join(x for x in (street, city, f"{state} {zip_code}".strip()) if x)
                key = address_key(street, city, state, zip_code)
                addresses[key] = (street, city, state, zip_code)
                m["_geo"] = key
                m["attendance_option"] = "hybrid" if m["conference_url"] else "in_person"
            elif m["conference_url"] or m["conference_phone"]:
                m["attendance_option"] = "online"
            else:
                continue
            meetings.append({k: v for k, v in m.items() if v not in (None, "", [])})
    return finish(meetings, addresses, cache, ua)


def finish(meetings, addresses, cache, ua):
    geocode(addresses, cache, ua)
    out = []
    for m in meetings:
        key = m.pop("_geo", None)
        point = cache.get(key) if key else None
        if point:
            m["latitude"], m["longitude"] = point
        elif m.get("attendance_option") == "in_person":
            continue  # can't place it on the map, and it has no online part
        out.append(m)
    return out
