import json

import pandas as pd

from scoreboard.archive import archive_items, confirmed_briefings, lookup_archive
from scoreboard.fetch import Response


class OneShot:
    def __init__(self, resp, skip_reason=None):
        self.resp = resp
        self.skip_reason = skip_reason
        self.params = None

    def get(self, url, params=None):
        self.params = params
        return self.resp


def test_lookup_archive_closest_snapshot():
    body = {"archived_snapshots": {"closest": {"available": True, "status": "200", "timestamp": "20240721111223",
                                               "url": "http://web.archive.org/web/20240721111223/https://x.ng/a"}}}
    fetcher = OneShot(Response("u", 200, json.dumps(body), {}))
    assert lookup_archive(fetcher, "https://x.ng/a", "2024-07-20") == (
        "http://web.archive.org/web/20240721111223/https://x.ng/a", "20240721111223", "ok")
    assert fetcher.params == {"url": "https://x.ng/a", "timestamp": "20240720"}


def test_lookup_archive_blank_when_none_or_failed():
    empty = OneShot(Response("u", 200, json.dumps({"archived_snapshots": {}}), {}))
    assert lookup_archive(empty, "https://x.ng/a", "2024-07-20") == ("", "", "no snapshot")
    assert lookup_archive(OneShot(None, "request failed"), "https://x.ng/a", "2024-07-20") == ("", "", "request failed")
    assert lookup_archive(OneShot(Response("u", 503, "", {})), "https://x.ng/a", "2024-07-20") == ("", "", "HTTP 503")


def test_confirmed_briefings_only():
    review = pd.DataFrame({"is_operational_briefing": ["yes", "no", "unsure", "yes"],
                           "url": ["a", "b", "c", "d"]})
    assert list(confirmed_briefings(review)["url"]) == ["a", "d"]


def test_archive_items_records_snapshot_and_logs_failures(isolated_access_log):
    class Fake:
        skip_reason = None

        def get(self, url, params=None):
            if params["url"] == "https://x.ng/ok":
                body = {"archived_snapshots": {"closest": {"available": True, "timestamp": "20240301",
                                                           "url": "http://web.archive.org/web/20240301/https://x.ng/ok"}}}
                return Response(url, 200, json.dumps(body), {})
            return Response(url, 503, "", {})

    items = pd.DataFrame({"confirmed_group_id": ["B1", "B2"], "outlet": ["X", "Y"],
                          "url": ["https://x.ng/ok", "https://x.ng/down"], "publish_date": ["2024-03-01", "2024-03-02"]})
    out = archive_items(items, Fake(), 2024)
    assert list(out["lookup_status"]) == ["ok", "HTTP 503"]
    assert out.loc[1, "archive_url"] == "" and out.loc[0, "archive_timestamp"] == "20240301"
    log = isolated_access_log.read_text(encoding="utf-8")
    assert "https://x.ng/down" in log and "1 of 2 confirmed briefing copies have a snapshot" in log
