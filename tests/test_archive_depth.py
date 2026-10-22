import json
from datetime import date

from scoreboard.archive_depth import FIELDS, outlet_rows
from scoreboard.collect import api_bounds
from scoreboard.config import load_config
from scoreboard.fetch import Fetcher, Response, full_url

URL = "https://x.ng/wp-json/wp/v2/posts"


def _cache(fetcher, params, body):
    fetcher._write_cache(Response(full_url(URL, params), 200, json.dumps(body), {}))


def _year_params(year):
    after, before = api_bounds(date(year, 1, 1), min(date(year, 12, 31), date(2026, 10, 18)))
    return {"after": after, "before": before, "per_page": 100, "_fields": FIELDS}


def test_cached_page_is_parsed_and_classified(tmp_path):
    fetcher = Fetcher(load_config(), cache_dir=tmp_path, offline=True)
    _cache(fetcher, {"order": "asc", "per_page": 1, "_fields": FIELDS}, [{"date": "2019-02-01T08:00:00", "link": "a"}])
    _cache(fetcher, {"order": "desc", "per_page": 1, "_fields": FIELDS}, [{"date": "2026-10-18T09:00:00", "link": "z"}])
    _cache(fetcher, _year_params(2021), [{"date": "2021-12-31T10:00:00", "link": "b"},
                                         {"date": "2021-03-02T10:00:00", "link": "c"}])
    _cache(fetcher, _year_params(2022), [])
    rows = {r["year"]: r for r in outlet_rows({"name": "X", "domain": "x.ng"}, fetcher)}
    assert rows[2021]["classification"] == "thin"  # 2 posts in the year
    assert (rows[2021]["posts_on_page_1"], rows[2021]["earliest_on_page_1"], rows[2021]["latest_on_page_1"]) == (
        2, "2021-03-02", "2021-12-31")
    assert (rows[2021]["outlet_earliest_post"], rows[2021]["outlet_latest_post"]) == ("2019-02-01", "2026-10-18")
    assert rows[2022]["classification"] == "archive missing" and rows[2022]["posts_on_page_1"] == 0
    # Not cached and offline: no request is sent, and the year is not classified as missing.
    assert rows[2023]["classification"].startswith("not checked")


def test_posts_outside_the_year_do_not_count_as_present(tmp_path):
    fetcher = Fetcher(load_config(), cache_dir=tmp_path, offline=True)
    _cache(fetcher, _year_params(2024), [{"date": "2019-05-01T10:00:00", "link": "old"}])
    row = next(r for r in outlet_rows({"name": "X", "domain": "x.ng"}, fetcher) if r["year"] == 2024)
    assert row["classification"] == "archive missing" and row["posts_outside_window"] == 1


def test_classes_from_posts_in_the_year():
    from scoreboard.archive_depth import classify
    assert classify("HTTP 200", 100) == "archive present"
    assert classify("HTTP 200", 99) == "thin"
    assert classify("HTTP 200", 1) == "thin"
    assert classify("HTTP 200", 0) == "archive missing"
    assert classify("HTTP 500", None) == "not checked (HTTP 500)"


def test_reclassify_uses_saved_table_only(tmp_path):
    from scoreboard.archive_depth import COLUMNS, reclassify
    import pandas as pd
    rows = [["V", "v.ng", 2022, "HTTP 200", 1, 0, "2022-01-19", "2022-01-19", "", "", "archive present"],
            ["V", "v.ng", 2023, "HTTP 200", 100, 0, "2023-05-23", "2023-05-24", "", "", "archive present"],
            ["V", "v.ng", 2024, "HTTP 500", "", "", "", "", "", "", "not checked (HTTP 500)"]]
    pd.DataFrame(rows, columns=COLUMNS).to_csv(tmp_path / "full_archive_depth.csv", index=False)
    table = reclassify(tables_dir=tmp_path)
    assert table["classification"].tolist() == ["thin", "archive present", "not checked (HTTP 500)"]


def test_full_page_reaching_january_is_thin():
    from scoreboard.archive_depth import classify
    # Newest first: 100 posts reaching back to January mean the year holds little more than 100.
    assert classify("HTTP 200", 100, 2021, "2021-01-21") == "thin"
    assert classify("HTTP 200", 100, 2021, "2021-12-29") == "archive present"
    assert classify("HTTP 200", 100, 2022, "2021-01-05") == "archive present"  # January of another year


def test_reclassify_keeps_one_row_per_outlet_and_year(tmp_path):
    from scoreboard.archive_depth import COLUMNS, reclassify
    import pandas as pd
    row = ["L", "l.ng", 2021, "HTTP 200", 100, 0, "2021-01-21", "2021-12-29", "", "", "archive present"]
    pd.DataFrame([row, row], columns=COLUMNS).to_csv(tmp_path / "full_archive_depth.csv", index=False)
    table = reclassify(tables_dir=tmp_path)
    assert len(table) == 1 and table["classification"].tolist() == ["thin"]
