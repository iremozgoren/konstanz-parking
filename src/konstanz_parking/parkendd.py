"""Download the historical ParkenDD dumps for Konstanz (2015-2022).

The dumps carry no explicit license, so they are written to a gitignored folder
(``data/external/parkendd/`` by default) and must never be committed.
Format of each CSV: ``utc_timestamp,free_spaces`` (rows are not sorted).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from konstanz_parking.sources import USER_AGENT

DUMPS_URL = "https://parkendd.de/dumps/"
_FILE_RE = re.compile(r'href="(konstanz[^"/]*\.csv)"')
POLITE_DELAY_S = 2.0

log = logging.getLogger("konstanz_parking.parkendd")


def list_konstanz_files(index_html: str) -> list[str]:
    return sorted(set(_FILE_RE.findall(index_html)))


def download(
    dest: Path,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    overwrite: bool = False,
) -> list[Path]:
    """Download every Konstanz dump into ``dest``. Existing files are skipped."""
    own_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=15.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        index = client.get(DUMPS_URL)
        index.raise_for_status()
        names = list_konstanz_files(index.text)
        log.info("found %d Konstanz dump files", len(names))
        for name in names:
            target = dest / name
            if target.exists() and not overwrite:
                continue
            sleep(POLITE_DELAY_S)
            resp = client.get(DUMPS_URL + name)
            if not resp.is_success:
                log.warning("skipping %s: HTTP %d", name, resp.status_code)
                continue
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(resp.content)
            tmp.rename(target)
            written.append(target)
            log.info("downloaded %s (%d bytes)", name, len(resp.content))
    finally:
        if own_client:
            client.close()
    return written
