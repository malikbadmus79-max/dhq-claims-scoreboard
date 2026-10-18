import json

import pandas as pd

from scoreboard.discover import (
    assign_groups,
    build_inventory,
    headline_figures,
    is_candidate,
    match_field,
    period_phrase,
    write_outputs,
)
from scoreboard.fetch import Response


def test_candidate_needs_dhq_and_outcome():
    assert is_candidate("DHQ: Troops neutralise 120 terrorists in one week")
    assert is_candidate("Buba: troops apprehend 30 suspects")
    assert is_candidate("Defence Media Operations: troops eliminate 12 bandits")
    assert not is_candidate("DHQ briefs journalists on welfare")
    assert not is_candidate("Troops kill 50 terrorists")


def test_title_lacks_dhq_but_excerpt_has_it():
    title = "Troops neutralise 120 terrorists in one week"
    excerpt = "The Defence Headquarters said on Thursday that troops recorded gains."
    assert not is_candidate(title)
    assert is_candidate(title, excerpt)
    assert match_field(title, excerpt) == "both"


def test_matched_field_values():
    assert match_field("DHQ: troops rescue 40 hostages", "Unrelated summary.") == "title"
    assert match_field("Weekly update", "Defence Headquarters said troops arrested 20.") == "excerpt"
    assert match_field("DHQ: troops rescue 40", "Buba said troops arrested 20.") == "both"
    assert match_field("Weekly update", "Nothing relevant.") is None


def test_period_phrase():
    assert period_phrase("DHQ: Troops killed 974 terrorists in February") == "in February"
    assert period_phrase("Troops neutralise 200 in two weeks") == "two weeks"
    assert period_phrase("Troops arrest 30") == ""


def test_headline_figures_skip_years_and_small_numbers():
    assert headline_figures("1,166 terrorists killed, 2,742 surrendered in 2024: 3 states") == {1166, 2742}


def test_groups_by_shared_figure_within_three_days():
    df = pd.DataFrame(
        {
            "publish_date": ["2024-03-01", "2024-03-03", "2024-03-20", "2024-03-02"],
            "title": [
                "DHQ: Troops kill 974 terrorists",
                "Troops neutralised 974 terrorists, DHQ says",
                "DHQ: Troops kill 974 terrorists",
                "DHQ: Troops arrest 55 suspects",
            ],
        }
    )
    groups = assign_groups(df)
    assert groups[0] == groups[1]
    assert groups[2] != groups[0]
    assert groups[3] not in (groups[0], groups[2])


class FakeFetcher:
    """Answers every outlet with one post whose title lacks DHQ but whose excerpt has it."""

    skip_reason = None
    EXCERPT = "<p>Defence Headquarters spokesman said the ZQXEXCERPTMARKER operations continued.</p>"

    def get(self, url, params=None):
        params = params or {}
        if params.get("per_page") == 1:
            return Response(url, 200, json.dumps([]))
        if params.get("search") != "DHQ":
            return Response(url, 200, json.dumps([]))
        domain = url.split("/")[2]
        post = {
            "date": "2024-05-02T10:00:00",
            "link": f"https://{domain}/troops-neutralise-150",
            "title": {"rendered": "Troops neutralise 150 terrorists in one week"},
            "excerpt": {"rendered": self.EXCERPT},
        }
        return Response(url, 200, json.dumps([post]), headers={"X-WP-TotalPages": "1"})


def test_excerpt_text_never_written(tmp_path):
    inventory, outlets = build_inventory(2024, fetcher=FakeFetcher())
    assert len(inventory) == len(outlets)
    assert set(inventory["matched_field"]) == {"both"}
    assert not inventory["kept_by_title_alone"].any()

    write_outputs(inventory, outlets, 2024, tables_dir=tmp_path)
    for csv in tmp_path.glob("*.csv"):
        text = csv.read_text(encoding="utf-8")
        assert "ZQXEXCERPTMARKER" not in text
        assert "spokesman said" not in text
        assert "excerpt" not in pd.read_csv(csv).columns


def test_buba_rule_in_candidate_filter():
    assert is_candidate("Troops neutralise 40 terrorists – Buba")
    assert is_candidate("Weekly update", "Maj.-Gen. Edward Buba said troops arrested 20 suspects.")
    assert not is_candidate("Agency arrests 14,480 suspects", "Chairman Buba Marwa said the arrests continued.")
    assert not is_candidate("Agency arrests 300", "BUBA-MARWA told journalists.")


# Pagination without the X-WP headers


class PagedFetcher:
    """Serves numbered pages of posts; `headers` are deliberately wrong to show they are ignored."""

    def __init__(self, pages, after_last="empty", headers=None):
        self.pages = pages
        self.after_last = after_last
        self.headers = headers or {}
        self.requested = []
        self.skip_reason = None

    def get(self, url, params=None):
        page = params["page"]
        self.requested.append(page)
        if page <= len(self.pages):
            return Response(url, 200, json.dumps(self.pages[page - 1]), self.headers)
        if self.after_last == "400":
            body = {"code": "rest_post_invalid_page_number", "message": "The page number requested is larger"}
            return Response(url, 400, json.dumps(body), {})
        return Response(url, 200, "[]", self.headers)


def _posts(n, start=0):
    return [{"link": f"https://x.ng/{i}", "date": "2024-03-01T00:00:00", "title": {"rendered": "t"}}
            for i in range(start, start + n)]


def test_paginate_ignores_low_header_total():
    from scoreboard.discover import paginate
    pages = [_posts(100), _posts(100, 100), _posts(30, 200)]
    fetcher = PagedFetcher(pages, headers={"X-WP-Total": "0", "X-WP-TotalPages": "1"})
    result = paginate(fetcher, "x.ng", {"search": "DHQ"})
    assert len(result["posts"]) == 230
    # Pages requested: three with posts and the empty fourth that ends paging.
    assert result["pages"] == 4 and not result["capped"]


def test_paginate_stops_on_empty_final_page():
    from scoreboard.discover import paginate
    fetcher = PagedFetcher([_posts(100), _posts(5, 100)])
    result = paginate(fetcher, "x.ng", {"search": "DHQ"})
    assert (len(result["posts"]), result["stop"]) == (105, "empty page")
    assert fetcher.requested == [1, 2, 3]


def test_paginate_stops_on_invalid_page_400():
    from scoreboard.discover import paginate
    fetcher = PagedFetcher([_posts(100), _posts(100, 100)], after_last="400")
    result = paginate(fetcher, "x.ng", {"search": "DHQ"})
    assert (len(result["posts"]), result["stop"], result["capped"]) == (200, "invalid page number", False)
    assert fetcher.requested == [1, 2, 3]


def test_paginate_other_400_is_reported(tmp_path):
    from scoreboard.discover import paginate

    class BadRequest(PagedFetcher):
        def get(self, url, params=None):
            self.requested.append(params["page"])
            return Response(url, 400, json.dumps({"code": "rest_invalid_param"}), {})

    result = paginate(BadRequest([]), "x.ng", {"search": "DHQ"})
    assert (result["posts"], result["stop"]) == ([], "HTTP 400")


def test_paginate_cap_is_logged(tmp_path, monkeypatch):
    import scoreboard.discover as discover
    logged = []
    monkeypatch.setattr(discover, "MAX_PAGES", 3)
    monkeypatch.setattr(discover, "log_access", lambda *a, **k: logged.append(a))
    fetcher = PagedFetcher([_posts(100, 100 * i) for i in range(5)])
    result = discover.paginate(fetcher, "x.ng", {"search": "DHQ"}, label="Full discovery 2024")
    assert (len(result["posts"]), result["capped"], fetcher.requested) == (300, True, [1, 2, 3])
    assert len(logged) == 1 and logged[0][0] == "x.ng" and "page cap" in logged[0][2]


def test_paginate_failed_request_is_incomplete():
    from scoreboard.discover import paginate

    class FailsOnPage2(PagedFetcher):
        def get(self, url, params=None):
            if params["page"] == 2:
                self.skip_reason = "request failed"
                return None
            return super().get(url, params)

    result = paginate(FailsOnPage2([_posts(100), _posts(100, 100)]), "x.ng", {"search": "DHQ"})
    assert (len(result["posts"]), result["stop"], result["complete"]) == (100, "request failed", False)
    complete = paginate(PagedFetcher([_posts(10)]), "x.ng", {"search": "DHQ"})
    assert complete["complete"] and complete["stop"] == "empty page"


class FixedFetcher(PagedFetcher):
    """Returns the same body for every page."""

    def __init__(self, body, status=200):
        super().__init__([])
        self.body = body
        self.status = status

    def get(self, url, params=None):
        self.requested.append(params["page"])
        return Response(url, self.status, self.body, {})


def test_paginate_non_json_is_invalid_response():
    from scoreboard.discover import paginate
    result = paginate(FixedFetcher("<!DOCTYPE html><html>blocked</html>"), "x.ng", {"search": "DHQ"})
    assert (result["stop"], result["complete"], result["posts"]) == ("invalid response", False, [])


def test_paginate_json_object_is_invalid_response():
    from scoreboard.discover import paginate
    result = paginate(FixedFetcher(json.dumps({"posts": []})), "x.ng", {"search": "DHQ"})
    assert (result["stop"], result["complete"]) == ("invalid response", False)


def test_paginate_repeated_page_stops_and_dedupes():
    from scoreboard.discover import paginate
    fetcher = FixedFetcher(json.dumps(_posts(3)))
    result = paginate(fetcher, "x.ng", {"search": "DHQ"})
    assert (len(result["posts"]), result["stop"], result["complete"]) == (3, "repeated page", False)
    assert fetcher.requested == [1, 2]


def test_paginate_dedupes_overlapping_pages():
    from scoreboard.discover import paginate
    pages = [_posts(100), _posts(100, 50)]  # second page repeats 50 links
    result = paginate(PagedFetcher(pages), "x.ng", {"search": "DHQ"})
    assert len(result["posts"]) == 150
    assert len({p["link"] for p in result["posts"]}) == 150


def test_paginate_drops_posts_outside_window_and_logs(isolated_access_log):
    from scoreboard.discover import paginate
    page = [
        {"link": "https://x.ng/in", "date": "2024-03-05T10:00:00"},
        {"link": "https://x.ng/early", "date": "2019-06-01T10:00:00"},
        {"link": "https://x.ng/late", "date": "2025-02-01T10:00:00"},
    ]
    params = {"search": "DHQ", "after": "2023-12-31T23:59:59", "before": "2025-01-01T00:00:00"}
    result = paginate(PagedFetcher([page]), "x.ng", params, label="Full discovery 2024")
    assert [p["link"] for p in result["posts"]] == ["https://x.ng/in"]
    assert result["dropped_outside_window"] == 2
    log = isolated_access_log.read_text(encoding="utf-8")
    assert "2 posts outside the date window dropped" in log
    assert "ignores the after/before date filter" in log


def test_paginate_no_date_log_when_nothing_dropped(isolated_access_log):
    from scoreboard.discover import paginate
    params = {"search": "DHQ", "after": "2023-12-31T23:59:59", "before": "2025-01-01T00:00:00"}
    paginate(PagedFetcher([_posts(5)]), "x.ng", params)
    assert not isolated_access_log.exists()


def test_paginate_cap_message_separates_pages_and_unique_posts(monkeypatch):
    import scoreboard.discover as discover
    logged = []
    monkeypatch.setattr(discover, "MAX_PAGES", 2)
    monkeypatch.setattr(discover, "log_access", lambda *a, **k: logged.append(a))
    pages = [_posts(100), _posts(100, 60), _posts(100, 200)]  # page 2 (links 60-159) adds 60 new links
    discover.paginate(PagedFetcher(pages), "x.ng", {"search": "DHQ"}, label="Full discovery 2024")
    result, notes = logged[0][2], logged[0][3]
    assert result == "page cap reached (2 pages requested)"
    assert "160 unique posts returned" in notes
