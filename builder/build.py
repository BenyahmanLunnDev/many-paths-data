"""
Daily build of the Many Paths meeting data.

Reads every open meeting list named in sources/, trims each to the fields the app uses,
and writes a static site that GitHub Pages serves:

    v1/feeds/<source id>.json   one list, trimmed
    v1/manifest.json            what was fetched, when, and what failed
    v1/curated_meetings.json    hand-entered groups (Restored Connections, ...)
    v1/helplines.json, v1/aa_helplines.json
    v1/sources.json, v1/places.json  what the web version reads to pick lists and find towns
    index.html                  a readable status page

Restricted lists are never fetched unless the group gave this project a sharing key,
supplied through the SOURCE_KEYS secret ("id=key;id2=key2"). A list that fails today
falls back to the copy published yesterday, so a site being down never empties the app.

    python builder/build.py --out site --status status/latest.json
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import extra
import places

ROOT = Path(__file__).resolve().parent.parent
PAGES = os.environ.get("PAGES_BASE", "https://benyahmanlunndev.github.io/many-paths-data/")
# Says who's asking and where to read about it. (Some hosts refuse anything containing "compatible;".)
UA = "Mozilla/5.0 ManyPaths/1.0 (daily meeting-list copy; github.com/BenyahmanLunnDev/many-paths-data)"

# Fields the app reads from a Meeting Guide (12 Step Meeting List) record. Everything
# else (edit links, authors, payment handles, feedback emails) is dropped.
KEEP = {
    "id", "slug", "name", "day", "time", "end_time", "types", "attendance_option", "approximate",
    "latitude", "longitude", "formatted_address", "location", "location_notes", "notes", "timezone",
    "conference_url", "conference_url_notes", "conference_phone", "phone", "contact_1_phone", "url",
    "updated", "fellowship", "skip", "until",
}

BMLT_FIELDS = (
    "id_bigint,meeting_name,weekday_tinyint,start_time,duration_time,time_zone,formats,venue_type,"
    "location_text,location_info,location_street,location_municipality,location_province,"
    "location_postal_code_1,latitude,longitude,comments,virtual_meeting_link,"
    "virtual_meeting_additional_info,phone_meeting_number,lang_enum"
)


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def get_json(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get_text(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,text/csv,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def age_days(iso):
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds() / 86400
    except (TypeError, ValueError):
        return 1e9


FORCE = False  # --force: re-read pages and sheets even if the last copy is recent


def build_extra(source, cache):
    """A public meeting page or sheet, re-read only when the last copy is older than refreshDays."""
    sid = source["id"]
    old = previous_manifest.get("sources", {}).get(sid, {})
    if not FORCE and old.get("status") == "ok" and age_days(old.get("fetchedAt")) < source.get("refreshDays", 1) - 0.1:
        try:
            return get_json(PAGES + f"v1/feeds/{sid}.json", timeout=60), dict(old)
        except Exception:  # noqa: BLE001 - fall through and rebuild
            pass
    reader = extra.read_tsml_page if source["type"] == "tsml_page" else extra.read_sheet
    try:
        data = reader(source, get_text, cache, UA)
        if not data:
            raise ValueError("no meetings found")
        if old.get("count") and len(data) < old["count"] / 2:
            # A sudden halving is far more likely a failed lookup than half the meetings closing.
            raise ValueError(f"only {len(data)} meetings, down from {old['count']}")
        return data, {"status": "ok", "count": len(data), "fetchedAt": now()}
    except Exception as e:  # noqa: BLE001
        error = str(e)[:120] or type(e).__name__
        try:
            previous = get_json(PAGES + f"v1/feeds/{sid}.json", timeout=60)
            return previous, {"status": "previous", "count": len(previous), "fetchedAt": old.get("fetchedAt"), "error": error}
        except Exception:  # noqa: BLE001
            return None, {"status": "failed", "error": error}


def feed_key(url):
    return urllib.parse.urlsplit(url)._replace(scheme="", query="", fragment="").geturl().lstrip("/").removeprefix("www.").lower()


def load_sources():
    """Hand-maintained sources win over generated ones for the same feed, as in the app."""
    manual = json.loads((ROOT / "sources/sources.json").read_text(encoding="utf-8"))
    generated = json.loads((ROOT / "sources/aa_sources.json").read_text(encoding="utf-8"))
    seen = {feed_key(s["url"]) for s in manual if s.get("url")}
    return manual + [s for s in generated if feed_key(s["url"]) not in seen]


def web_sources():
    """Every list, merged the way the Android app merges its copies: hand-maintained entries win."""
    manual = json.loads((ROOT / "sources/sources.json").read_text(encoding="utf-8"))
    seen = {feed_key(s["url"]) for s in manual if s.get("url")}
    rest = [s for name in ("aa_sources.json", "sheet_sources.json")
            for s in json.loads((ROOT / "sources" / name).read_text(encoding="utf-8"))]
    return manual + [s for s in rest if not s.get("url") or feed_key(s["url"]) not in seen]


def parse_keys(text):
    keys = {}
    for pair in (text or "").split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() and v.strip():
                keys[k.strip()] = v.strip()
    return keys


def trim(record):
    return {k: v for k, v in record.items() if k in KEEP and v not in (None, "", [])}


def request_url(source, keys):
    if source["kind"] == "BMLT_ONLINE":
        base = source["url"].rstrip("/") + "/"
        return (base + "client_interface/json/?switcher=GetSearchResults&venue_types=2&data_field_key="
                + urllib.parse.quote(BMLT_FIELDS, safe=""))
    url = source["url"]
    key = keys.get(source["id"])
    if key:
        url += ("&" if "?" in url else "?") + "key=" + urllib.parse.quote(key)
    return url


def wanted(source, keys):
    if source.get("kind") not in ("TSML", "BMLT_ONLINE"):
        return False
    if source.get("url", "").startswith(PAGES):
        return False  # published by this job itself (sheets, public pages)
    return not source.get("restricted") or source["id"] in keys


def fetch_one(source, keys):
    sid = source["id"]
    try:
        data = get_json(request_url(source, keys))
        if not isinstance(data, list):
            raise ValueError("not a meeting list")
        if source["kind"] == "TSML":
            data = [trim(m) for m in data if isinstance(m, dict)]
        if not data:
            raise ValueError("empty list")
        return sid, data, {"status": "ok", "count": len(data), "fetchedAt": now()}
    except Exception as e:  # noqa: BLE001 - one broken site must not stop the build
        error = f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else (str(e)[:120] or type(e).__name__)
        try:
            previous = get_json(PAGES + f"v1/feeds/{sid}.json", timeout=60)
            old = previous_manifest.get("sources", {}).get(sid, {})
            return sid, previous, {"status": "previous", "count": len(previous),
                                   "fetchedAt": old.get("fetchedAt"), "error": error}
        except Exception:  # noqa: BLE001
            return sid, None, {"status": "failed", "error": error}


previous_manifest = {}


def write_index(path, manifest, sources):
    rows = []
    names = {s["id"]: s for s in sources}
    order = {"failed": 0, "previous": 1, "ok": 2}
    for sid, st in sorted(manifest["sources"].items(), key=lambda kv: (order.get(kv[1]["status"], 3), kv[0])):
        s = names.get(sid, {})
        rows.append(
            f"<tr class='{st['status']}'><td>{html.escape(s.get('name', sid))}</td>"
            f"<td>{html.escape(s.get('area') or '')}</td><td>{st['status']}</td>"
            f"<td>{st.get('count', '')}</td><td>{html.escape(st.get('error', ''))}</td></tr>"
        )
    counts = manifest["counts"]
    path.write_text(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Many Paths data</title>
<style>
:root{{--bg:#eff4f3;--fg:#172b31;--muted:#4a5759;--card:#fff;--line:#c3cdcc;--bad:#8e1f25;--warn:#8a5100}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1415;--fg:#dde4e4;--muted:#bec8c8;--card:#172021;--line:#3f4949;--bad:#ffb4b4;--warn:#ffb866}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:960px;margin:auto;padding:16px}}h1{{font-size:24px}}p{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;background:var(--card)}}td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
tr.failed td:nth-child(3){{color:var(--bad);font-weight:600}}tr.previous td:nth-child(3){{color:var(--warn)}}
.wrap{{overflow-x:auto}}
</style></head><body><main>
<h1>Many Paths meeting data</h1>
<p>Built {manifest['generatedAt']}. {counts['ok']} lists fresh today, {counts['previous']} kept from an earlier day,
{counts['failed']} unavailable, {counts['meetings']} meetings in all. Every list belongs to the group that publishes it;
this copy is refreshed daily for the <a href="https://github.com/BenyahmanLunnDev/many-paths-data">Many Paths</a> app.
Restricted lists are not copied without the group's permission.</p>
<div class="wrap"><table><tr><th>List</th><th>Area</th><th>Today</th><th>Meetings</th><th>Problem</th></tr>
{''.join(rows)}</table></div></main></body></html>
""", encoding="utf-8")


def main():
    global previous_manifest
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--status", help="also write a small status summary here (committed daily)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", help="comma-separated source ids, for testing")
    ap.add_argument("--force", action="store_true", help="re-read pages and sheets now")
    args = ap.parse_args()
    global FORCE
    FORCE = args.force

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "v1/feeds").mkdir(parents=True)

    keys = parse_keys(os.environ.get("SOURCE_KEYS"))
    sources = load_sources()
    todo = [s for s in sources if wanted(s, keys)]
    if args.only:
        only = set(args.only.split(","))
        todo = [s for s in todo if s["id"] in only]
    try:
        previous_manifest = get_json(PAGES + "v1/manifest.json", timeout=60)
    except Exception:  # noqa: BLE001 - first run, or Pages not up yet
        previous_manifest = {}

    statuses = {}
    with cf.ThreadPoolExecutor(args.workers) as pool:
        for sid, data, st in pool.map(lambda s: fetch_one(s, keys), todo):
            statuses[sid] = st
            if data is not None:
                (out / f"v1/feeds/{sid}.json").write_text(
                    json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # Public meeting pages and sheets, with addresses looked up (and remembered between runs).
    # Known addresses ship with the repo (sources/geocode_cache.json, refreshed from a home
    # connection); the published cache adds any looked up by earlier runs.
    cache = json.loads((ROOT / "sources/geocode_cache.json").read_text(encoding="utf-8"))
    try:
        for k, v in get_json(PAGES + "v1/geocode-cache.json", timeout=60).items():
            if v is not None:
                cache.setdefault(k, v)
    except Exception:  # noqa: BLE001 - first run
        pass
    extras = [s for s in json.loads((ROOT / "sources/extra_sources.json").read_text(encoding="utf-8")) if s.get("enabled", True)]
    if args.only:
        extras = [s for s in extras if s["id"] in only]
    for source in extras:
        data, st = build_extra(source, cache)
        statuses[source["id"]] = st
        if data is not None:
            (out / f"v1/feeds/{source['id']}.json").write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "v1/geocode-cache.json").write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    sources = sources + extras  # so the status page names them

    # Hand-maintained files ride along so they can be updated without an app release.
    curated = json.loads((ROOT / "sources/curated_meetings.json").read_text(encoding="utf-8"))
    (out / "v1/feeds/local.json").write_text(json.dumps(curated, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    statuses["local"] = {"status": "ok", "count": len(curated), "fetchedAt": now()}
    for name in ("curated_meetings.json", "helplines.json", "aa_helplines.json"):
        shutil.copy(ROOT / "sources" / name, out / "v1" / name)

    # For the web version: every list it can show, and the towns and ZIP codes it can
    # search without sending what someone typed to a lookup service.
    (out / "v1/sources.json").write_text(
        json.dumps(web_sources(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "v1/places.json").write_text(
        json.dumps(places.build(out / "v1/feeds"), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    counts = {k: sum(1 for s in statuses.values() if s["status"] == k) for k in ("ok", "previous", "failed")}
    counts["meetings"] = sum(s.get("count", 0) for s in statuses.values())
    manifest = {"version": 1, "generatedAt": now(), "counts": counts, "sources": statuses}
    (out / "v1/manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    write_index(out / "index.html", manifest, sources)
    # Static pages, like the app's privacy policy, are served at the site root.
    for page in (ROOT / "pages").glob("*.html"):
        shutil.copy(page, out / page.name)
    (out / ".nojekyll").write_text("", encoding="utf-8")

    if args.status:
        p = Path(args.status)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
