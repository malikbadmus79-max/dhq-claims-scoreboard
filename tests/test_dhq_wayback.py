import json
from datetime import date

import pandas as pd
import pytest

import scoreboard.dhq_wayback as dw
from scoreboard.fetch import Response


@pytest.fixture(autouse=True)
def quiet_log(monkeypatch):
    monkeypatch.setattr(dw, "log_access", lambda *a, **k: None)


class FakeFetcher:
    def __init__(self, pages):
        self.pages, self.requested, self.skip_reason = pages, [], None

    def get(self, url, params=None):
        key = (url, (params or {}).get("resumeKey")) if params else url
        self.requested.append(key)
        return self.pages.get(key)


HEADER = ["urlkey", "original", "timestamp", "groupcount", "endtimestamp"]


def test_cdx_rows_follow_resume_keys():
    page1 = [HEADER, ["k1", "https://defencehq.mil.ng/a", "20210105000000", "3", "20220101000000"], [], ["RK"]]
    page2 = [HEADER, ["k2", "https://defencehq.mil.ng/b", "20230105000000", "1", ""]]
    f = FakeFetcher({(dw.CDX_API, None): Response("u", 200, json.dumps(page1)),
                     (dw.CDX_API, "RK"): Response("u", 200, json.dumps(page2))})
    rows = dw.cdx_rows(f, date(2026, 10, 25))
    assert [r["urlkey"] for r in rows] == ["k1", "k2"]
    index = dw.index_table(rows)
    assert index.to_dict("records") == [
        {"original": "https://defencehq.mil.ng/a", "first_timestamp": "20210105000000",
         "last_timestamp": "20220101000000", "captures": 3},
        {"original": "https://defencehq.mil.ng/b", "first_timestamp": "20230105000000",
         "last_timestamp": "20230105000000", "captures": 1}]


@pytest.mark.parametrize("url,expected", [
    ("https://defencehq.mil.ng/index.php/2022/07/28/press-briefing-on-operations/",
     {"date": "2022-07-28", "slug": "press-briefing-on-operations"}),
    ("https://defencehq.mil.ng/2026/05/22/press-release-strikes/", {"date": "2026-05-22", "slug": "press-release-strikes"}),
    ("https://defencehq.mil.ng/index.php/2016/07/25/old-post-before-the-period/", None),
    ("https://defencehq.mil.ng/?p=1234", {"date": "", "slug": ""}),
    ("https://defencehq.mil.ng/news/operation-hadin-kai-air-interdiction-targeted", {"date": "",
     "slug": "operation-hadin-kai-air-interdiction-targeted"}),
    ("https://defencehq.mil.ng/press-briefing-by-directorate-of-defence-media-operations-on-1-december-2022/",
     {"date": "", "slug": "press-briefing-by-directorate-of-defence-media-operations-on-1-december-2022"}),
    ("https://defencehq.mil.ng/department-of-defence-training-operation/", None),
    ("https://defencehq.mil.ng/directorate-of-special-operation-force/", None),
    ("https://defencehq.mil.ng/departments/training-and-operations", None),
    ("https://defencehq.mil.ng/news?page=3", None),
    ("https://defencehq.mil.ng/cds", None),
])
def test_post_info(url, expected):
    assert dw.post_info(url) == expected


def test_candidates_by_slug_and_title(monkeypatch, tmp_path):
    index = pd.DataFrame({"original": ["https://defencehq.mil.ng/2022/07/28/press-briefing-on-operations/",
                                       "https://defencehq.mil.ng/2022/07/29/cds-visits-the-navy-school/",
                                       "https://defencehq.mil.ng/?p=1", "https://defencehq.mil.ng/?p=2"],
                          "first_timestamp": ["20220801000000", "20220801000000", "20230101000000", "20230101000000"],
                          "last_timestamp": [""] * 4, "captures": [1] * 4})
    cands = dw.slug_candidates(dw.post_pages(index))
    assert cands["original"].tolist() == [index["original"][0], index["original"][2], index["original"][3]]
    page = lambda title: Response("u", 200, f'<html><head><meta property="og:title" content="{title}">'
                                            f'<meta property="article:published_time" content="2023-01-12T10:00:00">'
                                            f"</head><body><article><p>{'word ' * 100}</p></article></body></html>")
    pages = {dw.SNAPSHOT_URL.format(timestamp=t, url=u): page(title) for u, t, title in zip(
        cands["original"], cands["first_timestamp"], ["Press briefing on operations", "Troops rescue hostages",
                                                      "Happy new year"])}
    monkeypatch.setattr(dw, "TEXT_DIR", tmp_path)
    fetched, texts = dw.fetch_candidates(FakeFetcher(pages), cands)
    assert fetched["title"].tolist() == ["Press briefing on operations", "Troops rescue hostages"]
    assert fetched["post_date"].tolist() == ["2022-07-28", "2023-01-12"]
    assert fetched["snapshot_url"].iloc[0].startswith("https://web.archive.org/web/20220801000000id_/")
    assert set(texts) == set(fetched["url"])
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(dw.text_file(u).name for u in fetched["url"])


def test_wayback_matches_carry_source_and_snapshot():
    cands = pd.DataFrame({"url": ["p1", "p2"], "post_date": ["2022-07-28", ""], "title": ["Press briefing", "x"],
                          "snapshot_timestamp": ["20240530054518", "1"], "snapshot_url": ["s1", "s2"],
                          "fetch_status": ["HTTP 200", "HTTP 200"]})
    briefings = pd.DataFrame({"briefing_id": ["B2022-015"], "first_date": ["2022-07-29"]})
    m = dw.wayback_matches(cands, {}, briefings, None)
    assert m.to_dict("records") == [{"briefing_id": "B2022-015", "post_url": "p1", "post_date": "2022-07-28",
                                     "match_basis": "date", "stated_period": "", "source": "wayback",
                                     "snapshot_timestamp": "20240530054518", "title": "Press briefing"}]
