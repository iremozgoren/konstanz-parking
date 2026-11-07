# CLAUDE.md — Konstanz Parking Occupancy

## Project

Portfolio data project: **"What drives parking occupancy in Konstanz?"**

**Hypothesis:** besides weather and day of week, *Swiss shopping tourism* is a major driver.
Proxies: Swiss public and school holidays (Thurgau, Zürich, …) and the CHF/EUR exchange rate.

## Conventions

- Everything in **English**: code, file names, comments, commits, README.
- Python **3.12**, dependencies managed with **uv** (`uv add`, `uv run`). No pip/requirements.txt.
- Data processing: **pandas** + **DuckDB**.
- Lint/format: **ruff** (`uv run ruff check . && uv run ruff format .`).
- Tests: **pytest** (`uv run pytest`).
- Timestamps: store in **UTC** (ISO 8601 with offset). Convert to `Europe/Berlin` only for analysis/display.
- Raw data in `data/raw/` is **append-only and never modified**. All cleaning produces new files elsewhere.

## Phases

### Phase 0 — Data source feasibility (research only, no code)
1. Find a real-time or historical parking occupancy source for Konstanz
   (MobiData BW / ParkAPI, offenedaten-konstanz.de, the city's Parkleitsystem).
   For each: URL, format, update frequency, car parks covered, license,
   historical data availability, whether automated polling is allowed.
2. If nothing usable exists for Konstanz, propose a fallback (e.g. Zürich's open Parkleitsystem).
3. Check auxiliary sources: DWD open weather data (Konstanz station), ECB CHF/EUR reference rates,
   German (BW) and Swiss (Thurgau, Zürich) public + school holidays.
4. Report findings and **wait for the user's decision** before Phase 1.

### Phase 1 — Collector (after source approval)
- Small Python collector polling the parking source every **15 min** via **GitHub Actions cron**.
- Appends raw snapshots to `data/raw/` as **daily files**; raw files are never modified.
- Robust: retries with backoff, timeouts, logs failures, **never fails the workflow** on a bad
  response, and stores the raw response body even if malformed (flagged as such).
- Goal: start collecting ASAP — the analysis needs weeks of data.
- Note: GitHub cron is best-effort (runs can be delayed or skipped); the cleaning phase must handle
  irregular intervals.

### Later phases (plan only — do not build yet)
- **Phase 2 — Cleaning pipeline + data quality report:** gaps, frozen sensors (unchanged values for
  long periods), impossible values (negative free spaces, free > capacity), duplicates,
  DST/timezone issues, capacity changes, car parks appearing/disappearing.
- **Phase 3 — Auxiliary data:** weather (DWD), CHF/EUR (ECB), holidays (BW + Swiss cantons),
  joined onto a regular 15-min time grid.
- **Phase 4 — EDA:** daily/weekly profiles, Saturday effect, Swiss vs. German holiday effects,
  exchange-rate effect, weather effect.
- **Phase 5 — Forecasting model:** baselines (seasonal naive) vs. gradient boosting with calendar,
  weather, holiday and FX features; time-based cross-validation; feature importance to answer the
  research question.
- **Phase 6 — Streamlit dashboard:** live/recent occupancy, profiles, holiday comparisons, forecasts.

## Layout (planned)

```
data/raw/          # append-only raw snapshots, one file per day
data/processed/    # cleaned outputs (generated)
src/konstanz_parking/
tests/
.github/workflows/
```

## Status

- Phase 0 done (2026-11-06). Decision: three-source collector, with the city HTML as primary and
  ArcGIS + ParkAPI `konstanz`/`pbw` alongside. The `pbw` university car parks are the control group.
- Phase 1 built (2026-11-06): `src/konstanz_parking/` (`collector.py`, `sources.py`, `parkendd.py`),
  `.github/workflows/collect.yml` (cron) and `ci.yml` (ruff + pytest).

## Phase 1 operating rules (decided with the user)

- **Raw snapshots go to the `data` branch**, never to `main`. The workflow file lives on `main`
  (schedules only run from the default branch) and does a sparse, blobless checkout of `data`
  containing only today's/tomorrow's daily files.
- **ParkenDD dumps have no license**: download only (`konstanz-parking download-parkendd`) into
  the gitignored `data/external/parkendd/`. Never commit them.
- Every request sends `USER_AGENT` (in `sources.py`, includes the user's contact email, which the
  user approved). At most one request per run to konstanz.de; retries wait ≥ 30 s (robots.txt Crawl-delay).
- City HTML: store the verbatim parking-section slice (~12 KB, ~5 KB during outages), with the SHA-256
  of the full page. Fall back to the full page if the section markers are missing.
- Every run is logged with real timestamps in `data/raw/runs/<date>.jsonl` (GitHub cron delays/skips).
- **GitHub disables scheduled workflows in public repos after 60 days without repository activity.**
  It is unclear whether the bot's pushes to `data` count. GitHub emails a warning first; re-enable with
  `gh workflow enable collect.yml`, or push any commit to `main` at least every ~50 days.
- Raw data volume is ~2.4 MB/day (~0.9 GB/year). If repo size becomes a problem, compact old months
  into archives in Phase 2. Never edit raw lines.

## Known data quirks (for Phase 2)

- konstanz.de hides the parking tables from User-Agents containing "collector" (probably a bot
  keyword list). Every snapshot before the UA fix (until 2026-11-07 08:16 UTC) has `valid=false` for this
  reason, not because the city's data was down. Keep the UA free of words like that.
- The *"Derzeit sind keine aktuellen Belegungszahlen verfügbar"* notice is shown for one region box
  (Petershausen) even when the other tables are present. Only a page with no tables at all is invalid.
- City HTML: four rows are all labelled "Fernbusbahnhof". Identify car parks by the detail-page `href`
  or the row position, not by the label. `XXX` = no data. No timestamp and no capacity in the HTML;
  use ArcGIS `max_cap`.
- ArcGIS/ParkAPI `konstanz`: Döbele and Europabrücke report 0 free of 0, which is not real data.
- ParkenDD dumps: rows unsorted; `0 free` over long spans can mean closed or no data, not full.
  `bykguldenstr` is constant 0 (unusable). `seerheincenter` is frozen before 2020.

## 2020 border closure: ParkenDD coverage (checked 2026-11-06)

Window 2020-03-16 to 2020-06-15 (92 days). 97 % of 5-min slots are present for every lot.
Days with ≥ 80 % slots and non-constant values:
altstadt, augustinerkarstadt, bodenseeforum, doebele, fischmarkt, lago: 92/92;
benediktiner, marktstaette: 85/92; seerheincenter: 83/92.
Comparison windows: 2020-01-06 to 03-15 (99.9 %), 2020-06-16 to 09-30 (94 %), 2018 same window
(81.5 %, data ends 2018-06-01), 2019 same window (33 %, data starts 2019-05-16).
**Confounder:** the closure overlaps the German COVID retail lockdown (shops closed from mid-March,
partial reopening from around 20 April 2020). Split the window into lockdown vs.
shops-open-but-border-closed, and use car parks less dependent on shoppers (benediktiner, bodenseeforum)
as within-city contrasts.

## Data sources (Phase 0 findings, verified 2026-11-06)

### Parking: live
| Source | Endpoint | Status on 2026-11-06 | License |
|---|---|---|---|
| City Parkleitsystem HTML | `https://www.konstanz.de/leben+in+konstanz/mobilitaet/parkleitsystem` (`table.parken`) | **Working**: plausible free counts for Altstadt, Lago, Fischmarkt, Döbele + 3 more. No timestamps, no capacities, several rows wrongly labelled "Fernbusbahnhof", `XXX` = no data | None stated. robots.txt allows the path (Crawl-delay 30) |
| City ArcGIS (official open data) | `https://services.gis.konstanz.digital/geoportal/rest/services/Fachdaten/Parkplaetze_Parkleitsystem/MapServer/0/query?where=1%3D1&outFields=*&f=json` | **Live fields mostly null**: 11 sites, good static metadata (`max_cap`, coordinates, operator). `real_fcap`/`updated` null except Döbele and Europabrücke, which read 0/0 (bogus). Schema differs from the MobiData docs | CC BY 4.0 © Stadt Konstanz |
| MobiData BW ParkAPI v3 | `https://api.mobidata-bw.de/park-api/api/public/v3/parking-sites?source_uid=konstanz` (also `pbw`) | `konstanz`: same broken data as ArcGIS (9 sites in error). `pbw`: **working** for the 4 university car parks | CC BY 4.0 (konstanz) |
| ParkenDD API | `https://api.parkendd.de/Konstanz` | Mirrors the city HTML, `active_support: false` | — |

### Parking: historical
- ParkenDD dumps: `https://parkendd.de/dumps/` (`konstanz<lot>-<year>.csv`, format `utc_timestamp,free`).
  5-minute data for 2015 (from July) to 2022, covering Altstadt, Lago, Fischmarkt, Marktstätte, Augustiner,
  Benediktiner, Seerheincenter, Döbele and Bodenseeforum. Has gaps (e.g. 2019-03/04, most of 2021).
  Rows are unsorted. Nothing after 2022. No explicit license.

### Auxiliary
- Weather: DWD station **02712 Konstanz**, 10-minute and hourly data on opendata.dwd.de (`recent`/`now`/`historical`).
- FX: ECB SDMX `https://data-api.ecb.europa.eu/service/data/EXR/D.CHF.EUR.SP00.A?format=csvdata` (daily, CHF per EUR).
- Holidays: OpenHolidays API (`openholidaysapi.org`): school holidays for DE-BW, CH-TG, CH-ZH;
  public holidays via `/PublicHolidays` or the `holidays` Python package. Some Swiss school holidays are set per
  municipality, so canton-level dates are an approximation.
