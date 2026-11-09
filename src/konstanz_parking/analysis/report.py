"""Build ``reports/analysis.md``: does Swiss shopping tourism drive parking occupancy in Konstanz?

All numbers are recomputed on every run (``uv run konstanz-parking analysis``). The prose around
them was written for the results at the time of writing: if the data or the cleaning change,
re-read the interpretation sentences.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from konstanz_parking.analysis import figures, panel
from konstanz_parking.analysis import fx_effect as fxe
from konstanz_parking.analysis import natural_experiment as ne
from konstanz_parking.analysis import swiss_holidays as sh


def _ci(r: dict | pd.Series, nd: int = 1) -> str:
    return f"{r['est']:+.{nd}f} [{r['lo']:+.{nd}f}, {r['hi']:+.{nd}f}]"


def _p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def _cars(x: float | None) -> str:
    return "–" if x is None or pd.isna(x) else f"≈ {x:+.0f}"


def _variant_table(df: pd.DataFrame) -> str:
    lines = [
        "| Specification | Effect (pp) [95 % CI] | p | ≈ cars | Car parks | 2020 days | Obs. |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, r in df.iterrows():
        name = f"**{r['variant']}**" if r["kind"] == "main" else r["variant"]
        lines.append(
            f"| {name} | {_ci(r)} | {_p(r['p'])} | {_cars(r['cars'])} | {r['n_lots']} | "
            f"{r['n_days_2020']} | {r['nobs']:,} |"
        )
    return "\n".join(lines)


def angle1(r: ne.Results, figdir: Path, tables: Path) -> str:
    r.variants.to_csv(tables / "analysis_2020_did.csv", index=False)
    r.groups.to_csv(tables / "analysis_2020_groups.csv", index=False)
    r.event.to_csv(tables / "analysis_2020_event_study.csv", index=False)
    figures.raw_weekly(r, figdir / "analysis_2020_weekly.png")
    figures.event_study(r, figdir / "analysis_2020_event_study.png")
    figures.event_study_long(r, figdir / "analysis_2020_event_study_long.png")
    figures.event_study_groups(r, figdir / "analysis_2020_event_study_groups.png")
    forest_rows = r.variants.assign(label=r.variants["variant"].str.replace("Main: ", ""))
    figures.forest(
        forest_rows,
        figdir / "analysis_2020_did.png",
        "2020 difference-in-differences: main estimate and robustness checks",
        "Extra occupancy after 15 June 2020 vs same weeks 2016–2019 (pp, 95 % CI)",
    )

    v = r.variants.set_index("kind")
    main = r.variants.iloc[0]
    lago_rows = r.variants[r.variants["kind"].isin(["main", "lago"])]
    lo_range, hi_range = lago_rows["est"].min(), lago_rows["est"].max()
    g = r.groups.set_index("term")
    j = r.jump
    bg = {k: r.by_group[k][1] for k in panel.GROUP_ORDER}
    pre_level = r.event_long[r.event_long["start"] < pd.Timestamp("2020-03-09")]["est"].mean()
    week0 = j["week0"]
    post_avg = j["post_avg_w0_7"]
    lots = ", ".join(r.n["lots"])
    del v

    lago_cap = r.capacity["lago"]
    lago_j = [bg["lago"][k]["est"] for k in ("jump", "jump_last4", "jump_quad")]
    lago_lo, lago_hi = min(lago_j), max(lago_j)
    pj = {"Pooled (all car parks)": j} | {
        {"lago": "LAGO", "centre": "City centre", "less_shopping": "Less shopping-oriented"}[k]: bg[
            k
        ]
        for k in panel.GROUP_ORDER
    }
    jump_rows = "\n".join(
        f"| {name} | {_ci(x['jump'])} | {_ci(x['jump_last4'])} | {_ci(x['jump_quad'])} |"
        for name, x in pj.items()
    )

    return f"""## 1. The 2020 natural experiment

**Design (pre-specified).** Difference-in-differences on daily occupancy (10–18 h, shopping days).
The model compares `pre` = 20 Apr–14 Jun 2020 (BW shops open, crossing to shop banned) with `post` =
15 Jun–9 Aug 2020 (border open). It subtracts the change between the same calendar dates in
2016–2019. Fixed effects: car park × year, car park × period, car park × weekday. Controls: weather
(temperature and its square, rain, sunshine), BW school holidays, bridge days. Standard errors are
clustered by date. Car parks: {lots}. Seerheincenter has a 2016–2017 baseline, so it is included
(see *Deviations*).
2020 has {r.n["days_2020_pre"]} shopping days in `pre` and {r.n["days_2020_post"]} in `post`.
Mean 2020 occupancy in `pre` was {r.n["mean_y_2020_pre"]:.0f} %.

![Weekly occupancy 2020 vs 2016-2019](figures/analysis_2020_weekly.png)

The raw picture already shows the problem with this design. In 2020 occupancy did not stay flat
during `pre`. It climbed steadily from the lockdown low back towards normal, and in the city centre
it reached the normal level at about the time the border reopened.

### Main estimate and robustness checks

{_variant_table(r.variants)}

![DiD variants](figures/analysis_2020_did.png)

- **Main estimate (pre-specified):** occupancy rose **{main["est"]:.1f} pp** more from `pre` to
  `post` in 2020 than in a normal year (95 % CI {main["lo"]:.1f} to {main["hi"]:.1f}).
- **LAGO gap:** the three LAGO versions give **{lo_range:.1f} to {hi_range:.1f} pp**. Dropping
  LAGO, or keeping only dates on which LAGO is valid, moves the estimate by less than 2 pp. LAGO's
  14 frozen days do not drive the result.
- **This is not a clean Swiss effect.** The main estimate is reported as pre-specified, but it
  compares the *average* of `pre` (which includes the deep post-lockdown dip of late April) with
  the average of `post`. Most of it is the general recovery. Starting `pre` on 11 May (R1) lowers it
  to {r.variants.iloc[3]["est"]:.1f} pp, and it would keep falling with later starts. **The DiD is
  an upper bound, not an estimate of the Swiss effect.** The event study separates the two.

### Event study (pre-specified)

![Event study](figures/analysis_2020_event_study.png)

Each point is the 2020 deviation from the same week of 2016–2019, relative to the last week before
the reopening (8–14 Jun). Pre-specified reading: compare the step into the week of 15 June with
the linear trend of the weeks 20 Apr–14 Jun, extrapolated one week.

- Through May and early June 2020, occupancy recovered by about
  **{j["slope_per_week"]["est"]:.1f} pp per week** relative to normal years.
- In the week of 15 June, occupancy was {week0["est"]:.1f} pp above the reference week. The linear
  trend predicts {j["trend_pred_week0"]["est"]:.1f} pp. **Pre-specified jump beyond the trend:
  {_ci(j["jump"])} pp** (p {_p(j["jump"]["p"])}).
- After that the series is flat (weeks 0–7: {_ci(post_avg)} pp), at about the level of February
  2020 relative to normal years ({pre_level:+.1f} pp, exploratory figure below). In other words,
  2020 was back to its pre-COVID level from the week of the reopening on.

![Event study from February](figures/analysis_2020_event_study_long.png)

**Sharp jump or gradual recovery? For the pooled data, the honest answer is: the data cannot
tell.** The recovery was accelerating in late May and early June, and a straight line through
all eight weeks underestimates its last steps. The jump is therefore sensitive to the shape of
the trend. This check was added after seeing the raw series (see *Deviations*):

| Group | Jump, linear trend 8 weeks (pre-specified) | Linear trend, last 4 weeks | Quadratic trend, 8 weeks |
|---|---|---|---|
{jump_rows}

Pooled and for the city centre, the jump shrinks to about zero with a more flexible trend. The
pattern fits a recovery that **completed** around mid-June about as well as it fits a Swiss
step. The plateau after 15 June does not settle the question either, because a completed recovery
also levels off at the normal level.

### Border-near vs city-centre car parks

Pre-specified DiD by group (one model, group-specific `2020 × post` terms):

| Group | Effect (pp) [95 % CI] | ≈ cars | Car parks |
|---|---|---|---|
| LAGO | {_ci(g.loc["lago"])} | {_cars(g.loc["lago", "cars"])} | {g.loc["lago", "lots"]} |
| City centre | {_ci(g.loc["centre"])} | {_cars(g.loc["centre", "cars"])} | {g.loc["centre", "lots"]} |
| Less shopping-oriented | {_ci(g.loc["less_shopping"])} | {_cars(g.loc["less_shopping", "cars"])} | {g.loc["less_shopping", "lots"]} |
| LAGO − less shopping | {_ci(g.loc["lago − less_shopping"])} | | |
| Centre − less shopping | {_ci(g.loc["centre − less_shopping"])} | | |

These group DiDs contain the same recovery bias as the pooled one. The more informative evidence is
the event study per group (exploratory, not pre-specified):

![Event study per group](figures/analysis_2020_event_study_groups.png)

- **LAGO, right next to the Kreuzlingen border, shows a step at 15 June that survives every trend
  shape: {lago_lo:+.0f} to {lago_hi:+.0f} pp** (table above). That is roughly
  {lago_lo / 100 * lago_cap:.0f}–{lago_hi / 100 * lago_cap:.0f} more cars of its ~{lago_cap:.0f}
  effective spaces at an average daytime moment. In the raw data, LAGO's gap to normal years
  halved within the first week after the reopening and closed in the second.
- **City centre:** a jump of {bg["centre"]["jump"]["est"]:+.1f} pp with the pre-specified trend, but
  {bg["centre"]["jump_quad"]["est"]:+.1f} pp with a quadratic one. Not distinguishable from a
  completed recovery.
- **Less shopping-oriented** (Benediktiner, Bodenseeforum): no positive step under any trend. The
  negative values reflect an unusually high reference week (in the raw data 2020 was *above* normal
  in 8–14 Jun, but well below in the weeks before and after). Bodenseeforum is also not a
  clean control, because large events stayed banned all summer.

So the evidence ranks as the shopping-tourism hypothesis predicts, with a clear step only where Swiss
shoppers are expected to matter most. It is still **one car park and one event**. A LAGO-specific
change on 15 June (for example a rule for shopping centres) would produce the same picture. I found
none, but cannot rule it out.

### Confounders

| Confounder | Date | Handled? |
|---|---|---|
| Post-lockdown recovery trend | from 20 Apr 2020 | **Not by the DiD**, which it inflates. **Only partly by the event study:** the step at LAGO is robust to the trend's shape, the pooled and city-centre steps are not. The group comparison helps only if the recovery is similar across groups, which is not guaranteed. |
| German VAT cut 19 → 16 % | 1 Jul 2020 | **Yes for the step:** it starts two weeks after the reopening, and the weeks around 1 July show no further step. The DiD's `post` window includes it. Swiss shoppers can reclaim German VAT anyway, so the cut mainly affects German residents. |
| BW mask mandate in shops | from 27 Apr 2020 | **Largely:** in force during almost all of `pre` and all of `post`, so it cannot create a step on 15 June. It may lower 2020 levels overall. |
| Swiss summer holidays | TG from 4 Jul, ZH from 11 Jul 2020 | **On average yes:** baseline years have them at similar dates, and the step (15–21 Jun) comes before them. **Not handled:** in 2020 many Swiss holidayed at home instead of abroad, which could raise July shopping trips. No extra rise is visible in July. |
| Other steps inside `pre` | 800 m² limit lifted 4 May; Swiss shops reopen 11 May; partners may cross 16 May | Part of the recovery trend; robustness check R1 starts `pre` on 11 May. |
| Domestic tourism and events | BW hotels reopened in late May; large events stayed banned | **Not handled.** Tourism mainly builds up in July, after the step. The event ban keeps Bodenseeforum (comparison group) low. |
| Holidays inside the windows | Ascension, Pentecost, Corpus Christi; BW Pentecost holidays 2–13 Jun | Public holidays are not shopping days (excluded); bridge days and BW school holidays are controlled. The reference week 8–14 Jun contains Corpus Christi and its bridge day, so it is a slightly unusual reference (the jump test uses all eight weeks, which limits the impact). |
"""


def _effect_table(df: pd.DataFrame) -> str:
    lines = [
        "| Specification | Effect (pp) [95 % CI] | p | % of normal-day mean | ≈ cars | Obs. |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in df.iterrows():
        name = f"**{r['label']}**" if r["kind"] == "main" else r["label"]
        lines.append(
            f"| {name} | {_ci(r)} | {_p(r['p'])} | {r['pct_of_mean']:+.1f} % | "
            f"{_cars(r['cars'])} | {r['nobs']:,} |"
        )
    return "\n".join(lines)


def angle2(r: sh.Results, figdir: Path, tables: Path) -> str:
    t = r.table
    t.to_csv(tables / "analysis_swiss_holidays.csv", index=False)
    figures.forest(
        t.assign(label=t["label"].str.replace("Main: ", "")),
        figdir / "analysis_swiss_holidays.png",
        "Swiss holidays on German shopping days: main estimate, breakdowns, placebos",
        "Extra daily occupancy 10–18 h vs comparable normal days (pp, 95 % CI)",
    )
    c = r.counts
    x = t.set_index("label")
    main = t.iloc[0]
    row = lambda prefix: t[t["label"].str.startswith(prefix)].iloc[0]  # noqa: E731
    pub, school = row("1a"), row("1b")
    wd, sat = row("2a"), row("2b")
    no_bw = row("4:")
    lago, centre, less = row("7: LAGO"), row("7: city"), row("7: less")
    pl = t[t["kind"] == "placebo"]
    del x

    return f"""## 2. Swiss holidays on German shopping days (2015–2022)

**Design (pre-specified).** On German shopping days (Mon–Sat, not a BW public holiday), compare
occupancy on days when Thurgau or Zürich has a public or school holiday with other days **of the
same car park in the same month and year**. Fixed effects: car park × year-month, car park ×
weekday. Controls: weather, BW school holidays, bridge days. Standard errors are clustered by
calendar week, because school holidays come in blocks of consecutive days.

- Sample: {c["dates"]:,} shopping days (Jul 2015–15 Mar 2020 and Apr–Dec 2022), {c["obs"]:,}
  car-park-days, {c["holiday_dates"]} of these dates with a Swiss holiday, spread over
  {c["holiday_weeks"]} calendar weeks.
- 20 Dec–6 Jan is excluded (Swiss Christmas holidays coincide with the German pre-Christmas peak).
  This also removes Berchtoldstag (2 January). The only Swiss-only public holiday left is **Swiss
  National Day (1 August)**, on {c["public_dates"]} dates.
- {c["na_dropped_dates"]} dates are dropped because the Zürich sport week is unknown.

{_effect_table(t)}

![Swiss holiday effects](figures/analysis_swiss_holidays.png)

**Main estimate:** on a German shopping day with a Swiss holiday, average daytime occupancy is
**{main["est"]:.1f} pp higher** (95 % CI {main["lo"]:.1f} to {main["hi"]:.1f}) than on comparable
days. That is {main["pct_of_mean"]:.0f} % above the normal-day mean of {c["mean_y_nonholiday"]:.0f} %,
or {_cars(main["cars"])} cars across the {c["capacity"]:.0f} effective spaces of these car parks.

What the breakdowns show:

- **School holidays** carry almost all events ({school["est"]:+.1f} pp). **Swiss National Day**
  shows a much larger effect ({pub["est"]:+.1f} pp) but rests on only {c["public_dates"]} days.
  All of them fall inside the Swiss summer holidays, so they are not independent events. Treat it
  as anecdotal.
- **Weekdays vs Saturdays:** {wd["est"]:+.1f} pp on Mon–Fri, {sat["est"]:+.1f} pp on Saturdays
  ({_ci(sat)}). This is **not** evidence that Swiss shoppers stay away on Saturdays. On a normal
  Saturday the city-centre car parks and LAGO are already about 93 % full on average (10–18 h), and
  more than half of all Saturday quarter-hours are at ≥ 95 %. Extra demand cannot show up in
  occupancy when the car parks are full: it turns into queues or parking elsewhere. **Occupancy
  data cannot measure the Saturday effect.**
- **Both cantons on holiday** ({row("3c")["est"]:+.1f} pp) > Zürich only ({row("3b")["est"]:+.1f}) >
  Thurgau only ({row("3a")["est"]:+.1f}). This dose-response pattern fits the hypothesis: more Swiss
  people off school, more extra cars.
- **By car park:** LAGO {_ci(lago)} pp ({lago["pct_of_mean"]:+.0f} % of its normal level), city
  centre {_ci(centre)}, less shopping-oriented {_ci(less)}. The ordering again points to the
  border-near shopping centre, but the less shopping-oriented car parks also rise. Part of the
  effect is therefore not shopping specific (e.g. Swiss day trips and tourism in general).
- **Overlap with BW school holidays:** on days without BW school holidays the effect is
  {_ci(no_bw)} pp. That is smaller than the main estimate, so the BW school holiday control may
  not fully separate the two when both fall in the same weeks.

**Placebo test: not passed cleanly.** Moving the Swiss dates by two weeks should give zero. It gives
{pl.iloc[0]["est"]:+.1f} pp ({_ci(pl.iloc[0])}) and {pl.iloc[1]["est"]:+.1f} pp ({_ci(pl.iloc[1])}).
School holidays fall at about the same time every year (e.g. July/August, October), and the
month fixed effects do not absorb all patterns *within* a month. A shifted indicator picks up
some of that seasonal timing. The placebo estimates are about a third of the main estimate and have
opposite signs. A reasonable reading is that **roughly ±2 pp of the main estimate could be seasonal
timing rather than Swiss holidays**. The effect stays positive under that margin but is less precise
than the confidence interval suggests.
"""


def angle3(r: fxe.Results, figdir: Path, tables: Path) -> str:
    t = r.table
    t.to_csv(tables / "analysis_fx.csv", index=False)
    figures.fx_figure(r, figdir / "analysis_fx.png")
    figures.forest(
        t.assign(label=t["label"].str.replace("Main: ", "")),
        figdir / "analysis_fx_variants.png",
        "CHF/EUR: main estimate and robustness checks",
        "Occupancy change per 10 % stronger franc (pp, 95 % CI)",
    )
    c = r.counts
    main = t.iloc[0]
    lines = [
        "| Specification | pp per 10 % stronger franc [95 % CI] | p | ≈ cars | Months | Obs. |",
        "|---|---|---|---|---|---|",
    ]
    for _, x in t.iterrows():
        name = f"**{x['label']}**" if x["kind"] == "main" else x["label"]
        lines.append(
            f"| {name} | {_ci(x)} | {_p(x['p'])} | {_cars(x['cars'])} | {x['months']} | {x['nobs']} |"
        )
    span = 100 * (c["fx_max"] / c["fx_min"] - 1)
    lo_all, hi_all = t["lo"].min(), t["hi"].max()

    return f"""## 3. CHF/EUR and occupancy (correlational)

**Design (pre-specified).** Monthly panel per car park, {c["months"]} months between Jul 2015 and
Feb 2020 ({c["obs"]} car-park-months with ≥ {fxe.MIN_DAYS} valid shopping days). Occupancy is
regressed on log(EUR per CHF) with car park and calendar-month fixed effects, a linear trend per
car park, weather, and the share of BW school holiday and Swiss holiday shopping days in the month.
Standard errors are Driscoll–Kraay (robust to correlation across car parks and over
{fxe.DK_LAGS} months).

**This angle is correlational.** The exchange rate is not assigned at random. It moves slowly,
together with the Swiss and German economies, retail trends (e.g. online shopping) and parking
supply. Nothing below is a causal estimate.

![CHF/EUR](figures/analysis_fx.png)

{chr(10).join(lines)}

![FX variants](figures/analysis_fx_variants.png)

- **Main estimate:** {_ci(main)} pp per 10 % stronger franc (p {_p(main["p"])}). **No detectable
  association.**
- Every robustness check also has a confidence interval that includes zero. Taken together, they
  run from {lo_all:+.1f} to {hi_all:+.1f} pp. The point estimates are all positive (the
  direction the hypothesis predicts) but small.
- **What this can and cannot say.** In the main sample the franc only moved between
  {c["fx_min"]:.3f} ({c["fx_min_month"]}) and {c["fx_max"]:.3f} CHF per EUR ({c["fx_max_month"]}),
  a range of about {span:.0f} %. The big franc shock of January 2015 is before the data starts.
  About {100 * c["x_share_left"]:.0f} % of the within-car-park FX variation is left after season,
  trends and controls, so the model has some variation to work with. The data **rule out large
  effects** (more than about {hi_all:.0f} pp per 10 %) but cannot distinguish a small positive
  association from zero.
- The forecasting model (Phase 5) can still use the exchange rate as a feature. Its importance there
  will be predictive, not causal.
"""


def build(processed: Path, reports: Path, external: Path = Path("data/external")) -> Path:
    figdir, tables = reports / "figures", reports / "tables"
    figdir.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)
    bins = panel.load_bins(processed)
    d = panel.daily(bins)

    parts = [
        HEADER,
        angle1(ne.run(d, bins), figdir, tables),
        angle2(sh.run(d, bins), figdir, tables),
        angle3(fxe.run(d, external / "ecb" / "ecb_chf_eur_daily.csv"), figdir, tables),
        DEVIATIONS,
    ]
    out = reports / "analysis.md"
    out.write_text("\n\n".join(p.strip() for p in parts) + "\n")
    return out


HEADER = """# Does Swiss shopping tourism drive parking occupancy in Konstanz?

Generated by `uv run konstanz-parking analysis` from the cleaned ParkenDD history (2015–2022, nine
car parks) joined with weather, holidays and CHF/EUR. The analysis was **pre-specified** in
[`analysis_plan.md`](analysis_plan.md), committed before any model was run. Every robustness check
from the plan is reported below, whatever its result.

**Outcome:** daily mean occupancy (10:00–18:00 local) of one car park, in percentage points of its
effective capacity, on German shopping days (Mon–Sat, not a BW public holiday). Car-park-days need
≥ 24 of 32 valid 15-minute bins. All effects come with 95 % confidence intervals. "≈ cars" converts
percentage points into cars parked at an average daytime moment, using the summed effective
capacity of the car parks in the sample."""

DEVIATIONS = """## Deviations from the plan

- The plan said Seerheincenter has no valid data before 2020 and would drop out of angles 1 and 3.
  In fact it has valid data in 2015–2017 (only 2018–2019 are frozen). It therefore stays in the
  pooled estimates, as the plan's rule ("all car parks") requires, but belongs to none of the
  three car park groups.
- The event-study weeks without any 2020 observation (LAGO, 18–24 May) get no coefficient and are
  left out of the trend fit, instead of being treated as zero.
- Added, clearly marked as exploratory: the event study from February 2020 and the event study per
  car park group.
- Added after seeing the raw weekly series: the jump re-estimated with a linear trend through the
  last four weeks and with a quadratic trend. The raw series showed an accelerating recovery that
  the pre-specified linear trend cannot capture. This check **weakened** the pooled and city-centre
  results; it is reported because it changes the conclusion."""
