"""
Weekly meetings from a public calendar (an .ics feed, e.g. a Google Calendar a group embeds on
its website), turned into Meeting Guide records. Only weekly series still running are kept;
one-off events and monthly service meetings are left out.

Southern Idaho NA's calendars look like this, and the reader is built around that shape:

    SUMMARY:POCATELLO - Never Alone
    LOCATION:745 S 1st Ave\\, Pocatello\\, ID 83201\\, USA
    DESCRIPTION:(O)(BS)(WC)\\nLibrary Room
    RRULE:FREQ=WEEKLY;BYDAY=SA
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

ICAL_DAYS = {"SU": 0, "MO": 1, "TU": 2, "WE": 3, "TH": 4, "FR": 5, "SA": 6}

# NA meeting format codes as groups write them in calendar text, to Meeting Guide codes the
# apps understand (or plain words, which the apps show as they are).
FORMATS = {
    "O": "O", "OPEN": "O", "C": "C", "CLOSED": "C", "WC": "X", "W/C": "X", "BT": "BT", "JFT": "Just for Today",
    "BS": "Book study", "IP": "IP study", "IW": "It Works", "SPAD": "Spiritual Principle a Day", "ST": "ST",
    "SWG": "Step Working Guide", "LC": "Living Clean", "SP": "SP", "D": "D", "CL": "CAN", "CAN": "CAN",
    "CANDLELIGHT": "CAN", "M": "M", "W": "W", "NC": "No children", "CW": "Children welcome", "BEG": "BE",
    "NS": "Non-smoking", "QA": "Q&A", "TO": "Topic", "GP": "Guiding Principles", "TR": "TR",
}
FORMAT_CODE = re.compile(r"\(([A-Za-z/&+0-9 ]{1,12})\)")
JOIN = re.compile(r"https?://[^\s<>\"']*(?:zoom\.us|meet\.google|teams\.microsoft|teams\.live|webex|gotomeet)[^\s<>\"']*")
SERVICE = re.compile(r"\b(service committee|asc|area service|sub-?committee|business meeting|h&i|public relations|"
                     r"activities|outreach|literature committee|workshop|convention|campout|picnic|dance)\b", re.I)
ADDRESS = re.compile(r"(\d+[^,]*?)[,\s]+([A-Za-z .'-]+?),?\s+([A-Z]{2})\b\.?\s*(\d{5})?")


def unescape(value):
    return (value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\").strip())


def parse(text):
    """VEVENTs as lists of (name, params, value), with folded lines joined."""
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()
    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = []
        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            current.append((name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value))
    return events


def first(event, name):
    return next(((p, v) for n, p, v in event if n == name), (None, None))


def when(params, value, default_tz):
    """A DTSTART-style value as an aware datetime, or None for all-day dates."""
    if not value or (params or {}).get("VALUE") == "DATE" or len(value) == 8:
        return None
    if value.endswith("Z"):
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(default_tz))
    tz = ZoneInfo((params or {}).get("TZID") or default_tz)
    return dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz)


def rule(event):
    _, value = first(event, "RRULE")
    return dict(part.split("=", 1) for part in value.split(";") if "=" in part) if value else None


def split_summary(summary):
    """'POCATELLO - Never Alone' -> ('Pocatello', 'Never Alone'); a summary without a town prefix stays whole."""
    m = re.match(r"^\s*([A-Z][A-Z .']{2,30}?)\s*(?:-|–|:)\s*(.*)$", summary)
    if m and m.group(1).strip().upper() == m.group(1).strip():
        town = m.group(1).strip().title()
        return town, m.group(2).strip()
    if re.fullmatch(r"[A-Z][A-Z .']{2,30}", summary.strip()):
        return summary.strip().title(), ""
    return None, summary.strip()


def formats(text):
    codes, rest = [], text
    for m in FORMAT_CODE.finditer(text):
        raw = m.group(1).strip().upper()
        if raw in FORMATS:
            codes.append(FORMATS[raw])
            rest = rest.replace(m.group(0), " ")
        elif re.fullmatch(r"[0-9.]+ ?H\+?|[0-9]+ ?MIN|[A-Z]{1,4}", raw):
            rest = rest.replace(m.group(0), " ")  # "(1H+)", unknown short codes: noise to readers
    if re.search(r"\bclosed meeting\b", text, re.I) and "C" not in codes:
        codes.append("C")
    if re.search(r"\bopen meeting\b", text, re.I) and "O" not in codes:
        codes.append("O")
    if re.search(r"\bcandle ?light\b", text, re.I) and "CAN" not in codes:
        codes.append("CAN")
    return list(dict.fromkeys(codes)), re.sub(r"[ \t]+", " ", rest).strip()


ROOM = re.compile(r"\s*(?:\b(?:room|rm|suite|ste|unit)\b\.?\s*[\w-]+|#\s*[\w-]+)", re.I)


def split_address(location, town_hint, default_state):
    """(place name, street, city, state, zip) from free text, or Nones where it can't tell."""
    text = re.sub(r",?\s*USA$", "", location.strip())
    m = ADDRESS.search(text)
    if not m:
        return (text or None), None, None, None, None
    street, city, state, zip_code = m.group(1).strip(" ,."), m.group(2).strip(" ,."), m.group(3), m.group(4) or ""
    # "745 S 1st Ave Pocatello, ID" has no comma between the street and the town, so the
    # split can land on either side of "Ave".
    if town_hint and city.lower() != town_hint.lower():
        if street.lower().endswith(" " + town_hint.lower()):
            street, city = street[: -len(town_hint)].strip(" ,"), town_hint
        elif city.lower().endswith(" " + town_hint.lower()):
            street, city = f"{street} {city[: -len(town_hint)].strip()}", town_hint
    # "237 N Water Room 206" is found by its street; the room is in the notes.
    street = re.sub(r"\s+", " ", ROOM.sub("", street)).strip(" ,.")
    place = text[: m.start()].strip(" ,") or None
    return place, street, city, state or default_state, zip_code


def dates(event, name, default_tz):
    """Every date listed in [name] lines (EXDATE can repeat and hold several values)."""
    out = set()
    for n, params, value in event:
        if n == name:
            for v in value.split(","):
                moment = when(params, v, default_tz)
                if moment:
                    out.add(moment.date().isoformat())
    return out


def meetings(text, source, today=None):
    """Meeting Guide records, plus {address key: (street, city, state, zip)} to geocode."""
    today = today or dt.date.today()
    default_tz = source.get("timezone") or "America/Denver"
    events = parse(text)
    # Instances moved or cancelled ("RECURRENCE-ID") don't meet at their usual time that day.
    moved = {}
    for e in events:
        rid = first(e, "RECURRENCE-ID")
        if rid[1]:
            start = when(*rid, default_tz)
            if start:
                moved.setdefault(first(e, "UID")[1], set()).add(start.date().isoformat())
    out, addresses = [], {}
    for e in events:
        if first(e, "RECURRENCE-ID")[1] or (first(e, "STATUS")[1] or "").upper() == "CANCELLED":
            continue
        r = rule(e)
        if not r or r.get("FREQ") != "WEEKLY" or r.get("INTERVAL", "1") != "1":
            continue
        start = when(*first(e, "DTSTART"), default_tz)
        if not start:
            continue
        until = None
        if "UNTIL" in r:
            until = dt.datetime.strptime(r["UNTIL"][:8], "%Y%m%d").date()
            if until < today:
                continue
        days = [ICAL_DAYS[d[-2:]] for d in r.get("BYDAY", "").split(",") if d[-2:] in ICAL_DAYS and not d[:-2]]
        if r.get("BYDAY") and not days:
            continue  # "1SU": monthly in disguise
        days = days or [(start.weekday() + 1) % 7]
        if "COUNT" in r:
            last = start.date() + dt.timedelta(weeks=-(-int(r["COUNT"]) // len(days)))
            if last < today:
                continue
            until = last

        summary = unescape(first(e, "SUMMARY")[1] or "")
        description = re.sub(r"<[^>]+>", " ", unescape(first(e, "DESCRIPTION")[1] or ""))
        if not summary or SERVICE.search(summary):
            continue
        town, name = split_summary(summary)
        codes, name = formats(name)
        more_codes, notes = formats(description)
        codes = list(dict.fromkeys(codes + more_codes))
        location = unescape(first(e, "LOCATION")[1] or "")
        link = (JOIN.findall(location + " " + description) or [None])[0]
        place, street, city, state, zip_code = split_address(JOIN.sub("", location), town, source.get("state"))

        end = when(*first(e, "DTEND"), default_tz)
        minutes = int((end - start).total_seconds() // 60) if end and end > start else 60
        finish = start + dt.timedelta(minutes=minutes)
        # A series that starts later doesn't meet before its first date.
        skip = sorted({(today + dt.timedelta(days=i)).isoformat() for i in range(0, 56)
                       if (today + dt.timedelta(days=i)) < start.date()
                       and ((today + dt.timedelta(days=i)).weekday() + 1) % 7 in days}
                      | {d for d in moved.get(first(e, "UID")[1], set()) | dates(e, "EXDATE", default_tz)
                         if d >= today.isoformat()})
        modified = first(e, "LAST-MODIFIED")[1]
        m = {
            "id": (first(e, "UID")[1] or summary).split("@")[0],
            "name": name or (f"{town} NA meeting" if town else summary),
            "day": days,
            "time": start.strftime("%H:%M"),
            "end_time": finish.strftime("%H:%M"),
            "timezone": str(start.tzinfo) if isinstance(start.tzinfo, ZoneInfo) else default_tz,
            "types": codes,
            "location": place,
            "notes": notes,
            "conference_url": link,
            "url": source.get("website"),
            "updated": f"{modified[:4]}-{modified[4:6]}-{modified[6:8]}" if modified else today.isoformat(),
            "skip": skip,
            "until": until.isoformat() if until else None,
            "fellowship": source.get("fellowship"),
        }
        if street and city:
            m["formatted_address"] = f"{street}, {city}, {state} {zip_code}".strip()
            key = "|".join(x.strip().lower() for x in (street, city, state, zip_code))
            addresses[key] = (street, city, state, zip_code)
            m["_geo"] = key
            m["attendance_option"] = "hybrid" if link else "in_person"
        elif link:
            m["attendance_option"] = "online"
        else:
            continue  # nowhere to go
        out.append({k: v for k, v in m.items() if v not in (None, "", [])})
    return out, addresses
