# Raw data branch

This branch holds **raw, append-only** parking snapshots written by the `collect` workflow
on `main`. Lines are never modified or deleted. The code lives on the `main` branch.

## Layout

```
data/raw/<source>/<YYYY-MM-DD>.jsonl   # one JSON object per poll, UTC day of the run
data/raw/runs/<YYYY-MM-DD>.jsonl       # one line per workflow run (actual timestamps)
```

Sources: `city_html`, `arcgis`, `parkapi_konstanz`, `parkapi_pbw`.

## Snapshot fields (schema_version 1)

`source`, `url`, `run_id`, `requested_at`, `received_at` (UTC ISO 8601), `attempts`
(every try with status/error/elapsed), `http_status`, `ok` (HTTP success),
`valid` (body looks as expected), `validation_note`, `rows`, `content_type`,
`body_bytes` and `body_sha256` (of the full response), `body_is_excerpt`, `body`
(UTF-8 text) or `body_base64` (if not UTF-8).

For `city_html`, `body` is a verbatim slice of the page containing the parking tables.

## Licensing

See "Data sources & licensing" in the README on `main`. The city web page data has
**no stated license**; ArcGIS/ParkAPI `konstanz` data is CC BY 4.0 © Stadt Konstanz.
