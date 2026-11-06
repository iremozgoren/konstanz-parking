import json
from pathlib import Path

import httpx
import pytest

from konstanz_parking import collector
from konstanz_parking.parkendd import list_konstanz_files
from konstanz_parking.sources import (
    USER_AGENT,
    Source,
    city_html_excerpt,
    validate_arcgis,
    validate_city_html,
    validate_parkapi,
)

# Synthetic page mimicking the structure of the city's Parkleitsystem page.
CITY_HTML = """<html><nav>lots of navigation</nav>
<table class="parken-header"><tr><td>Parkmöglichkeit</td><td>freie Plätze</td></tr></table>
<!-- custom-knParken-simple.vm -->
<table class="parken">
  <tr><td class="tdleft"><a href="/x/parkhaus+altstadt/Parkhaus.html">Altstadt</a></td>
      <td class="tdright gleichbleibend">95</td></tr>
</table>
<table class="parken">
  <tr><td class="tdleft"><a href="/x/parkhaus+augustiner/Parkhaus.html">Augustiner</a></td>
      <td class="tdright">XXX</td></tr>
</table>
<footer>footer</footer></html>"""


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": USER_AGENT})


def no_sleep(_: float) -> None:
    pass


# --- source helpers -------------------------------------------------------------------------


def test_city_html_excerpt_is_verbatim_slice():
    excerpt, is_excerpt = city_html_excerpt(CITY_HTML)
    assert is_excerpt
    assert excerpt in CITY_HTML
    assert excerpt.startswith('<table class="parken-header">')
    assert excerpt.endswith("</table>")
    assert "Augustiner" in excerpt and "footer" not in excerpt


def test_city_html_excerpt_falls_back_to_full_body():
    body = "<html>redesigned page</html>"
    assert city_html_excerpt(body) == (body, False)


OUTAGE_HTML = """<nav>menu</nav>
<table class="parken-header"><tr><td>Parkmöglichkeit</td></tr></table>
<div class="boxChild"></div>
<table class="parken-header"><tr><td>Parkmöglichkeit</td></tr></table>
<p><i>Derzeit sind keine aktuellen Belegungszahlen verfügbar.</i></p>
<footer>footer</footer>"""


def test_outage_page_is_excerpted_and_flagged():
    excerpt, is_excerpt = city_html_excerpt(OUTAGE_HTML)
    assert is_excerpt and excerpt in OUTAGE_HTML
    assert excerpt.endswith("</p>") and "footer" not in excerpt
    result = validate_city_html(OUTAGE_HTML)
    assert not result.valid and result.note == "city reports no current occupancy data"


def test_validate_city_html_counts_rows():
    result = validate_city_html(CITY_HTML)
    assert result.valid and result.rows == 2
    assert result.note == "1 numeric of 2 rows"
    assert not validate_city_html("<html></html>").valid


def test_validate_json_sources():
    arcgis = {"features": [{"attributes": {"real_fcap": 3}}, {"attributes": {"real_fcap": None}}]}
    assert validate_arcgis(json.dumps(arcgis)).note == "1 of 2 with real_fcap"
    assert not validate_arcgis('{"error": {"code": 500}}').valid
    assert not validate_arcgis("not json").valid
    assert validate_parkapi('{"items": [{"realtime_free_capacity": 1}]}').valid
    assert not validate_parkapi("[]").valid


# --- fetching --------------------------------------------------------------------------------


def test_retries_then_succeeds_and_respects_min_delay():
    calls = {"n": 0}
    delays: list[float] = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, text='{"items": []}')

    src = Source("s", "https://example.org/a", min_retry_delay_s=30.0, validate=validate_parkapi)
    record = collector.fetch_source(make_client(handler), src, sleep=delays.append)
    assert record["ok"] and record["valid"]
    assert [a["status"] for a in record["attempts"]] == [503, 503, 200]
    assert delays and min(delays) >= 30.0


def test_network_error_never_raises():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    record = collector.fetch_source(make_client(handler), Source("s", "https://e.org"), no_sleep)
    assert record["ok"] is False
    assert "ConnectTimeout" in record["error"]
    assert len(record["attempts"]) == collector.MAX_ATTEMPTS
    assert record["body"] is None


def test_malformed_body_is_stored():
    def handler(request):
        return httpx.Response(200, text="<html>maintenance</html>")

    src = Source("s", "https://e.org", validate=validate_arcgis)
    record = collector.fetch_source(make_client(handler), src, no_sleep)
    assert record["ok"] is True and record["valid"] is False
    assert record["body"] == "<html>maintenance</html>"
    assert len(record["attempts"]) == 1


def test_http_error_stores_body_without_retry_on_404():
    def handler(request):
        return httpx.Response(404, text="gone")

    record = collector.fetch_source(make_client(handler), Source("s", "https://e.org"), no_sleep)
    assert record["ok"] is False and record["error"] == "HTTP 404"
    assert record["body"] == "gone" and len(record["attempts"]) == 1


def test_non_utf8_body_stored_as_base64():
    def handler(request):
        return httpx.Response(200, content=b"\xff\xfe\x00bad")

    record = collector.fetch_source(make_client(handler), Source("s", "https://e.org"), no_sleep)
    assert record["body"] is None and record["body_base64"]
    assert record["valid"] is False


def test_failing_validator_keeps_raw_body():
    def boom(_: str):
        raise RuntimeError("bug")

    def handler(request):
        return httpx.Response(200, text="payload")

    src = Source("s", "https://e.org", validate=boom)
    record = collector.fetch_source(make_client(handler), src, no_sleep)
    assert "post-processing failed" in record["error"]
    assert record["body_base64"]


# --- full run --------------------------------------------------------------------------------


def test_run_appends_daily_files_and_run_log(tmp_path: Path):
    seen_agents = []

    def handler(request):
        seen_agents.append(request.headers["user-agent"])
        if "city" in str(request.url):
            return httpx.Response(200, text=CITY_HTML)
        raise httpx.ReadTimeout("slow", request=request)

    sources = [
        Source(
            "city", "https://e.org/city", excerpt=city_html_excerpt, validate=validate_city_html
        ),
        Source("broken", "https://e.org/broken"),
    ]
    client = make_client(handler)
    first = collector.run(tmp_path, sources, client=client, sleep=no_sleep)
    collector.run(tmp_path, sources, client=client, sleep=no_sleep)

    day = first["started_at"][:10]
    city_lines = (tmp_path / "city" / f"{day}.jsonl").read_text().splitlines()
    assert len(city_lines) == 2  # appended, not overwritten
    city = json.loads(city_lines[0])
    assert city["body_is_excerpt"] and "footer" not in city["body"]
    assert city["run_id"] == first["run_id"]

    broken = json.loads((tmp_path / "broken" / f"{day}.jsonl").read_text().splitlines()[0])
    assert broken["ok"] is False

    runs = (tmp_path / "runs" / f"{day}.jsonl").read_text().splitlines()
    assert len(runs) == 2
    run_rec = json.loads(runs[0])
    assert run_rec["started_at"] <= run_rec["finished_at"]
    assert run_rec["sources"]["broken"]["ok"] is False
    assert all("irem11314@gmail.com" in ua for ua in seen_agents)


def test_cli_collect_returns_zero_when_all_sources_fail(tmp_path, monkeypatch):
    from konstanz_parking import main

    def handler(request):
        raise httpx.ConnectError("down", request=request)

    real_run = collector.run

    def fake_run(data_dir):
        return real_run(data_dir, client=make_client(handler), sleep=no_sleep)

    monkeypatch.setattr(collector, "run", fake_run)
    assert main(["collect", "--data-dir", str(tmp_path)]) == 0


@pytest.mark.parametrize(
    "html,expected",
    [
        (
            '<a href="konstanzlago-2020.csv">x</a><a href="dresden-2020.csv">',
            ["konstanzlago-2020.csv"],
        ),
        ('<a href="konstanzaltstadt-2015.backup.csv">', ["konstanzaltstadt-2015.backup.csv"]),
    ],
)
def test_parkendd_index_parsing(html, expected):
    assert list_konstanz_files(html) == expected
