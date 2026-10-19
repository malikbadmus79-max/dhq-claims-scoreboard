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

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None):
        n = len([c for c in calls if c[0] == year])
        calls.append((year, attempt))
        return {f"https://x.ng/{year}": {"date": f"{year}-05-01"}}, {"capped": 0, "incomplete": outcomes[(year, n)],
                                                                 "stops": []}

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


# Time budget per outlet-year

YEAR_2024 = [(2024, date(2024, 1, 1), date(2024, 12, 31))]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _hit(n):
    return {f"https://x.ng/{n}": {"title": "Troops neutralise 40 terrorists - DHQ", "excerpt": "",
                                 "date": "2024-05-01", "terms": ["DHQ"]}}


def test_budget_stops_search_marks_incomplete_and_logs(monkeypatch, isolated_access_log):
    import scoreboard.collect as collect
    from scoreboard.discover import BUDGET_STOP
    clock, searches, done = Clock(), [], []

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None):
        searches.append(attempt)
        clock.now += 16 * 60  # past the 15-minute budget mid-search
        assert should_stop()
        return _hit(1), {"capped": 0, "incomplete": 3, "stops": ["empty page", BUDGET_STOP, BUDGET_STOP, BUDGET_STOP]}

    monkeypatch.setattr(collect, "probe_api", lambda f, d: "yes")
    monkeypatch.setattr(collect, "_search_year", fake_search)
    out = collect.collect_outlet({"name": "X", "domain": "x.ng"}, YEAR_2024, 15 * 60, sleep=clock.sleep,
                                 fetcher=object(), clock=clock, on_done=lambda *a: done.append(a))
    assert searches == ["first pass"]  # no retry after the budget is spent
    assert out["incomplete"][2024] == 3 and out["reasons"][2024] == BUDGET_STOP
    assert done[0][1:] == (2024, _hit(1), 3)
    assert "time budget exceeded" in isolated_access_log.read_text(encoding="utf-8")


def test_budget_counts_retries_and_retry_waits(monkeypatch, isolated_access_log):
    import scoreboard.collect as collect
    from scoreboard.discover import BUDGET_STOP
    clock, searches, done = Clock(), [], []

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None):
        searches.append(attempt)
        clock.now += 14.5 * 60  # first pass ends inside the budget, still incomplete
        return _hit(len(searches)), {"capped": 0, "incomplete": 2, "stops": ["request failed"] * 2 + ["empty page"] * 2}

    monkeypatch.setattr(collect, "probe_api", lambda f, d: "yes")
    monkeypatch.setattr(collect, "_search_year", fake_search)
    out = collect.collect_outlet({"name": "X", "domain": "x.ng"}, YEAR_2024, 15 * 60, sleep=clock.sleep,
                                 fetcher=object(), clock=clock, on_done=lambda *a: done.append(a))
    # The 60 s retry wait takes the outlet-year past 15 minutes: no retry search is run.
    assert searches == ["first pass"]
    assert out["reasons"][2024] == BUDGET_STOP and done[0][3] == 2
    assert "time budget exceeded" in isolated_access_log.read_text(encoding="utf-8")


def test_failed_requests_reason_without_budget(monkeypatch):
    import scoreboard.collect as collect

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None):
        return _hit(1), {"capped": 0, "incomplete": 2, "stops": ["HTTP 500", "request failed", "empty page", "empty page"]}

    monkeypatch.setattr(collect, "probe_api", lambda f, d: "yes")
    monkeypatch.setattr(collect, "_search_year", fake_search)
    out = collect.collect_outlet({"name": "X", "domain": "x.ng"}, YEAR_2024, 15 * 60, sleep=lambda s: None,
                                 fetcher=object(), clock=Clock())
    assert out["reasons"][2024] == "HTTP 500 x1; request failed x1"


def test_budget_cancels_fetcher_requests(monkeypatch):
    import scoreboard.collect as collect
    clock = Clock()

    class F:
        cancel = None

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None):
        assert fetcher.cancel() is False
        clock.now += 20 * 60
        assert fetcher.cancel() is True
        return {}, {"capped": 0, "incomplete": 4, "stops": ["time budget exceeded"] * 4}

    monkeypatch.setattr(collect, "probe_api", lambda f, d: "yes")
    monkeypatch.setattr(collect, "_search_year", fake_search)
    collect.collect_outlet({"name": "X", "domain": "x.ng"}, YEAR_2024, 15 * 60, fetcher=F(), clock=clock)


# Save as you go


def _rows(path):
    import pandas as pd
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def test_saver_merges_yield_by_outlet_and_year(tmp_path):
    from scoreboard.collect import YIELD_COLUMNS, Saver
    path = tmp_path / "full_yield_by_outlet_year.csv"
    path.write_text(",".join(YIELD_COLUMNS) + "\nB,2023,5,1,0,True\nA,2022,9,2,0,True\nA,2023,1,0,3,False\n",
                    encoding="utf-8")
    saver = Saver(tmp_path, ["A", "B"])
    saver.save({"name": "A"}, 2023, _hit(1), 0)
    assert _rows(path).values.tolist() == [
        ["A", "2022", "9", "2", "0", "True"],
        ["A", "2023", "1", "1", "0", "True"],  # the newer row replaced the older one
        ["B", "2023", "5", "1", "0", "True"],
    ]


def test_saver_replaces_only_that_outlets_inventory_rows(tmp_path):
    from scoreboard.collect import Saver
    saver = Saver(tmp_path, ["A", "B"])
    saver.save({"name": "B"}, 2024, _hit(9), 0)
    saver.save({"name": "A"}, 2024, {**_hit(1), **_hit(2)}, 0)
    saver.save({"name": "A"}, 2024, _hit(3), 0)  # a later run replaces the rows of A only
    inv = _rows(tmp_path / "full_inventory_2024.csv")
    assert sorted(zip(inv["outlet"], inv["url"])) == [("A", "https://x.ng/3"), ("B", "https://x.ng/9")]
    # Both copies share the figure 40 on the same day: one briefing group across outlets.
    assert inv["briefing_group_id"].nunique() == 1


def test_saver_writes_nothing_after_close(tmp_path):
    from scoreboard.collect import Saver
    saver = Saver(tmp_path, ["A"])
    saver.close()
    saver.save({"name": "A"}, 2024, _hit(1), 0)
    assert list(tmp_path.iterdir()) == [] and saver.saved == []


def test_run_writes_each_outlet_year_and_merges_with_earlier_runs(tmp_path):
    import scoreboard.collect as collect
    from scoreboard.collect import YIELD_COLUMNS
    path = tmp_path / "full_yield_by_outlet_year.csv"
    path.write_text(",".join(YIELD_COLUMNS) + "\nPremium Times,2021,7,1,0,True\nPremium Times,2024,,,4,False\n",
                    encoding="utf-8")
    RecordingFetcher.requested = []
    out = collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher)
    table = _rows(path)
    assert ["Premium Times", "2021", "7", "1", "0", "True"] in table.values.tolist()
    assert table[(table["outlet"] == "Premium Times") & (table["year"] == "2024")].values.tolist() == [
        ["Premium Times", "2024", "0", "0", "0", "True"]]
    assert (table["year"] == "2024").sum() == len(out["saved"]) == 14
    assert (tmp_path / "full_inventory_2024.csv").exists()


class StallingFetcher(RecordingFetcher):
    """Voice of Nigeria answers at once; every other outlet stalls until released."""

    release = None

    def get(self, url, params=None):
        if "von.gov.ng" not in url:
            StallingFetcher.release.wait(10)
        return super().get(url, params)


def test_keyboard_interrupt_keeps_finished_outlet_years(tmp_path, monkeypatch):
    import threading
    import time
    import scoreboard.collect as collect
    StallingFetcher.release = threading.Event()
    yield_path = tmp_path / "full_yield_by_outlet_year.csv"

    def interrupt_after_first_save(threads):
        deadline = time.monotonic() + 10
        while not yield_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        raise KeyboardInterrupt

    monkeypatch.setattr(collect, "_join", interrupt_after_first_save)
    try:
        out = collect.run(date(2024, 1, 1), date(2024, 12, 31), tables_dir=tmp_path, fetcher_factory=StallingFetcher)
    finally:
        StallingFetcher.release.set()
        # The workers return before the temporary access log is torn down.
        for t in threading.enumerate():
            if t.daemon and t is not threading.current_thread():
                t.join(10)
    assert out["interrupted"] and out["saved"] == [("Voice of Nigeria", 2024)]
    assert _rows(yield_path)["outlet"].tolist() == ["Voice of Nigeria"]
