import json
from datetime import date

from scoreboard.collect import api_bounds, candidate_rows, year_windows, yield_row
from scoreboard.fetch import Response


def test_year_windows_end_at_run_date():
    windows = year_windows(date(2021, 1, 1), date(2026, 10, 18))
    assert windows[0] == (2021, date(2021, 1, 1), date(2021, 12, 31))
    assert windows[-1] == (2026, date(2026, 1, 1), date(2026, 10, 18))
    assert len(windows) == 6


def test_api_bounds_match_pilot_strings_for_a_full_year():
    assert api_bounds(date(2024, 1, 1), date(2024, 12, 31)) == ("2023-12-31T23:59:59", "2025-01-01T00:00:00")
    assert api_bounds(date(2026, 1, 1), date(2026, 10, 18)) == ("2025-12-31T23:59:59", "2026-10-19T00:00:00")


def test_candidate_rows_keep_marwa_exclusion():
    hits = {
        "https://x.ng/a": {"title": "Buba Marwa: NDLEA arrests 40 suspects", "excerpt": "", "date": "2023-01-02",
                           "terms": ["Buba"]},
        "https://x.ng/b": {"title": "Troops neutralise 40 terrorists – DHQ", "excerpt": "", "date": "2023-01-02",
                           "terms": ["DHQ"]},
    }
    rows = candidate_rows("Daily Post", hits)
    assert [r["url"] for r in rows] == ["https://x.ng/b"]


def test_collect_outlet_retries_incomplete_years(monkeypatch):
    import scoreboard.collect as collect
    calls = []
    outcomes = {(2023, 0): 1, (2024, 0): 0, (2023, 1): 0}

    def fake_search(fetcher, domain, year, first, last, attempt):
        n = len([c for c in calls if c[0] == year])
        calls.append((year, attempt))
        return {f"https://x.ng/{year}": {"date": f"{year}-05-01"}}, {"capped": 0, "incomplete": outcomes[(year, n)]}

    monkeypatch.setattr(collect, "Fetcher", lambda: object())
    monkeypatch.setattr(collect, "probe_api", lambda f, d: "yes")
    monkeypatch.setattr(collect, "_search_year", fake_search)
    windows = [(2023, date(2023, 1, 1), date(2023, 12, 31)), (2024, date(2024, 1, 1), date(2024, 12, 31))]
    waits = []
    out = collect.collect_outlet({"name": "X", "domain": "x.ng"}, windows, sleep=waits.append)
    assert calls == [(2023, "first pass"), (2024, "first pass"), (2023, "retry 1")]
    assert out["incomplete"] == {2023: 0, 2024: 0}
    assert waits == [collect.RETRY_WAIT_SECONDS]


def test_outlet_without_api_is_logged_and_never_searched(monkeypatch, isolated_access_log):
    import scoreboard.collect as collect
    searched = []
    monkeypatch.setattr(collect, "probe_api", lambda f, d: "no API (HTTP 404)")
    monkeypatch.setattr(collect, "_search_year", lambda *a: searched.append(a))
    out = collect.collect_outlet({"name": "AllAfrica", "domain": "allafrica.com"},
                                 [(2024, date(2024, 1, 1), date(2024, 12, 31))], fetcher=object())
    assert searched == [] and out["years"] == {}
    log = isolated_access_log.read_text(encoding="utf-8")
    assert "allafrica.com" in log and "not searched" in log


def test_yield_row_marks_incomplete_and_never_reports_failed_search_as_zero():
    assert yield_row("X", 2024, 120, 30, 0) == {
        "outlet": "X", "year": 2024, "api_posts_returned": 120, "candidates": 30,
        "incomplete_queries": 0, "complete": True}
    partial = yield_row("X", 2024, 120, 30, 2)
    assert (partial["api_posts_returned"], partial["candidates"], partial["complete"]) == (120, 30, False)
    failed = yield_row("X", 2025, 0, 0, 4)
    assert (failed["api_posts_returned"], failed["candidates"], failed["complete"]) == ("", "", False)
    # A complete year with no posts is a real 0.
    assert yield_row("X", 2021, 0, 0, 0)["api_posts_returned"] == 0


class RecordingFetcher:
    """Answers every request with an empty JSON list and records each URL requested."""

    requested: list[str] = []

    def __init__(self, *args, **kwargs):
        self.skip_reason = None

    def check_robots(self, url):
        RecordingFetcher.requested.append(url)
        return True, "HTTP 200"

    def get(self, url, params=None):
        from scoreboard.fetch import full_url
        full = full_url(url, params)
        RecordingFetcher.requested.append(full)
        return Response(full, 200, "[]", {})


def test_discovery_makes_no_wayback_requests(tmp_path):
    import scoreboard.collect as collect
    RecordingFetcher.requested = []
    collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher)
    assert RecordingFetcher.requested, "the fake fetcher was not used"
    assert any("/wp-json/wp/v2/posts" in u for u in RecordingFetcher.requested)
    assert not [u for u in RecordingFetcher.requested if "archive.org" in u]
