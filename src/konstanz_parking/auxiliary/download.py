"""Download auxiliary raw data into ``data/external/`` (gitignored; re-downloadable).

- DWD hourly observations, station 02712 Konstanz (air temperature, precipitation, sunshine,
  wind): historical and recent zips. License: DWD open data, attribution "Deutscher Wetterdienst".
- ECB euro reference rate CHF per EUR (daily). Free reuse with source attribution.
- OpenHolidays API: school holidays for DE-BW, CH-TG, CH-ZH (ODbL).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx

from konstanz_parking.sources import USER_AGENT

log = logging.getLogger("konstanz_parking.auxiliary")

DWD_STATION = "02712"
DWD_BASE = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/"
DWD_PRODUCTS = {
    "air_temperature": "TU",
    "precipitation": "RR",
    "sun": "SD",
    "wind": "FF",
}
ECB_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.CHF.EUR.SP00.A"
OPENHOLIDAYS_URL = "https://openholidaysapi.org/SchoolHolidays"
SCHOOL_SUBDIVISIONS = {"DE": "DE-BW", "CH-TG": "CH-TG", "CH-ZH": "CH-ZH"}
HOLIDAY_YEARS = range(2015, 2028)


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(120.0, connect=15.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def _get(client: httpx.Client, url: str, **kw) -> httpx.Response:
    for attempt in range(4):
        try:
            r = client.get(url, **kw)
            r.raise_for_status()
            return r
        except httpx.HTTPError as exc:
            if attempt == 3:
                raise
            log.warning("retrying %s after %s", url, exc)
            time.sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


def download_dwd(dest: Path, client: httpx.Client) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for product, code in DWD_PRODUCTS.items():
        for kind in ("historical", "recent"):
            index = _get(client, f"{DWD_BASE}{product}/{kind}/").text
            pattern = rf'stundenwerte_{code}_{DWD_STATION}_[^"]+\.zip'
            for name in sorted(set(re.findall(pattern, index))):
                target = dest / name
                # 'recent' files change daily: always refresh them; historical ones are stable.
                if target.exists() and kind == "historical":
                    out.append(target)
                    continue
                r = _get(client, f"{DWD_BASE}{product}/{kind}/{name}")
                target.write_bytes(r.content)
                log.info("downloaded %s (%d bytes)", name, len(r.content))
                out.append(target)
    return out


def download_ecb(dest: Path, client: httpx.Client) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    r = _get(client, ECB_URL, params={"format": "csvdata", "startPeriod": "2015-01-01"})
    target = dest / "ecb_chf_eur_daily.csv"
    target.write_bytes(r.content)
    log.info("downloaded ECB CHF/EUR (%d bytes)", len(r.content))
    return target


def download_openholidays(dest: Path, client: httpx.Client) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for subdiv in SCHOOL_SUBDIVISIONS.values():
        country = subdiv.split("-")[0]
        for year in HOLIDAY_YEARS:
            target = dest / f"school_{subdiv}_{year}.json"
            if target.exists() and year < time.gmtime().tm_year:
                out.append(target)
                continue
            r = _get(
                client,
                OPENHOLIDAYS_URL,
                params={
                    "countryIsoCode": country,
                    "subdivisionCode": subdiv,
                    "languageIsoCode": "EN",
                    "validFrom": f"{year}-01-01",
                    "validTo": f"{year}-12-31",
                },
            )
            target.write_bytes(r.content)
            out.append(target)
            time.sleep(0.5)
    log.info("OpenHolidays: %d files", len(out))
    return out


def download_all(external: Path) -> None:
    with _client() as client:
        download_dwd(external / "dwd", client)
        download_ecb(external / "ecb", client)
        download_openholidays(external / "openholidays", client)
