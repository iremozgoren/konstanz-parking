"""Definitions of the parking data sources polled by the collector."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

CONTACT_EMAIL = "irem11314@gmail.com"
REPO_URL = "https://github.com/iremozgoren/konstanz-parking"
# Do NOT put the word "collector" in the User-Agent: konstanz.de then serves the page without
# the parking tables (verified 2026-11-07; "konstanz-parking/0.1 (...)" gets the full page).
USER_AGENT = f"konstanz-parking/0.1 (+{REPO_URL}; {CONTACT_EMAIL})"

# konstanz.de robots.txt asks for "Crawl-delay: 30". We make at most one request per run
# to that host and wait at least this long before any retry.
KONSTANZ_DE_CRAWL_DELAY_S = 30.0

CITY_HTML_URL = "https://www.konstanz.de/leben+in+konstanz/mobilitaet/parkleitsystem"
ARCGIS_URL = (
    "https://services.gis.konstanz.digital/geoportal/rest/services/Fachdaten/"
    "Parkplaetze_Parkleitsystem/MapServer/0/query"
    "?where=1%3D1"
    "&outFields=id,name,type,max_cap,real_capa,real_fcap,updated,opening_s,has_live"
    "&returnGeometry=false&f=json"
)
PARKAPI_BASE = "https://api.mobidata-bw.de/park-api/api/public/v3/parking-sites"
PARKAPI_KONSTANZ_URL = f"{PARKAPI_BASE}?source_uid=konstanz"
# The pbw source covers all of Baden-Württemberg; restrict to the Konstanz university area.
PARKAPI_PBW_URL = f"{PARKAPI_BASE}?source_uid=pbw&lat=47.68&lon=9.18&radius=3000"

_HTML_START = '<table class="parken-header">'
_HTML_LAST_TABLE = '<table class="parken">'
_HTML_NO_DATA = "Derzeit sind keine aktuellen Belegungszahlen verfügbar"
_HTML_ROW_RE = re.compile(
    r'<table class="parken">.*?<td class="tdright[^"]*">\s*([^<]*?)\s*</td>', re.S
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    note: str | None = None
    rows: int | None = None


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    min_retry_delay_s: float = 5.0
    # Returns (stored_body, is_excerpt). Must be a verbatim substring of the body.
    excerpt: Callable[[str], tuple[str, bool]] | None = None
    validate: Callable[[str], ValidationResult] | None = None


def city_html_excerpt(body: str) -> tuple[str, bool]:
    """Return the verbatim slice of the page that contains the parking section.

    The full page is ~260 KB of navigation markup; the parking section is ~12 KB.
    The slice runs from the first table header to whichever comes last: the last
    parking table or the city's "no current data" notice (shown during outages).
    If no header is found (page redesign), the full body is kept so nothing is lost.
    """
    start = body.find(_HTML_START)
    if start == -1:
        return body, False
    ends = []
    for marker, closing in (
        (_HTML_LAST_TABLE, "</table>"),
        (_HTML_START, "</table>"),
        (_HTML_NO_DATA, "</p>"),
    ):
        pos = body.rfind(marker)
        if pos >= start:
            close = body.find(closing, pos)
            if close != -1:
                ends.append(close + len(closing))
    if not ends:
        return body, False
    return body[start : max(ends)], True


def validate_city_html(body: str) -> ValidationResult:
    values = _HTML_ROW_RE.findall(body)
    if not values:
        if _HTML_NO_DATA in body:
            return ValidationResult(False, "city reports no current occupancy data", 0)
        return ValidationResult(False, "no parking rows found", 0)
    numeric = sum(v.isdigit() for v in values)
    return ValidationResult(True, f"{numeric} numeric of {len(values)} rows", len(values))


def validate_arcgis(body: str) -> ValidationResult:
    try:
        data = json.loads(body)
    except ValueError as exc:
        return ValidationResult(False, f"invalid JSON: {exc}")
    if not isinstance(data, dict):
        return ValidationResult(False, "unexpected JSON shape")
    if "error" in data:
        return ValidationResult(False, f"ArcGIS error: {data['error']}")
    features = data.get("features")
    if not isinstance(features, list):
        return ValidationResult(False, "no 'features' list")
    live = sum(
        1
        for f in features
        if isinstance(f, dict) and (f.get("attributes") or {}).get("real_fcap") is not None
    )
    return ValidationResult(True, f"{live} of {len(features)} with real_fcap", len(features))


def validate_parkapi(body: str) -> ValidationResult:
    try:
        data = json.loads(body)
    except ValueError as exc:
        return ValidationResult(False, f"invalid JSON: {exc}")
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return ValidationResult(False, "no 'items' list")
    live = sum(
        1 for s in items if isinstance(s, dict) and s.get("realtime_free_capacity") is not None
    )
    return ValidationResult(True, f"{live} of {len(items)} with realtime_free_capacity", len(items))


SOURCES: tuple[Source, ...] = (
    Source(
        name="city_html",
        url=CITY_HTML_URL,
        min_retry_delay_s=KONSTANZ_DE_CRAWL_DELAY_S,
        excerpt=city_html_excerpt,
        validate=validate_city_html,
    ),
    Source(name="arcgis", url=ARCGIS_URL, validate=validate_arcgis),
    Source(name="parkapi_konstanz", url=PARKAPI_KONSTANZ_URL, validate=validate_parkapi),
    Source(name="parkapi_pbw", url=PARKAPI_PBW_URL, validate=validate_parkapi),
)
