"""
For AA lists whose feed is restricted (the 12 Step Meeting List plugin's default), find the
ones whose public meeting page can be read the way a visitor sees it, as with EVI.
Checks robots.txt first, asks for each page once, and writes tools/public_pages.json.

    python tools/find_public_pages.py
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "builder"))
import build  # noqa: E402

UA = build.UA


def get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read().decode("utf-8", "replace")


def rows(page):
    n = 0
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = dict(re.findall(r'<td class="([a-z]+)[^"]*"[^>]*>(.*?)</td>', row, re.S))
        if "name" in cells and "time" in cells:
            n += 1
    return n


def main():
    manual = json.loads((ROOT / "sources/sources.json").read_text(encoding="utf-8"))
    generated = json.loads((ROOT / "sources/aa_sources.json").read_text(encoding="utf-8"))
    copied = {s.get("copyOf") for s in manual}
    seen, todo = set(), []
    for s in manual + generated:
        if not s.get("restricted") or s["id"] in copied:
            continue
        key = build.feed_key(s["url"])
        if key in seen:
            continue
        seen.add(key)
        todo.append(s)
    out = []
    for s in todo:
        parts = urllib.parse.urlsplit(s["url"])
        root = f"{parts.scheme}://{parts.netloc}"
        page_url = root + "/meetings/?tsml-day=any"
        result = {"id": s["id"], "name": s["name"], "root": root, "page": page_url}
        try:
            robots = urllib.robotparser.RobotFileParser()
            try:
                _, _, text = get(root + "/robots.txt", timeout=20)
                robots.parse(text.splitlines())
            except Exception:  # noqa: BLE001 - no robots.txt means no rules
                robots.parse([])
            if not robots.can_fetch(UA, page_url):
                result["status"] = "robots says no"
            else:
                time.sleep(1)
                status, final, page = get(page_url)
                result["final"] = final
                n = rows(page)
                result["rows"] = n
                if n:
                    result["status"] = "readable"
                elif "tsml-ui" in page or 'id="tsml-ui"' in page:
                    result["status"] = "new interface (loads the restricted feed in the browser)"
                elif "sgcaptcha" in page or "challenge" in page.lower()[:3000]:
                    result["status"] = "bot check"
                else:
                    result["status"] = "no meeting table"
        except Exception as e:  # noqa: BLE001
            result["status"] = f"error: {str(e)[:80]}"
        print(f"{s['id']:<34} {result['status']:<20} {result.get('rows', '')}", flush=True)
        out.append(result)
        time.sleep(1)
    (ROOT / "tools/public_pages.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
