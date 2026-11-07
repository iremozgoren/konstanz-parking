"""Registry of Konstanz car parks in the ParkenDD dumps.

The dumps are named ``konstanz<dump_name>-<year>.csv``. Some car parks were renamed by the
scraper (the series continue seamlessly, verified on 2026-11-07), and a few dump names are
scraper artefacts rather than car parks.

Capacities:
- ``arcgis_max_cap``: official ``max_cap`` from the city's ArcGIS layer (retrieved 2026-11-07).
- ``parkendd_total``: ``total`` reported by api.parkendd.de (retrieved 2026-11-07).
Both are *today's* values. The historical free counts often disagree with them (see the data
quality report), so cleaning also derives an *effective* capacity from the data itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lot:
    lot_id: str
    name: str
    dump_names: tuple[str, ...]
    arcgis_max_cap: int | None
    parkendd_total: int | None
    note: str = ""


LOTS: tuple[Lot, ...] = (
    Lot("altstadt", "Parkhaus Altstadt", ("altstadt",), 359, 359),
    Lot(
        "augustiner",
        "Parkhaus Augustiner / Karstadt",
        ("augustinerkarstadt", "augustiner"),
        288,
        None,
        "renamed augustinerkarstadt -> augustiner on 2022-01-10 09:00 UTC (no overlap)",
    ),
    Lot("benediktiner", "Parkhaus Benediktinerplatz", ("benediktiner",), 118, None),
    Lot(
        "bodenseeforum",
        "Parkplatz Bodenseeforum",
        ("amseerhein", "bodenseeforum"),
        None,
        None,
        "renamed amseerhein -> bodenseeforum on 2016-11-25 11:50 UTC (no overlap); "
        "free counts are capped at 500; not in the city's ArcGIS layer",
    ),
    Lot("doebele", "Parkplatz Döbele", ("doebele",), 435, 335),
    Lot("fischmarkt", "Parkhaus Fischmarkt", ("fischmarkt",), 161, 158),
    Lot("lago", "Parkhaus LAGO", ("lago",), 931, 936),
    Lot("marktstaette", "Parkhaus Marktstätte", ("marktstaette",), 288, None),
    Lot("seerheincenter", "Tiefgarage Seerheincenter", ("seerheincenter",), 312, 280),
)

LOTS_BY_ID: dict[str, Lot] = {lot.lot_id: lot for lot in LOTS}

# Dump names that are not used, with the reason (shown in the coverage and quality reports).
EXCLUDED_DUMPS: dict[str, str] = {
    "0": "scraper artefact: constant 0, no car park name",
    "xxx": "scraper artefact: constant 0 ('XXX' is the city's no-data marker)",
    "$parkgetbezeichnung": "scraper artefact: unrendered template variable, constant 0",
    "bykguldenstr": "constant 0 from 2016 on; not part of today's parking guidance system",
    "bykgulden": "renamed bykguldenstr (6 rows, constant 0)",
}

_DUMP_TO_LOT: dict[str, str] = {d: lot.lot_id for lot in LOTS for d in lot.dump_names}


def lot_for_dump(dump_name: str) -> str | None:
    """Canonical lot id for a dump name, or ``None`` if the dump is excluded/unknown."""
    return _DUMP_TO_LOT.get(dump_name)
