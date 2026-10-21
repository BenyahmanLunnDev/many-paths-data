# Many Paths meeting data

A daily copy of the public recovery-meeting lists the [Many Paths](https://github.com/BenyahmanLunnDev) Android app shows. That covers NA online, Refuge Recovery, Recovery Dharma, Crystal Meth Anonymous, and about 230 AA intergroups and areas that share their lists openly, plus a few hand-entered local groups.

**Status page:** https://benyahmanlunndev.github.io/many-paths-data/

## Why a daily copy
- **Faster for phones:** the app downloads one trimmed file per list from one place, instead of contacting hundreds of volunteer-run websites.
- **Lighter on those websites:** each one is read once a day by this job, not by every phone.
- **Keys stay off phones:** when a group gives Many Paths a sharing key, the key lives here as a hidden GitHub secret, never in the app. That's the same approach AA's Meeting Guide app uses.

## What it does and doesn't copy
- It copies lists their owners publish openly (the 12 Step Meeting List feed with sharing set to "open", or a public NA server), and a few groups' public Google Sheets and calendars.
- **A restricted feed is never read** without the group's permission (a sharing key in the `SOURCE_KEYS` secret).
- Many AA lists are "restricted" only because that's the 12 Step Meeting List plugin's default. For those, the group's **public meetings page** (what any visitor sees) is copied about once a week, each list on its own weekday, if the site's robots.txt allows it. The apps show these as "copied from their website on <date>" with a link back, and a copy is replaced by the group's own feed if it shares a key, or removed if the group asks. See `sources/copy_sources.json`.
- Sites that block automated requests aren't worked around; the app reads them directly instead.
- Each record is trimmed to the fields the app uses. Edit links, authors, payment handles and feedback emails are dropped.
- If a site is down, yesterday's copy is kept and marked as such on the status page.

Every list belongs to the group that publishes it. Corrections belong on the group's own site, and they show up here the next day.

## Layout
| Path | What |
|---|---|
| `sources/` | Which lists to read (`sources.json` hand-kept, `aa_sources.json` generated from aa.org's directory, `copy_sources.json` public-page copies, `extra_sources.json` sheets and calendars), hand-entered groups, phone lines, known addresses |
| `tools/` | `find_public_pages.py` (which restricted lists have a readable public page) and `make_copy_sources.py` (writes `copy_sources.json` and looks up its addresses from a home connection) |
| `builder/build.py` | The daily build (Python standard library only) |
| `.github/workflows/daily.yml` | Runs the build at about 4 AM Pacific and publishes to GitHub Pages |
| `status/latest.json` | Small daily summary, committed so GitHub keeps the schedule running |

Published files (on Pages, not in git):

| File | What |
|---|---|
| `v1/feeds/<id>.json` | One list each |
| `v1/manifest.json` | Status of every list |
| `v1/sources.json`, `v1/places.json` | Every list the apps know, and a town/ZIP index for the web version |
| `v1/curated_meetings.json`, `v1/helplines.json`, `v1/aa_helplines.json` | Hand-entered groups and phone lines |

## Adding a sharing key
When a group gives Many Paths a key: go to Settings → Secrets and variables → Actions, and create or edit `SOURCE_KEYS` as `aa-eviaa=THEKEY` (separate several with `;`). Then run the workflow from the Actions tab.

## Run it locally
```bash
python -m unittest discover -s tests
python builder/build.py --out site --only refuge,dharma
```

## License
GPL-3.0 for the code. The meeting information belongs to the groups that publish it.
