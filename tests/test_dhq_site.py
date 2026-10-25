import json
from datetime import date

import pandas as pd
import pytest

import scoreboard.dhq_site as ds
from scoreboard.fetch import Response


class FakeFetcher:
    """Answers from a dict of url -> Response; anything else fails. robots: (allowed, status)."""

    def __init__(self, pages=None, robots=(True, "HTTP 200")):
        self.pages, self.robots, self.requested, self.skip_reason = pages or {}, robots, [], None

    def check_robots(self, url):
        return self.robots

    def get(self, url, params=None):
        key = url if params is None else (url, params.get("page"))
        self.requested.append(key)
        self.skip_reason = None if key in self.pages else "request failed"
        return self.pages.get(key)


@pytest.fixture(autouse=True)
def quiet_log(monkeypatch):
    monkeypatch.setattr(ds, "log_access", lambda *a, **k: None)


def api_page(posts, total_pages):
    return Response("u", 200, json.dumps(posts), {"X-WP-TotalPages": str(total_pages)})


END = date(2026, 10, 25)


def test_unreachable_robots_lists_nothing_and_requests_nothing():
    f = FakeFetcher(robots=(False, "unreachable"))
    posts, method = ds.list_posts(f, END)
    assert posts.empty and method == "not listed: robots.txt unreachable" and f.requested == []


def test_rest_api_is_paged_and_titles_cleaned():
    api = ds.ORIGIN + ds.API_PATHS[0]
    f = FakeFetcher({
        (api, 1): api_page([{"id": 1, "date": "2021-01-07T10:00:00", "link": "https://x/a",
                             "title": {"rendered": "UPDATE ON ARMED FORCES OF NIGERIA OPERATIONS &#8211; 1"}}], 2),
        (api, 2): api_page([{"id": 2, "date": "2021-01-21T10:00:00", "link": "https://x/b",
                             "title": {"rendered": "<b>Visit</b> of the CDS"}}], 2),
    })
    posts, method = ds.list_posts(f, END)
    assert method == "REST API" and posts["id"].tolist() == ["1", "2"]
    assert posts["title"].tolist() == ["UPDATE ON ARMED FORCES OF NIGERIA OPERATIONS – 1", "Visit of the CDS"]
    assert posts["date"].tolist() == ["2021-01-07", "2021-01-21"]


SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://defencehq.mil.ng/wp-sitemap-posts-post-1.xml</loc></sitemap>
<sitemap><loc>https://defencehq.mil.ng/wp-sitemap-taxonomies-category-1.xml</loc></sitemap></sitemapindex>"""
SITEMAP_POSTS = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://defencehq.mil.ng/2022/03/10/press-briefing-on-operations/</loc><lastmod>2023-01-01T00:00:00</lastmod></url>
<url><loc>https://defencehq.mil.ng/old-post/</loc><lastmod>2020-05-01T00:00:00</lastmod></url></urlset>"""


def test_sitemap_used_when_api_fails():
    f = FakeFetcher({ds.ORIGIN + ds.SITEMAP_PATH: Response("u", 200, SITEMAP_INDEX),
                     "https://defencehq.mil.ng/wp-sitemap-posts-post-1.xml": Response("u", 200, SITEMAP_POSTS)})
    posts, method = ds.list_posts(f, END)
    assert method == "sitemap" and len(posts) == 1
    assert (posts.loc[0, "date"], posts.loc[0, "title"]) == ("2022-03-10", "press briefing on operations")


def test_archive_entries_read_articles():
    page = """<article><h2><a href="https://x/p1">Troops neutralise terrorists</a></h2>
              <time datetime="2024-02-16T09:00:00">16 Feb</time></article><article><p>no link</p></article>"""
    assert ds.archive_entries(page) == [{"id": "", "date": "2024-02-16", "url": "https://x/p1",
                                         "title": "Troops neutralise terrorists"}]


def test_candidates_by_title():
    posts = pd.DataFrame({"title": ["UPDATE ON ARMED FORCES OF NIGERIA OPERATIONS", "Press Briefing by DDMO",
                                    "Troops rescue hostages", "CDS visits Kaduna", "Defence Media Operations update"]})
    assert ds.candidates(posts)["title"].tolist() == ["UPDATE ON ARMED FORCES OF NIGERIA OPERATIONS",
                                                       "Press Briefing by DDMO", "Troops rescue hostages",
                                                       "Defence Media Operations update"]


def test_match_by_date_and_period():
    briefings = pd.DataFrame({"briefing_id": ["B2021-012", "B2021-013", "B2021-020"],
                              "first_date": ["2021-10-14", "2021-10-28", "2021-11-20"]})
    periods = pd.DataFrame({"confirmed_group_id": ["B2021-013"], "period_start": ["2021-10-14"],
                            "period_end": ["2021-10-28"]})
    cands = pd.DataFrame({"url": ["p1", "p2"], "date": ["2021-10-27", "2021-11-10"]})
    texts = {"p1": "Between 14 to 28 October 2021, troops neutralised terrorists."}
    m = ds.match(cands, texts, briefings, periods)
    assert m.to_dict("records") == [{"briefing_id": "B2021-013", "post_url": "p1", "post_date": "2021-10-27",
                                     "match_basis": "date and period", "stated_period": "2021-10-14 to 2021-10-28"}]
    cov = ds.coverage_by_year(m, briefings)
    assert cov.loc["2021"].tolist() == [3, 1]


def test_match_prefers_nearest_date_without_period():
    briefings = pd.DataFrame({"briefing_id": ["B1"], "first_date": ["2024-02-16"]})
    cands = pd.DataFrame({"url": ["far", "near"], "date": ["2024-02-13", "2024-02-16"]})
    m = ds.match(cands, {}, briefings)
    assert (m.loc[0, "post_url"], m.loc[0, "match_basis"], m.loc[0, "stated_period"]) == ("near", "date", "")


def test_delay_is_never_below_two_seconds():
    f = ds.make_fetcher({"user_agent": "ua", "min_delay_seconds": 1, "obey_robots_txt": True})
    assert f.delay == 2
    assert ds.make_fetcher({"user_agent": "ua", "min_delay_seconds": 5, "obey_robots_txt": True}).delay == 5
