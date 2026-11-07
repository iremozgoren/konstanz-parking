"""COVID-19 phases for the 2020 natural experiment (Konstanz / Swiss border).

Dates are local (Europe/Berlin) calendar days, verified 2026-11-07 against these sources:

- [1] Germany introduced border controls and entry restrictions at the Swiss border on
  16 March 2020; Konstanz/Kreuzlingen closed with fences. Fence removed 15/16 May 2020.
  https://www.kreuzlingen.ch/datei-download/1565 ,
  https://www.thestar.com.my/news/world/2020/05/16/lovers-kept-apart-by-coronavirus-reunited-as-border-fence-comes-down
- [2] BW Corona-Verordnung of 17 March 2020, in force 18 March 2020: most retail closed.
  https://realtech.com/wp-content/uploads/2020/03/2020_03_17_landesregierung-beschliesst-massnahmen-gegen-die-ausbreitung-des-coronavirus.pdf
- [3] BW: shops up to 800 m² may reopen from 20 April 2020.
  https://www.baden-wuerttemberg.de/de/service/presse/pressemitteilung/pid/richtlinie-fuer-die-oeffnung-des-einzelhandels-1
- [4] Switzerland: "extraordinary situation" from 16 March 2020, shops closed (from 17 March);
  shops reopened 11 May 2020. https://www.plattformj.ch/artikel/180442/ ,
  https://www.blick.ch/schweiz/nach-sechs-wochen-corona-lockdown-heute-oeffnet-sich-die-schweiz-id15862917.html
- [5] 16 May 2020: checks at the German/Austrian border eased, crossing allowed only to visit
  family or a partner, or one's own property (plus allotment gardeners). "Einkaufen gelte nicht
  als ein triftiger Reisegrund"; shopping tourists were turned back and fined.
  https://www.plattformj.ch/artikel/181990/ . SRF, 14 May 2020: "Wenn am 15. Juni die Grenzen
  wieder ganz aufgehen, dürfte auch der Einkaufstourismus wieder einsetzen."
  https://www.srf.ch/news/schweiz/selbstdeklaration-fuer-paare-das-ist-sicher-noch-eine-knacknuss
  15 June 2020: free movement restored, ceremony at the Konstanz/Kreuzlingen border.
  https://www.plattformj.ch/artikel/182614/
- [6] Germany: retail closed again from 16 December 2020 (second lockdown).
  https://www.baden-wuerttemberg.de/de/service/alle-meldungen/meldung/pid/bund-und-laender-einigen-sich-auf-lockdown-ab-16-dezember/

``shopping_tourism_allowed``: False from 16 Mar to 14 Jun 2020 (crossing the border to shop was
not a permitted reason), True otherwise. Later restrictions (quarantine rules, the second German
retail lockdown) are not encoded in this flag.

Phases (``covid_phase``):
- ``pre_covid``: before 16 Mar 2020.
- ``border_closed_shops_open``: 16-17 Mar 2020 (2 days of transition; exclude from comparisons).
- ``lockdown``: 18 Mar - 19 Apr 2020. German shops closed AND border closed: the two effects
  cannot be separated.
- ``shops_open_border_closed``: 20 Apr - 14 Jun 2020. **Key window**: shops in BW open (≤ 800 m²
  at first), Swiss shoppers cannot come. Sub-events: Swiss shops reopen 11 May; partners and
  relatives may cross from 16 May. **Shopping trips stay banned until 15 June** [5], so the
  16 May easing does not end the key window (``border_partial_easing`` marks it only as a
  sub-period; ``shopping_tourism_allowed`` stays False).
- ``border_reopened``: 15 Jun - 15 Dec 2020.
- ``later_covid``: from 16 Dec 2020 (second lockdown, later varying restrictions; not modelled
  in detail).
"""

from __future__ import annotations

import pandas as pd

PHASES: list[tuple[str, str]] = [
    ("border_closed_shops_open", "2020-03-16"),
    ("lockdown", "2020-03-18"),
    ("shops_open_border_closed", "2020-04-20"),
    ("border_reopened", "2020-06-15"),
    ("later_covid", "2020-12-16"),
]
PHASE_ORDER = ["pre_covid"] + [p for p, _ in PHASES]

CH_SHOPS_CLOSED = ("2020-03-17", "2020-05-10")  # inclusive, local dates [4]
BORDER_PARTIAL_EASING_FROM = "2020-05-16"  # partners/relatives only, no shopping [5]
SHOPPING_TOURISM_BANNED = ("2020-03-16", "2020-06-14")  # inclusive, local dates [1, 5]


def phases(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Per local date: ``covid_phase`` (ordered categorical) and sub-event flags."""
    phase = pd.Series("pre_covid", index=dates)
    for name, start in PHASES:
        phase[dates >= pd.Timestamp(start)] = name
    out = pd.DataFrame(index=dates)
    out["covid_phase"] = pd.Categorical(phase, categories=PHASE_ORDER, ordered=True)
    out["ch_shops_closed_covid"] = (dates >= pd.Timestamp(CH_SHOPS_CLOSED[0])) & (
        dates <= pd.Timestamp(CH_SHOPS_CLOSED[1])
    )
    out["border_partial_easing"] = (out["covid_phase"] == "shops_open_border_closed") & (
        dates >= pd.Timestamp(BORDER_PARTIAL_EASING_FROM)
    )
    out["shopping_tourism_allowed"] = ~(
        (dates >= pd.Timestamp(SHOPPING_TOURISM_BANNED[0]))
        & (dates <= pd.Timestamp(SHOPPING_TOURISM_BANNED[1]))
    )
    return out
