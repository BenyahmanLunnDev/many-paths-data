"""
Turns tools/public_pages.json (from find_public_pages.py) into sources/copy_sources.json:
a dated weekly copy of each restricted AA list's public meeting page, like EVI's.

Also looks up the addresses on those pages from here, because the US Census geocoder
refuses GitHub's servers, and ships them in sources/geocode_cache.json. Addresses that
neither the Census nor OpenStreetMap can place are stored as [] so the daily job doesn't
ask again every morning.

    python tools/make_copy_sources.py            # add lists not copied yet; keep the rest
    python tools/make_copy_sources.py --refresh  # re-read every list
"""
import collections
import json
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "builder"))
import build  # noqa: E402
import extra  # noqa: E402

PAGES = build.PAGES
MIN_ROWS = 20  # a handful of rows means the page isn't really the whole list
SKIP = {"aa-eviaa-org"}  # EVI is already copied (aa-eviaa-public)
DECISION = ("Turned on 2026-10-20 by the project owner for restricted AA lists with a readable public page, "
            "as with EVI: copied weekly, dated, linked; replaced by the group's feed if it shares a key, "
            "removed if it asks.")


def main():
    found = json.loads((ROOT / "tools/public_pages.json").read_text(encoding="utf-8"))
    originals = {s["id"]: s for s in json.loads((ROOT / "sources/sources.json").read_text(encoding="utf-8"))
                 + json.loads((ROOT / "sources/aa_sources.json").read_text(encoding="utf-8"))}
    cache_path = ROOT / "sources/geocode_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    out_path = ROOT / "sources/copy_sources.json"
    existing = {e["copyOf"]: e for e in json.loads(out_path.read_text(encoding="utf-8"))} if out_path.exists() else {}
    refresh = "--refresh" in sys.argv
    entries, addresses, counts = [], {}, {}
    for f in found:
        if f["status"] != "readable" or f.get("rows", 0) < MIN_ROWS or f["id"] in SKIP:
            continue
        if f["id"] in existing and not refresh:
            entries.append(existing[f["id"]])  # copied before; its addresses are already known
            continue
        o = originals[f["id"]]
        page_url = f.get("final") or f["page"]
        time.sleep(1)
        try:
            page = build.get_text(page_url)
        except Exception as e:  # noqa: BLE001
            print(f"skip {f['id']}: {e}", flush=True)
            continue
        meetings, found_addresses = extra.parse_tsml_page(page, {"website": page_url.split("?")[0]})
        if len(meetings) < MIN_ROWS:
            print(f"skip {f['id']}: only {len(meetings)} meetings", flush=True)
            continue
        states = collections.Counter(m.get("_state") for m in meetings if m.get("_state"))
        state = states.most_common(1)[0][0] if states else ""
        addresses.update(found_addresses)
        counts[f["id"]] = len(meetings)
        sid = f["id"] + "-public"
        entries.append({
            "id": sid, "name": o["name"], "fellowship": "AA", "kind": "TSML",
            "url": f"{PAGES}v1/feeds/{sid}.json", "website": page_url.split("?")[0],
            "area": o.get("area"), "centerLat": o["centerLat"], "centerLng": o["centerLng"],
            "radiusMiles": o["radiusMiles"], "copyOf": o["id"],
            "type": "tsml_page", "page": page_url, "state": state, "details": "online",
            # A weekly copy, each list on its own weekday so no morning reads them all.
            "refreshDays": 7, "weekday": zlib.crc32(sid.encode()) % 7, "enabled": True,
            "decision": DECISION,
        })
        print(f"{sid:<40} {len(meetings):>5} meetings, {state}", flush=True)

    print(f"\n{len(entries)} lists, {sum(counts.values())} meetings, {len(addresses)} addresses", flush=True)
    todo = {k: v for k, v in addresses.items() if k not in cache}
    print(f"{len(todo)} addresses to look up", flush=True)
    extra.geocode_with_fallback(todo, cache, build.UA, max_lookups=5000)
    for k in todo:
        if cache.get(k) is None:
            cache[k] = []  # looked up, not found: don't ask again every morning
    placed = sum(1 for k in addresses if cache.get(k))
    print(f"placed {placed} of {len(addresses)} addresses", flush=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    out_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
