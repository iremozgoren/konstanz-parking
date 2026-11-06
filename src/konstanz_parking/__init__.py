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

    p_dl = sub.add_parser("download-parkendd", help="download historical ParkenDD dumps")
    p_dl.add_argument("--dest", type=Path, default=Path("data/external/parkendd"))
    p_dl.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    if args.command == "collect":
        from konstanz_parking.collector import run

        record = run(args.data_dir)
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

    return 2


if __name__ == "__main__":
    sys.exit(main())
