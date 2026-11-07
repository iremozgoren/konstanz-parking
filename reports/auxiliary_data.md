# Auxiliary data: weather, CHF/EUR, holidays, COVID-19 phases

`uv run konstanz-parking fetch-aux` downloads the raw files into `data/external/` (gitignored).
`uv run konstanz-parking features` joins them onto the cleaned 15-minute grid and writes
`data/processed/features_15min.parquet` (one row per car park × 15 min, 39 columns).

## Sources and how they are joined

| Feature(s) | Source | Join | Licence |
|---|---|---|---|
| `temp_c`, `rel_humidity`, `precip_mm`, `precip_ind`, `sunshine_min`, `wind_ms` | DWD hourly observations, station **02712 Konstanz** (historical + recent files; historical wins) | Each 15-min bin gets the hourly record of the hour that contains it (record ending at the next full hour, UTC) | DWD open data, "Datenbasis: Deutscher Wetterdienst" |
| `chf_per_eur` | ECB reference rate `EXR.D.CHF.EUR.SP00.A` | As of publication: the rate for day *d* is used from 16:00 local on *d*. Before that, and on weekends and TARGET holidays, the previous rate applies. **No look-ahead.** | ECB, free reuse with attribution |
| `de_public_holiday`, `ch_tg_public_holiday`, `ch_zh_public_holiday` (+ names) | Python `holidays` package (DE-BW, CH-TG, CH-ZH) | Local calendar date | MIT |
| `de_school_holiday` | OpenHolidays API (DE-BW) | Local date | ODbL |
| `ch_tg_school_holiday`, `ch_zh_school_holiday` | 2015–2019: **EDK national school holiday lists**, transcribed into `src/konstanz_parking/auxiliary/ch_school_holidays_manual.csv` (source per row). From 2020: OpenHolidays API | Local date | EDK lists: reproduction with attribution; OpenHolidays: ODbL |
| `covid_phase`, `ch_shops_closed_covid`, `border_partial_easing` | Official announcements and press, listed in `auxiliary/covid.py` | Local date | – |
| `hour`, `minute_of_day`, `day_of_week`, `is_saturday`, `month`, `year` | Derived from `ts_local` | – | – |

## Holiday logic

- **German shopping day** (`de_shopping_day`): Monday to Saturday and not a BW public holiday.
  German shops are closed on Sundays and public holidays, so a Swiss holiday can only bring
  shoppers to Konstanz on such a day.
- **Interaction features**:
  - `swiss_holiday_german_shopping_day`: a TG or ZH public **or** school holiday on a German
    shopping day.
  - `swiss_public_holiday_german_shopping_day`: the same, public holidays only (e.g. Berchtoldstag
    on 2 January in Thurgau, Swiss national day on 1 August). Days that are holidays on both sides,
    such as Ascension or 26 December, are excluded because German shops are closed.
  - `swiss_school_holiday_german_shopping_day`: the same, school holidays only.
- School holiday periods are **extended to the adjacent weekend(s)**: sources differ in whether
  they list them (the EDK lists Zürich's holidays Mon–Fri from 2018 and Sat–Sun before), and
  families travel on them.
- For Zürich, only OpenHolidays entries for the *Volksschule* (compulsory school) are used. Entries
  that apply only to vocational and upper-secondary schools (e.g. Ascension bridge days) are
  ignored.

## Known gaps and approximations

- **Zürich sport week:** set by each municipality. A canton-wide date exists in the EDK lists only
  for 2015, 2018, 2019 and 2020. For 2016, 2017, 2021 and 2022, February is marked **unknown
  (`<NA>`)** instead of guessed. This is why `ch_zh_school_holiday` is missing for 4.2 % of rows.
  The combined `ch_school_holiday` is still `True` where Thurgau has holidays (Kleene logic).
- **Canton-level dates are approximations:** some municipalities deviate, and Thurgau gives its
  school municipalities one week of their own choosing (often around Ascension). That week is not
  included.
- The EDK 2015 list prints the end of Thurgau's spring holidays as "19.04.2013". This is an obvious
  typo for 2015, corrected and noted in the CSV.
- Zürich's city holidays (Sechseläuten, Knabenschiessen) are not public holidays in the `holidays`
  package and are not included.
- **Weather:** DWD reports sunshine only for hours ending 03–20 UTC. Night hours are set to 0 min.
  The remaining missing values are real station gaps (sunshine 2.6 %, others < 0.2 % of rows).
- **Weather timing:** the "concurrent hour" join uses values measured up to 45 minutes after the
  start of a bin. That is fine for explaining occupancy (Phase 4). The forecasting model
  (Phase 5) must use lagged or forecast weather instead.

## COVID-19 phases (2020 natural experiment)

| `covid_phase` | Local dates | Meaning |
|---|---|---|
| `pre_covid` | until 2020-03-15 | Baseline |
| `border_closed_shops_open` | 2020-03-16 – 03-17 | Border closed, BW shops still open (2-day transition, exclude) |
| `lockdown` | 2020-03-18 – 04-19 | BW shops closed **and** border closed. The two effects cannot be separated |
| `shops_open_border_closed` | 2020-04-20 – 06-14 | **Key window:** BW shops open (≤ 800 m² at first), Swiss shoppers cannot come |
| `border_reopened` | 2020-06-15 – 12-15 | Free movement restored |
| `later_covid` | from 2020-12-16 | Second German retail lockdown, later varying rules (not modelled) |

Flags within the key window: `ch_shops_closed_covid` (Swiss shops closed 17 March – 10 May 2020)
and `border_partial_easing` (from 16 May only partners, relatives and second-home owners could
cross; shopping trips were still not allowed).

Caveats for this window are in the ParkenDD quality report: LAGO's sensor is frozen from 12 to
25 May 2020, and Seerheincenter has no pre-COVID baseline.

## Not in the history

The University of Konstanz car parks (the planned control group, ParkAPI source `pbw`) are **not**
in the ParkenDD history. They exist only in the live data collected since November 2026.
