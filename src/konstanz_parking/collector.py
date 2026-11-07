"""Poll all parking sources once and append raw snapshots to daily JSONL files.

Design rules:
- Raw files are append-only. One JSON object per line, one file per source per UTC day.
- A bad response (timeout, HTTP error, malformed body) never raises: it is recorded,
  including whatever body was received.
- Every run is also logged to ``runs/<date>.jsonl`` with its actual timestamps, so gaps
  caused by delayed or skipped GitHub Actions cron runs can be detected later.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from konstanz_parking.sources import SOURCES, USER_AGENT, Source

SCHEMA_VERSION = 1
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}

log = logging.getLogger("konstanz_parking.collector")


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _encode_body(raw: bytes) -> tuple[str | None, str | None]:
    """Return (text, base64). Exactly one is set if raw is non-empty."""
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, base64.b64encode(raw).decode("ascii")


def fetch_source(
    client: httpx.Client,
    source: Source,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Fetch one source with retries. Never raises; always returns a snapshot record."""
    attempts: list[dict[str, Any]] = []
    last_response: httpx.Response | None = None
    requested_at = utc_now()

    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        entry: dict[str, Any] = {"attempt": attempt, "at": iso(utc_now())}
        retry = False
        try:
            response = client.get(source.url)
            last_response = response
            entry["status"] = response.status_code
            retry = response.status_code in RETRY_STATUS
        except httpx.HTTPError as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            retry = True
        except Exception as exc:  # noqa: BLE001 - must never crash the run
            entry["error"] = f"unexpected {type(exc).__name__}: {exc}"
            retry = True
        entry["elapsed_s"] = round(time.monotonic() - started, 3)
        attempts.append(entry)

        if not retry or attempt == max_attempts:
            break
        delay = max(source.min_retry_delay_s, 5.0 * 2 ** (attempt - 1))
        log.warning(
            "%s attempt %d failed (%s); retrying in %.0fs",
            source.name,
            attempt,
            entry.get("error") or entry.get("status"),
            delay,
        )
        sleep(delay)

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": source.name,
        "url": source.url,
        "requested_at": iso(requested_at),
        "received_at": iso(utc_now()),
        "attempts": attempts,
        "http_status": None,
        "ok": False,
        "error": attempts[-1].get("error"),
        "content_type": None,
        "body_bytes": None,
        "body_sha256": None,
        "body_is_excerpt": False,
        "body": None,
        "body_base64": None,
        "valid": None,
        "validation_note": None,
        "rows": None,
    }
    if last_response is None:
        return record

    try:
        raw = last_response.content
        record["http_status"] = last_response.status_code
        record["content_type"] = last_response.headers.get("content-type")
        record["body_bytes"] = len(raw)
        record["body_sha256"] = hashlib.sha256(raw).hexdigest()
        record["ok"] = last_response.is_success and record["error"] is None
        if not last_response.is_success and record["error"] is None:
            record["error"] = f"HTTP {last_response.status_code}"

        text, b64 = _encode_body(raw)
        if text is None:
            record["body_base64"] = b64
            record["valid"] = False
            record["validation_note"] = "body is not valid UTF-8"
            return record

        if source.validate is not None:
            result = source.validate(text)
            record["valid"] = result.valid
            record["validation_note"] = result.note
            record["rows"] = result.rows
        stored = text
        if source.excerpt is not None:
            stored, record["body_is_excerpt"] = source.excerpt(text)
        record["body"] = stored
    except Exception as exc:  # noqa: BLE001 - keep the raw body even if post-processing fails
        record["error"] = f"post-processing failed: {type(exc).__name__}: {exc}"
        record["body_base64"] = base64.b64encode(last_response.content).decode("ascii")
        record["body"] = None
    return record


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _github_context() -> dict[str, str | None]:
    keys = {
        "github_run_id": "GITHUB_RUN_ID",
        "github_run_attempt": "GITHUB_RUN_ATTEMPT",
        "github_event": "GITHUB_EVENT_NAME",
        "trigger": "COLLECT_TRIGGER",
        "github_sha": "GITHUB_SHA",
    }
    return {k: os.environ.get(v) for k, v in keys.items()}


def last_snapshot_time(data_dir: Path, now: datetime) -> datetime | None:
    """Start time of the most recent non-skipped run in today's or yesterday's run log."""
    latest: datetime | None = None
    for day in (now - timedelta(days=1), now):
        path = data_dir / "runs" / f"{day:%Y-%m-%d}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
                if rec.get("skipped"):
                    continue
                ts = datetime.fromisoformat(rec["started_at"].replace("Z", "+00:00"))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue  # a corrupt log line must not block collection
            if latest is None or ts > latest:
                latest = ts
    return latest


def run(
    data_dir: Path,
    sources: Iterable[Source] = SOURCES,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    min_interval_s: float = 0.0,
) -> dict[str, Any]:
    """Poll every source once, write snapshots and a run log entry. Returns the run record.

    If the previous snapshot is younger than ``min_interval_s`` (two triggers firing close
    together), nothing is fetched; only a ``skipped`` entry is written to the run log.
    """
    started_at = utc_now()
    day = started_at.strftime("%Y-%m-%d")
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    if min_interval_s > 0:
        last = last_snapshot_time(data_dir, started_at)
        if last is not None and (started_at - last).total_seconds() < min_interval_s:
            age = (started_at - last).total_seconds()
            log.info(
                "last snapshot %s is %.0fs old (< %.0fs): skipping", iso(last), age, min_interval_s
            )
            skip_record = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "started_at": iso(started_at),
                "finished_at": iso(utc_now()),
                **_github_context(),
                "skipped": True,
                "skip_reason": f"last snapshot {iso(last)} is {age:.0f}s old",
                "sources": {},
            }
            append_jsonl(data_dir / "runs" / f"{day}.jsonl", skip_record)
            return skip_record

    own_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    summary: dict[str, Any] = {}
    try:
        for source in sources:
            try:
                record = fetch_source(client, source, sleep=sleep)
            except Exception as exc:  # noqa: BLE001 - defensive; fetch_source should not raise
                record = {
                    "schema_version": SCHEMA_VERSION,
                    "source": source.name,
                    "url": source.url,
                    "requested_at": iso(utc_now()),
                    "ok": False,
                    "error": f"collector bug: {type(exc).__name__}: {exc}",
                }
            record["run_id"] = run_id
            append_jsonl(data_dir / source.name / f"{day}.jsonl", record)
            summary[source.name] = {
                "ok": record.get("ok"),
                "valid": record.get("valid"),
                "http_status": record.get("http_status"),
                "attempts": len(record.get("attempts", [])),
                "error": record.get("error"),
                "note": record.get("validation_note"),
            }
            level = logging.INFO if record.get("ok") and record.get("valid") else logging.WARNING
            log.log(level, "%s: %s", source.name, summary[source.name])
    finally:
        if own_client:
            client.close()

    run_record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": iso(started_at),
        "finished_at": iso(utc_now()),
        **_github_context(),
        "skipped": False,
        "sources": summary,
    }
    append_jsonl(data_dir / "runs" / f"{day}.jsonl", run_record)
    return run_record
