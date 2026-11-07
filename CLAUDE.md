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
- Phase 2 + 3 done **for the ParkenDD history** (2026-11-07): `src/konstanz_parking/history/`
  (`lots.py`, `load.py`, `coverage.py`, `clean.py`, `report.py`) and `src/konstanz_parking/auxiliary/`
  (`weather.py`, `fx.py`, `holidays.py`, `covid.py`, `features.py`). Report:
  `reports/data_quality_parkendd.md`; aux notes: `reports/auxiliary_data.md`. Cleaning the *live*
  collector data is still to do (reuse the flag logic).

## Phase 2/3 pipeline rules

- Pipeline: `coverage` → `clean` → `report`; `fetch-aux` → `features`. Outputs in `data/processed/`
  (gitignored, derived from unlicensed dumps). `reports/` (Markdown, PNG, aggregate CSV) **is** committed.
- Rows are flagged, never silently deleted (`valid` = no invalid flag). Thresholds are constants at the
  top of `history/clean.py`; the report recomputes every number, so re-run `report` after changes.
- Occupancy = 1 − free / **effective capacity** (99.9th pct of valid free per lot / capacity period),
  because official capacities contradict the history. Official ArcGIS capacity is informational only.
- Analysis deps are in the uv group `analysis`; the collector workflow uses `--no-default-groups`.
- Matplotlib figures use `history/plotstyle.py` (fixed categorical colour order, blue ramp).
- **The University of Konstanz car parks (`pbw`, control group) exist only in the live data**, not in
  the ParkenDD history. The 2020 natural experiment has no university control group; use within-city
  contrasts instead.

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
- **Triggers:** primary = cron-job.org calling the `workflow_dispatch` API every 15 min at :00/:15/:30/:45
  (`inputs.trigger = "cron-job.org"`); backup = GitHub schedule at :07/:22/:37/:52 (it fired only 2× in
  ~10 h on 2026-11-06/07). `collect --min-interval 600` skips a run if the last non-skipped snapshot is
  < 10 min old, and logs it with `"skipped": true` and its `trigger`, so per-trigger reliability can be measured.
- The cron-job.org job uses a **fine-grained PAT** (only this repo, Actions: read & write) that **expires
  around 2027-11-07**. The token lives only in cron-job.org; never put it in the repo or the chat. When
  it expires, dispatches fail with 401 and only the backup schedule remains.
- **GitHub disables scheduled workflows in public repos after 60 days without repository activity.**
  It is unclear whether the bot's pushes to `data` count. GitHub emails a warning first; re-enable with
  `gh workflow enable collect.yml`, or push any commit to `main` at least every ~50 days.
- Raw data volume is ~2.4 MB/day (~0.9 GB/year). If repo size becomes a problem, compact old months
  into archives in Phase 2. Never edit raw lines.

## Known data quirks

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
- ParkenDD (found in Phase 2, details in the report): timestamps verified as UTC. Renames
  `augustinerkarstadt`→`augustiner` (2022-01-10), `amseerhein`→`bodenseeforum` (2016-11-25). Several car
  parks report 0 at night while closed, and drop to 0 for ~15 min every day at 07:00 local (feed reset;
  some at midnight). Negative values only in 2022. Bodenseeforum capped at 500. Seerheincenter
  reported up to 1410 in mid-2020, capacity ceiling 280 → 235. Official capacities disagree with the data
  (Altstadt ≤ 259 of 359, Benediktiner > 118, Döbele ≤ 335 vs ArcGIS 435). Feed-wide freezes, e.g.
  2020-08-11..20. **LAGO frozen 2020-05-12..25** (inside the key border-closure window). Holes:
  2019-02-11..05-16 and almost all of 2021.

## 2020 border closure: ParkenDD coverage (checked 2026-11-06)

Window 2020-03-16 to 2020-06-15 (92 days). 97 % of 5-min slots are present for every lot.
Days with ≥ 80 % slots and non-constant values:
altstadt, augustinerkarstadt, bodenseeforum, doebele, fischmarkt, lago: 92/92;
benediktiner, marktstaette: 85/92; seerheincenter: 83/92.
Comparison windows: 2020-01-06 to 03-15 (99.9 %), 2020-06-16 to 09-30 (94 %), 2018 same window
(81.5 %, data ends 2018-06-01), 2019 same window (33 %, data starts 2019-05-16).
**Confounder:** the closure overlaps the German COVID retail lockdown. Phases are now encoded as
`covid_phase` in `auxiliary/covid.py` (dates verified with sources): pre_covid; border_closed_shops_open
(16–17 Mar); lockdown (18 Mar–19 Apr: effects not separable); **shops_open_border_closed (20 Apr–14 Jun,
key window)**; border_reopened (15 Jun–15 Dec); later_covid (from 16 Dec 2020). Use car parks less
dependent on shoppers (benediktiner, bodenseeforum) as within-city contrasts.

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
