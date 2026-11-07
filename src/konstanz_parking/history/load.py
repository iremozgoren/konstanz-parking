"""Load the raw ParkenDD dumps (read-only) into one long DataFrame.

Each dump is a headerless CSV ``utc_timestamp,free``. Timestamps have no offset; ParkenDD
documents them as UTC, and the data confirms it (no missing hour on spring-forward nights, no
doubled hour on fall-back nights; see the quality report).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from konstanz_parking.history.lots import lot_for_dump

DEFAULT_DUMP_DIR = Path("data/external/parkendd")

_NAME_RE = re.compile(r"^konstanz(?P<dump>.+?)-(?P<year>\d{4})(?P<backup>\.backup-\d{4})?\.csv$")

COLUMNS = ["lot_id", "dump_name", "source_file", "is_backup", "file_row", "ts_utc", "free"]


def parse_dump_filename(name: str) -> tuple[str, int, bool] | None:
    """``konstanzlago-2020.csv`` -> ``("lago", 2020, False)``."""
    m = _NAME_RE.match(name)
    if not m:
        return None
    return m["dump"], int(m["year"]), m["backup"] is not None


def read_dump(path: Path) -> pd.DataFrame:
    """Read one dump file. Unparseable rows are kept with NaT/NaN (counted by the caller)."""
    raw = pd.read_csv(path, header=None, names=["ts", "free"], dtype=str, keep_default_na=False)
    out = pd.DataFrame(
        {
            "file_row": pd.RangeIndex(len(raw)),
            "ts_utc": pd.to_datetime(
                raw["ts"], format="%Y-%m-%dT%H:%M:%S", errors="coerce", utc=True
            ),
            "free": pd.to_numeric(raw["free"], errors="coerce").astype("Int64"),
        }
    )
    return out


def load_raw(dump_dir: Path = DEFAULT_DUMP_DIR, include_excluded: bool = False) -> pd.DataFrame:
    """All dump rows as a long DataFrame (columns: ``COLUMNS``).

    Excluded dumps (see ``EXCLUDED_DUMPS``) get ``lot_id = None`` and are dropped unless
    ``include_excluded`` is set.
    """
    frames = []
    for path in sorted(dump_dir.glob("konstanz*.csv")):
        parsed = parse_dump_filename(path.name)
        if parsed is None:
            continue
        dump, _year, is_backup = parsed
        lot_id = lot_for_dump(dump)
        if lot_id is None and not include_excluded:
            continue
        df = read_dump(path)
        df["lot_id"] = lot_id
        df["dump_name"] = dump
        df["source_file"] = path.name
        df["is_backup"] = is_backup
        frames.append(df)
    if not frames:
        raise FileNotFoundError(
            f"no ParkenDD dumps in {dump_dir}; run `konstanz-parking download-parkendd` first"
        )
    out = pd.concat(frames, ignore_index=True)[COLUMNS]
    for col in ("lot_id", "dump_name", "source_file"):
        out[col] = out[col].astype("category")
    return out
