# What drives parking occupancy in Konstanz?

Konstanz sits directly on the Swiss border, and its city-centre car parks fill up with
shoppers from Switzerland. This project tests the hypothesis that **besides weather and day
of week, Swiss shopping tourism is a major driver of parking occupancy**. It measures that
through Swiss public and school holidays (Thurgau, Zürich) and the CHF/EUR exchange rate.

Car parks at the University of Konstanz serve as a **control group**: they are busy for
reasons that have nothing to do with shopping.

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Data source feasibility | ✅ done |
| 1 | Collector (GitHub Actions, every 15 min) + historical download | ✅ running |
| 2 | Cleaning pipeline + data quality report | ✅ done for the 2015–2022 history ([report](reports/data_quality_parkendd.md)); live data pending |
| 3 | Weather, FX and holiday features | ✅ joined onto the history ([notes](reports/auxiliary_data.md)) |
| 4 | Exploratory analysis | planned |
| 5 | Occupancy forecasting model | planned |
| 6 | Streamlit dashboard | planned |

A natural experiment is built into the history: during the Swiss–German border closure
(mid-March to mid-June 2020), Swiss shoppers could not come at all.

## How the collector works

- `.github/workflows/collect.yml` runs every 15 minutes and polls four endpoints
  (see below), one request each.
- Each response is appended **unchanged** to `data/raw/<source>/<YYYY-MM-DD>.jsonl` on the
  **`data` branch**, so `main` stays clean. Each line holds the request metadata (timestamps,
  HTTP status, all retry attempts, SHA-256 of the full body) and the body itself.
- For the city web page only the parking section (a verbatim ~12 KB slice of the ~260 KB
  page) is stored. If the page layout changes and the section cannot be found, the full page
  is stored instead.
- Bad responses (timeouts, HTTP errors, malformed bodies, city outages) never fail the
  workflow. They are recorded as data and shown as warning annotations.
- Every run logs its actual start/end time to `data/raw/runs/<date>.jsonl`, because GitHub's
  cron is best-effort and runs can be delayed or skipped.
- Because GitHub's cron drops many runs on quiet repositories, an external scheduler
  ([cron-job.org](https://cron-job.org)) triggers the workflow every 15 minutes through the
  `workflow_dispatch` API. GitHub's own schedule stays on as a backup. A run within 10 minutes
  of the previous snapshot is skipped (and logged), so the two triggers never create duplicates.
- Requests identify themselves with a descriptive User-Agent including a contact address.
  `konstanz.de` gets at most one request per run, and retries wait at least 30 s, as its
  robots.txt asks.

## Data sources & licensing

Some of the data used here is openly licensed and some is not. Each source keeps its own terms.

| Source | Used for | License / terms | Attribution & notes |
|---|---|---|---|
| [Stadt Konstanz – ArcGIS "Parkplätze Live"](https://offenedaten-konstanz.de/dataset/parkplaetze-und-parkleitsystem) (via MobiData BW) | Capacities, coordinates, metadata; live fields when they work | **CC BY 4.0** | **© Stadt Konstanz, CC BY 4.0** (Amt für Liegenschaften und Geoinformation). As of Nov 2026 the live fields are empty for 9 of 11 sites. |
| [MobiData BW ParkAPI v3](https://api.mobidata-bw.de/park-api/) – source `konstanz` | Same city data via the state platform | **CC BY 4.0** | **© Stadt Konstanz, CC BY 4.0**. Shows the same gaps as ArcGIS. |
| MobiData BW ParkAPI v3 – source `pbw` | University car parks (control group) | **Not stated** by the platform for this source | Operator: Parkraumgesellschaft Baden-Württemberg. |
| [Stadt Konstanz – Parkleitsystem web page](https://www.konstanz.de/leben+in+konstanz/mobilitaet/parkleitsystem) | **Primary** live free-space counts for the city-centre car parks | **No license stated** | Collected in line with the site's robots.txt: at most **1 request per 15 minutes**, retries wait ≥ 30 s (crawl-delay), and every request sends a descriptive User-Agent with a contact address. Raw snapshots are kept for this research project only. Please do not reuse them. |
| [ParkenDD dumps](https://parkendd.de/dumps/) | Historical 5-min data, 2015–2022 | **No license stated** | Downloaded locally by `konstanz-parking download-parkendd` into a gitignored folder. **Never committed or redistributed**; only aggregate statistics and figures appear in `reports/`. |
| [DWD Open Data](https://opendata.dwd.de/) – station 02712 Konstanz | Weather | **CC BY 4.0** ([DWD terms of use](https://opendata.dwd.de/climate_environment/CDC/Terms_of_use.pdf)) | **Source: Deutscher Wetterdienst (DWD), CC BY 4.0.** |
| [ECB data API](https://data.ecb.europa.eu/) – `EXR/D.CHF.EUR.SP00.A` | CHF/EUR exchange rate | [ECB statistics reuse policy](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html): free reuse, the source must be quoted and the statistics not altered | **Source: ECB statistics.** |
| [OpenHolidays API](https://www.openholidaysapi.org/) | School holidays for DE-BW, and for CH-TG/CH-ZH from 2020 | **ODbL 1.0** ([data repository](https://github.com/openpotato/openholidaysapi.data)) | **Contains data from the OpenHolidays API, ODbL 1.0.** Some Swiss school holidays are set per municipality, so canton-level dates are approximate. |
| [EDK school holiday lists](https://www.edk.ch/de/bildungssystem/kantonale-schulorganisation/Schulferien) (via edudoc.ch / Internet Archive) | Swiss school holidays 2015–2019, transcribed with sources into `auxiliary/ch_school_holidays_manual.csv` | Reproduction with source attribution ("Nachdruck nur mit Quellenangabe gestattet") | **Source: EDK / IDES, Schulferien 2015–2020.** |
| [`holidays`](https://pypi.org/project/holidays/) Python package | Public holidays DE-BW, CH-TG, CH-ZH | MIT | |

**Takedown:** If you own any of this data and want it removed, please contact me at
irem11314@gmail.com.

The **code** in this repository is licensed under the [MIT License](LICENSE). The MIT License
covers the code only, **not** the data: each data source keeps its own terms listed above.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .

uv run konstanz-parking collect --data-dir /tmp/raw     # poll once
uv run konstanz-parking download-parkendd               # history → data/external/parkendd/

# Phase 2/3 pipeline for the ParkenDD history (outputs in data/processed/ are not committed)
uv run konstanz-parking coverage     # raw coverage per car park and month → reports/tables, reports/figures
uv run konstanz-parking clean        # flags → data/processed/parkendd_clean.parquet + parkendd_15min.parquet
uv run konstanz-parking report       # → reports/data_quality_parkendd.md
uv run konstanz-parking fetch-aux    # DWD, ECB, OpenHolidays → data/external/
uv run konstanz-parking features     # → data/processed/features_15min.parquet
```

The collector workflow runs with `uv run --no-default-groups`, so it only installs `httpx`. The
analysis libraries (pandas, DuckDB, matplotlib, …) live in the `analysis` dependency group.
