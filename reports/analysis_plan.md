# Pre-specified analysis plan (Phase 3)

Written and committed **before any model was run** (2026-11-09). The main estimate for each angle is
fixed here. Every robustness check listed here is reported in `reports/analysis.md` whatever its
result. Any deviation from this plan is listed there under "Deviations from the plan".

## Common definitions

- **Outcome:** daily mean occupancy of one car park, in percentage points (0–100), over the local
  15-minute bins 10:00–17:45 (32 bins). Occupancy = 1 − free / effective capacity (see the quality
  report). Bins come from `features_15min.parquet` (invalid readings are NaN; only gaps ≤ 30 min are interpolated).
  A car-park-day enters the analysis only if **≥ 24 of 32 bins** are valid. This automatically drops
  LAGO's frozen days (12–25 May 2020).
- **Shopping days only:** Monday to Saturday and not a BW public holiday (German shops are closed
  otherwise).
- **Daily weather** (10:00–18:00): mean temperature and its square, precipitation sum, sunshine
  minutes.
- **Bridge day:** a shopping day between a BW public holiday and a weekend/holiday.
- **Car park groups:**
  - `lago`: LAGO shopping centre, about 500 m from the Kreuzlingen border.
  - `centre`: Altstadt, Augustiner, Döbele, Fischmarkt, Marktstätte.
  - `less_shopping`: Benediktiner, Bodenseeforum (event venue / offices).
  - Seerheincenter has no valid data before 2020 and drops out of angles 1 and 3 automatically.
- **Inference:** OLS with fixed effects, 95 % confidence intervals. Standard errors are clustered by
  date (angle 1) or by calendar week (angle 2). Angle 3 uses Driscoll–Kraay (HAC across months,
  6 lags).
- **Effect in cars:** coefficient / 100 × summed effective capacity of the car parks in the sample.

## Angle 1: 2020 natural experiment (difference-in-differences)

- **Sample:** years 2016–2019 (baseline) and 2020, shopping days, calendar dates 20 Apr–9 Aug.
  - `pre` = 20 Apr–14 Jun (shops open in BW, crossing to shop banned).
  - `post` = 15 Jun–9 Aug (same 56-day length, border open).
- **Model:** `y ~ 2020×post + lot×year FE + lot×post FE + lot×weekday FE + weather + BW school
  holiday + bridge day`.
- **MAIN ESTIMATE:** the coefficient on `2020×post`, pooled over all car parks, LAGO's invalid
  days dropped, daily level. It estimates how much more occupancy rose from `pre` to `post` in
  2020 than in the same calendar weeks of 2016–2019.
- **LAGO variants (all reported, the range is the headline uncertainty):**
  - (a) main
  - (b) without LAGO
  - (c) only dates on which LAGO is valid
- **Group heterogeneity:** `2020×post` interacted with the car park group. Contrasts:
  - `lago − less_shopping`
  - `centre − less_shopping`
- **Robustness (all reported):**
  1. `pre` restricted to 11 May–14 Jun: all BW shops open from 4 May (800 m² limit lifted) and
     Swiss shops open from 11 May.
  2. Baseline year 2022 only, instead of 2016–2019.
  3. 15-minute level (10:00–17:45, lot×year×hour FE added), clustered by date.
  4. Saturdays only.
- **Event study (pre-specified):**
  - Dates 30 Mar–30 Aug, in 7-day bins aligned so that a bin starts on 15 June.
  - `y ~ Σ_k 2020×bin_k + lot×year FE + lot×bin FE + lot×weekday FE + weather + BW school holiday
    + bridge day`.
  - Reference bin = 8–14 Jun (the last week before reopening).
  - The plot shows the 2020 coefficients with 95 % CIs, the phases shaded.
  - **Pre-specified reading:**
    - Compare the jump from the reference week to the 15–21 Jun week with a linear trend fitted to
      the bins from 20 Apr to 14 Jun (shops open), extrapolated one week.
    - A jump well above the extrapolated trend supports a Swiss effect. A level in line with the
      trend suggests general recovery.
- **Named confounders:**
  - post-lockdown recovery trend
  - German VAT cut from 1 Jul 2020
  - BW mask mandate in shops from 27 Apr 2020
  - Swiss summer holidays starting in July

  The report states which of these the design handles and which it does not.

## Angle 2: Swiss holidays on German shopping days (2015–2022)

- **Sample:**
  - Shopping days from 2015-07 to 2020-03-15, plus 2022-04-01 to 2022-12-31 (after COVID rules).
  - 20 Dec–6 Jan is excluded, because Swiss Christmas holidays coincide with the German
    pre-Christmas peak.
  - Days where the Swiss indicator is unknown (`<NA>`, Zürich sport weeks) are dropped.
- **Treatment:** `swiss_holiday_german_shopping_day`, i.e. a TG or ZH public or school holiday on a
  German shopping day.
- **Model:** `y ~ swiss_holiday + lot×year×month FE + lot×weekday FE + BW school holiday + bridge
  day + weather`, clustered by calendar week.
- **MAIN ESTIMATE:** the `swiss_holiday` coefficient, pooled over all car parks, daily level.
- **Robustness and breakdowns (all reported):**
  1. Split into Swiss public vs school holidays.
  2. Saturday vs weekday interaction.
  3. TG only / ZH only / both.
  4. Only days without BW school holidays.
  5. Keeping 20 Dec–6 Jan (with a day-of-December control).
  6. Clustering by date instead of week.
  7. Per car park group.
  8. Placebo: the indicator shifted by −14 and +14 days, on days that are not real Swiss holidays.
     These estimates should be near zero.
  9. 15-minute level.

## Angle 3: CHF/EUR (correlational)

- **Sample:** monthly panel per car park, 2015-07 to 2020-02. Each car-park-month needs ≥ 10 valid
  shopping days.
- **Regressor:** `log(EUR per CHF)`, the monthly mean of the ECB rate. Higher = stronger franc.
  Reported as pp per **10 % stronger franc**.
- **Model:** `y ~ log(EUR per CHF) + lot FE + calendar month FE + lot-specific linear trend +
  weather + share of BW school holiday days + share of Swiss holiday shopping days`.
- **MAIN ESTIMATE:** the FX coefficient in this model.
- **Robustness (all reported):**
  1. No trend.
  2. Common quadratic trend.
  3. Spline trend (4 df).
  4. FX lagged (mean of previous 3 months).
  5. Excluding 2015.
  6. Including 2022 (strongest franc, but 2021 is missing and the post-COVID level differs).
- **Interpretation is correlational only.** The franc moves slowly, together with other long-run
  changes, and the sample has about 55 months.
