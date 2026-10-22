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

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None, terms=None):
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
    collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher, state_dir=tmp_path / "state")
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

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None, terms=None):
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
    assert done[0][1:4] == (2024, _hit(1), 3)
    assert "time budget exceeded" in isolated_access_log.read_text(encoding="utf-8")


def test_budget_counts_retries_and_retry_waits(monkeypatch, isolated_access_log):
    import scoreboard.collect as collect
    from scoreboard.discover import BUDGET_STOP
    clock, searches, done = Clock(), [], []

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None, terms=None):
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

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None, terms=None):
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

    def fake_search(fetcher, domain, year, first, last, attempt, should_stop=None, terms=None):
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
    out = collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher, state_dir=tmp_path / "state")
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
        out = collect.run(date(2024, 1, 1), date(2024, 12, 31), tables_dir=tmp_path, fetcher_factory=StallingFetcher, state_dir=tmp_path / "state")
    finally:
        StallingFetcher.release.set()
        # The workers return before the temporary access log is torn down.
        for t in threading.enumerate():
            if t.daemon and t is not threading.current_thread():
                t.join(10)
    assert out["interrupted"] and out["saved"] == [("Voice of Nigeria", 2024)]
    assert _rows(yield_path)["outlet"].tolist() == ["Voice of Nigeria"]


# Spokesperson names as terms, and runs over some terms only (--terms --merge)


def test_full_collection_uses_pilot_terms_and_filter():
    import inspect
    import scoreboard.collect as collect
    from scoreboard.discover import SEARCH_TERMS
    hits = {"https://x.ng/e": {"title": "Troops kill 12 bandits", "excerpt": "Maj.-Gen. John Enenche said.",
                               "date": "2021-03-01", "terms": ["John Enenche"]}}
    assert candidate_rows("X", hits) == []  # a spokesperson name alone is not a DHQ reference
    assert SEARCH_TERMS == ["Defence Headquarters", "DHQ", "Defence Media Operations", "Buba"]
    assert inspect.signature(collect.collect_outlet).parameters["terms"].default == SEARCH_TERMS


def test_pilot_filter_ignores_spokesperson_names():
    from scoreboard.discover import is_candidate
    assert not is_candidate("Troops kill 12 bandits", "Maj.-Gen. John Enenche said.")


def test_merge_unions_rows_links_and_term_status(tmp_path):
    from scoreboard.collect import Saver
    order = ["A"]
    outlet = {"name": "A", "domain": "a.ng"}
    base = {**_hit(1), "https://x.ng/p": {"title": "Unrelated", "excerpt": "", "date": "2024-05-01", "terms": ["DHQ"]}}
    Saver(tmp_path, order, state_dir=tmp_path / "s").save(outlet, 2024, base, 0, {"DHQ": True, "Buba": True})
    later = {"https://x.ng/1": {**_hit(1)["https://x.ng/1"], "terms": ["Musa Danmadami"]}, **_hit(2)}
    later["https://x.ng/2"]["terms"] = ["Musa Danmadami"]
    Saver(tmp_path, order, merge=True, state_dir=tmp_path / "s").save(outlet, 2024, later, 0, {"Musa Danmadami": True})
    inv = _rows(tmp_path / "full_inventory_2024.csv").set_index("url")
    assert sorted(inv.index) == ["https://x.ng/1", "https://x.ng/2"]
    assert inv.loc["https://x.ng/1", "search_term_hits"] == "DHQ; Musa Danmadami"
    table = _rows(tmp_path / "full_yield_by_outlet_year.csv")
    # 3 distinct links across both runs; every term complete.
    assert table.values.tolist() == [["A", "2024", "3", "2", "0", "True"]]


def test_replace_run_resets_state(tmp_path):
    from scoreboard.collect import Saver
    outlet = {"name": "A", "domain": "a.ng"}
    Saver(tmp_path, ["A"], state_dir=tmp_path / "s").save(outlet, 2024, {**_hit(1), **_hit(2)}, 0, {"DHQ": True})
    Saver(tmp_path, ["A"], state_dir=tmp_path / "s").save(outlet, 2024, _hit(3), 0, {"DHQ": True})
    assert _rows(tmp_path / "full_yield_by_outlet_year.csv").values.tolist() == [["A", "2024", "1", "1", "0", "True"]]


def test_run_searches_only_the_given_terms(tmp_path):
    import scoreboard.collect as collect
    RecordingFetcher.requested = []
    collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher,
                terms=["John Enenche"], merge=True, state_dir=tmp_path / "state")
    searched = {u.split("search=")[1].split("&")[0] for u in RecordingFetcher.requested if "search=" in u}
    assert searched == {"John+Enenche"}


# A complete row is never replaced by an incomplete rerun


def test_incomplete_rerun_never_overwrites_complete_row(tmp_path, isolated_access_log):
    from scoreboard.collect import Saver
    outlet = {"name": "A", "domain": "a.ng"}
    Saver(tmp_path, ["A"], state_dir=tmp_path / "s").save(outlet, 2024, {**_hit(1), **_hit(2)}, 0, {"DHQ": True})
    inventory_before = (tmp_path / "full_inventory_2024.csv").read_text(encoding="utf-8")
    state_before = (tmp_path / "s" / "2024" / "a.ng.json").read_text(encoding="utf-8")
    saver = Saver(tmp_path, ["A"], state_dir=tmp_path / "s")
    saver.save(outlet, 2024, _hit(3), 1, {"DHQ": False})
    assert _rows(tmp_path / "full_yield_by_outlet_year.csv").values.tolist() == [["A", "2024", "2", "2", "0", "True"]]
    assert (tmp_path / "full_inventory_2024.csv").read_text(encoding="utf-8") == inventory_before
    assert (tmp_path / "s" / "2024" / "a.ng.json").read_text(encoding="utf-8") == state_before
    assert saver.kept == [("A", 2024)] and saver.saved == []
    log = isolated_access_log.read_text(encoding="utf-8")
    assert "incomplete rerun not saved" in log and "the complete row (2 posts, 2 candidates) is kept" in log


def test_incomplete_term_batch_never_overwrites_complete_row(tmp_path):
    from scoreboard.collect import Saver
    outlet = {"name": "A", "domain": "a.ng"}
    Saver(tmp_path, ["A"], state_dir=tmp_path / "s").save(outlet, 2024, _hit(1), 0, {"DHQ": True})
    saver = Saver(tmp_path, ["A"], merge=True, state_dir=tmp_path / "s")
    saver.save(outlet, 2024, _hit(2), 1, {"John Enenche": False})
    assert saver.kept == [("A", 2024)]
    assert _rows(tmp_path / "full_yield_by_outlet_year.csv").values.tolist() == [["A", "2024", "1", "1", "0", "True"]]


def test_newer_row_replaces_older_when_complete_or_older_incomplete(tmp_path):
    from scoreboard.collect import Saver
    outlet = {"name": "A", "domain": "a.ng"}
    s = tmp_path / "s"
    Saver(tmp_path, ["A"], state_dir=s).save(outlet, 2024, _hit(1), 2, {"DHQ": False, "Buba": False})
    Saver(tmp_path, ["A"], state_dir=s).save(outlet, 2024, {**_hit(1), **_hit(2)}, 1, {"DHQ": True, "Buba": False})
    assert _rows(tmp_path / "full_yield_by_outlet_year.csv").values.tolist() == [["A", "2024", "2", "2", "1", "False"]]
    Saver(tmp_path, ["A"], state_dir=s).save(outlet, 2024, _hit(3), 0, {"DHQ": True, "Buba": True})
    assert _rows(tmp_path / "full_yield_by_outlet_year.csv").values.tolist() == [["A", "2024", "1", "1", "0", "True"]]


def test_run_requests_only_the_named_outlets(tmp_path):
    import scoreboard.collect as collect
    RecordingFetcher.requested = []
    out = collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher,
                      state_dir=tmp_path / "state", outlets=["21st Century Chronicle"])
    hosts = {u.split("/")[2] for u in RecordingFetcher.requested}
    assert hosts == {"21stcenturychronicle.com"}  # no other outlet, and no DHQ robots.txt check
    assert out["saved"] == [("21st Century Chronicle", 2024)] and out["dhq"] == "not requested"


def test_run_rejects_unknown_outlet(tmp_path):
    import pytest
    import scoreboard.collect as collect
    with pytest.raises(ValueError):
        collect.run(date(2024, 1, 1), date(2024, 1, 31), tables_dir=tmp_path, fetcher_factory=RecordingFetcher,
                    state_dir=tmp_path / "state", outlets=["No Such Outlet"])


# add: links from the cached dry-search pages, added to the inventory once each


def _cache_search(fetcher, domain, term, year, posts):
    import json
    from datetime import date
    from scoreboard.collect import api_bounds
    from scoreboard.discover import FIELDS, PER_PAGE
    from scoreboard.fetch import Response, full_url
    after, before = api_bounds(date(year, 1, 1), date(year, 12, 31))
    params = {"search": term, "after": after, "before": before, "_fields": FIELDS}
    url = f"https://{domain}/wp-json/wp/v2/posts"
    fetcher._write_cache(Response(full_url(url, {**params, "per_page": PER_PAGE, "page": 1}), 200, json.dumps(posts), {}))


def _post(link, title, excerpt="", day="2021-03-01"):
    return {"link": link, "date": f"{day}T10:00:00", "title": {"rendered": title}, "excerpt": {"rendered": excerpt}}


def test_add_from_cache_adds_distinct_links_once_and_flags_them(tmp_path):
    from scoreboard.config import load_config
    from scoreboard.fetch import Fetcher
    from scoreboard.spokesperson import add_from_cache
    tables = tmp_path / "tables"
    tables.mkdir()
    # An inventory written before added_by existed.
    (tables / "full_inventory_2021.csv").write_text(
        "outlet,url,title,publish_date,search_term_hits,period_phrase,matched_field,kept_by_title_alone,"
        "briefing_group_id,grouping_status\n"
        "Daily Post,https://dailypost.ng/old,Troops neutralise 9 terrorists - DHQ,2021-03-01,DHQ,,title,True,F2021-001,provisional\n",
        encoding="utf-8")
    fetcher = Fetcher(load_config(), cache_dir=tmp_path / "cache", offline=True)
    enenche = _post("https://dailypost.ng/new", "Troops kill 12 bandits", "Maj.-Gen. John Enenche said.")
    onyeuko = _post("https://dailypost.ng/two", "Troops rescue 5", "Brig.-Gen. Bernard Onyeuko and Benard Onyeuko said.")
    _cache_search(fetcher, "dailypost.ng", "John Enenche", 2021, [enenche, _post("https://dailypost.ng/old", "x")])
    _cache_search(fetcher, "dailypost.ng", "Bernard Onyeuko", 2021, [onyeuko])
    _cache_search(fetcher, "dailypost.ng", "Benard Onyeuko", 2021, [onyeuko])
    _cache_search(fetcher, "dailypost.ng", "Musa Danmadami", 2021, [_post("https://dailypost.ng/nodhq", "Flood in Kano")])
    added = add_from_cache(tables_dir=tables, fetcher=fetcher)
    assert sorted(added["url"]) == ["https://dailypost.ng/new", "https://dailypost.ng/two"]
    inv = _rows(tables / "full_inventory_2021.csv").set_index("url")
    assert inv.loc["https://dailypost.ng/old", "added_by"] == "discovery"
    assert inv.loc["https://dailypost.ng/new", "added_by"] == "spokesperson_check"
    assert inv.loc["https://dailypost.ng/two", "search_term_hits"] == "Bernard Onyeuko; Benard Onyeuko"
    # A second run adds nothing.
    assert add_from_cache(tables_dir=tables, fetcher=fetcher).empty


def test_discovery_save_keeps_check_rows_and_counts_discovery_only(tmp_path):
    from scoreboard.collect import Saver
    saver = Saver(tmp_path, ["A"], state_dir=tmp_path / "s")
    saver.save({"name": "A", "domain": "a.ng"}, 2024, _hit(1), 0, {"DHQ": True})
    path = tmp_path / "full_inventory_2024.csv"
    inv = _rows(path)
    extra = inv.iloc[[0]].assign(url="https://x.ng/check", added_by="spokesperson_check")
    import pandas as pd
    pd.concat([inv, extra]).to_csv(path, index=False)
    Saver(tmp_path, ["A"], state_dir=tmp_path / "s").save({"name": "A", "domain": "a.ng"}, 2024, _hit(2), 0, {"DHQ": True})
    inv = _rows(path).set_index("url")
    assert inv.loc["https://x.ng/check", "added_by"] == "spokesperson_check"
    assert "https://x.ng/1" not in inv.index and inv.loc["https://x.ng/2", "added_by"] == "discovery"
    assert _rows(tmp_path / "full_yield_by_outlet_year.csv")["candidates"].tolist() == ["1"]
