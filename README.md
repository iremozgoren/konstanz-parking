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
| 2 | Cleaning pipeline + data quality report | planned |
| 3 | Weather, FX and holiday features | planned |
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
- Requests identify themselves with a descriptive User-Agent including a contact address.
  `konstanz.de` gets at most one request per run, and retries wait at least 30 s, as its
  robots.txt asks.

## Data sources & licensing

Some of the data used here is openly licensed and some is not.

| Source | Used for | License | Notes |
|---|---|---|---|
| [Stadt Konstanz – Parkleitsystem web page](https://www.konstanz.de/leben+in+konstanz/mobilitaet/parkleitsystem) | **Primary** live free-space counts for the city-centre car parks | **No license stated.** | Scraped in line with the site's robots.txt (crawl-delay respected). I have asked the city for permission. Raw snapshots are kept for research; please do not reuse them without checking with the city. |
| [Stadt Konstanz – ArcGIS "Parkplätze Live"](https://offenedaten-konstanz.de/dataset/parkplaetze-und-parkleitsystem) (via MobiData BW) | Capacities, coordinates, metadata; live fields when they work | **CC BY 4.0** © Stadt Konstanz, Amt für Liegenschaften und Geoinformation | As of Nov 2026 the live fields are empty for 9 of 11 sites (reported to the city). |
| [MobiData BW ParkAPI v3](https://api.mobidata-bw.de/park-api/) – source `konstanz` | Same city data via the state platform | **CC BY 4.0** (Stadt Konstanz) | Shows the same gaps as ArcGIS. |
| MobiData BW ParkAPI v3 – source `pbw` | University car parks (control group) | **Not stated** by the platform for this source | Operator: Parkraumgesellschaft Baden-Württemberg. |
| [ParkenDD dumps](https://parkendd.de/dumps/) | Historical 5-min data, 2015–2022 | **No license stated.** | Downloaded locally by `konstanz-parking download-parkendd` into a gitignored folder. **Never committed or redistributed.** |
| [DWD Open Data](https://opendata.dwd.de/) – station 02712 Konstanz | Weather (planned) | DWD terms of use (open, attribution required) | |
| [ECB data API](https://data.ecb.europa.eu/) – `EXR/D.CHF.EUR.SP00.A` | CHF/EUR exchange rate (planned) | ECB reuse policy (free, source must be cited) | |
| [OpenHolidays API](https://www.openholidaysapi.org/) | Public and school holidays for DE-BW, CH-TG, CH-ZH (planned) | Open data, see their terms | Some Swiss school holidays are set per municipality, so canton-level dates are approximate. |

The code in this repository is my own work. No license has been chosen yet.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .

uv run konstanz-parking collect --data-dir /tmp/raw     # poll once
uv run konstanz-parking download-parkendd               # history → data/external/parkendd/
```
