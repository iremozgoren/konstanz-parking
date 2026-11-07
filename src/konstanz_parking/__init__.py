"""What drives parking occupancy in Konstanz?"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="konstanz-parking")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="poll all parking sources once")
    p_collect.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    p_collect.add_argument(
        "--min-interval",
        type=float,
        default=0.0,
        help="skip if the last snapshot is younger than this many seconds",
    )

    p_dl = sub.add_parser("download-parkendd", help="download historical ParkenDD dumps")
    p_dl.add_argument("--dest", type=Path, default=Path("data/external/parkendd"))
    p_dl.add_argument("--overwrite", action="store_true")

    p_cov = sub.add_parser("coverage", help="coverage of the ParkenDD history per lot and month")
    p_cov.add_argument("--dumps", type=Path, default=Path("data/external/parkendd"))
    p_cov.add_argument("--reports", type=Path, default=Path("reports"))

    p_clean = sub.add_parser("clean", help="clean the ParkenDD history -> data/processed/")
    p_clean.add_argument("--dumps", type=Path, default=Path("data/external/parkendd"))
    p_clean.add_argument("--processed", type=Path, default=Path("data/processed"))
    p_clean.add_argument("--reports", type=Path, default=Path("reports"))

    p_rep = sub.add_parser("report", help="data quality report for the ParkenDD history")
    p_rep.add_argument("--dumps", type=Path, default=Path("data/external/parkendd"))
    p_rep.add_argument("--processed", type=Path, default=Path("data/processed"))
    p_rep.add_argument("--reports", type=Path, default=Path("reports"))

    p_aux = sub.add_parser("fetch-aux", help="download DWD weather, ECB CHF/EUR, school holidays")
    p_aux.add_argument("--external", type=Path, default=Path("data/external"))

    p_feat = sub.add_parser("features", help="join auxiliary data onto the 15-min grid")
    p_feat.add_argument("--processed", type=Path, default=Path("data/processed"))
    p_feat.add_argument("--external", type=Path, default=Path("data/external"))
    p_feat.add_argument("--reports", type=Path, default=Path("reports"))

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.command == "collect":
        from konstanz_parking.collector import run

        record = run(args.data_dir, min_interval_s=args.min_interval)
        failed = [n for n, s in record["sources"].items() if not (s["ok"] and s["valid"])]
        for name in failed:
            # GitHub Actions annotation; visible in the run summary, does not fail the job.
            print(f"::warning title=source {name} failed::{record['sources'][name]}")
        # Bad responses never fail the workflow: they are recorded in the raw data.
        return 0

    if args.command == "download-parkendd":
        from konstanz_parking.parkendd import download

        files = download(args.dest, overwrite=args.overwrite)
        print(f"downloaded {len(files)} new files to {args.dest}")
        return 0

    if args.command == "coverage":
        from konstanz_parking.history.cli import coverage

        coverage(args.dumps, args.reports)
        return 0

    if args.command == "clean":
        from konstanz_parking.history.cli import clean

        clean(args.dumps, args.processed, args.reports)
        return 0

    if args.command == "fetch-aux":
        from konstanz_parking.history.cli import fetch_aux

        fetch_aux(args.external)
        return 0

    if args.command == "features":
        from konstanz_parking.history.cli import features

        features(args.processed, args.external, args.reports)
        return 0

    if args.command == "report":
        from konstanz_parking.history.report import build

        print(f"wrote {build(args.dumps, args.processed, args.reports)}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
