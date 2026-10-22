import json

import pandas as pd
import pytest

import scoreboard.fulltext as fulltext
import scoreboard.wirecheck as wirecheck
from scoreboard.fetch import Response

BODY = "<html><body><article>" + "".join(f"<p>Troops of the army cleared camp number {i} in the north.</p>" for i in range(12)) + "</article></body></html>"
CHALLENGE = "<html><script>slowAES.decrypt()</script></html>"


@pytest.fixture(autouse=True)
def text_dir(tmp_path, monkeypatch):
    path = tmp_path / "text"
    monkeypatch.setattr(wirecheck, "TEXT_DIR", path)
    monkeypatch.setattr(fulltext, "TEXT_DIR", path)
    return path


class FakeFetcher:
    """Serves article pages and slug lookups from dicts; records every URL requested."""

    def __init__(self, pages=None, api=None, clock=None, step=0.0):
        self.pages, self.api, self.requested = pages or {}, api or {}, []
        self.skip_reason, self.cancel, self.clock, self.step = None, None, clock, step

    def get(self, url, params=None):
        if self.cancel and self.cancel():
            self.skip_reason = "cancelled"
            return None
        if self.clock:
            self.clock.now += self.step
        self.requested.append((url, params))
        if params and "slug" in params:
            return Response(url, 200, json.dumps(self.api.get(params["slug"], [])), {})
        if url in self.pages:
            return Response(url, 200, self.pages[url], {})
        self.skip_reason = "request failed"
        return None

    def forget(self, url):
        return True


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def _rows(urls, outlet="Daily Post"):
    return pd.DataFrame({"url": urls, "outlet": outlet, "briefing_group_id": [f"F2021-{i:03d}" for i in range(len(urls))]})


def test_page_then_api_fallback_and_sources(tmp_path):
    a, b = "https://dailypost.ng/2021/01/01/a/", "https://dailypost.ng/2021/01/01/b/"
    api_post = [{"link": b, "content": {"rendered": BODY}}]
    fetcher = FakeFetcher(pages={a: BODY, b: CHALLENGE}, api={"b": api_post})
    items = fulltext.fetch_outlet_year(_rows([a, b]), "dailypost.ng", fetcher, 900, {})
    assert [(i["fetch_status"], i["api_status"], i["text_source"]) for i in items] == [
        ("ok", "", "article page"), ("JS challenge page", "ok", "WordPress API")]
    assert fulltext.stored_text(b) == (wirecheck.extract_body(BODY), "WordPress API")


def test_text_on_disk_is_not_fetched_again():
    a = "https://dailypost.ng/2021/01/01/a/"
    fulltext.store_text(a, "stored body", "WordPress API")
    fetcher = FakeFetcher()
    items = fulltext.fetch_outlet_year(_rows([a]), "dailypost.ng", fetcher, 900, {})
    assert fetcher.requested == []
    assert (items[0]["fetch_status"], items[0]["text_source"]) == ("ok (text cached)", "WordPress API")


def test_pilot_text_without_source_file_takes_pilot_source(text_dir):
    a = "https://dailypost.ng/2024/01/01/a/"
    text_dir.mkdir()
    wirecheck.text_path(a).write_text("pilot body", encoding="utf-8")
    items = fulltext.fetch_outlet_year(_rows([a]), "dailypost.ng", FakeFetcher(), 900, {a: "WordPress API"})
    assert items[0]["text_source"] == "WordPress API"


def test_time_budget_stops_the_outlet_year():
    urls = [f"https://dailypost.ng/2021/01/01/{i}/" for i in range(5)]
    clock = Clock()
    fetcher = FakeFetcher(pages={u: BODY for u in urls}, clock=clock, step=400)
    items = fulltext.fetch_outlet_year(_rows(urls), "dailypost.ng", fetcher, 900, {}, clock=clock)
    statuses = [i["fetch_status"] for i in items]
    assert statuses[:3] == ["ok", "ok", "ok"] and statuses[3:] == ["time budget exceeded"] * 2
    assert len(fetcher.requested) == 3


def test_repeated_failures_skip_pages_but_still_try_the_api():
    urls = [f"https://dailypost.ng/2021/01/01/{i}/" for i in range(5)]
    fetcher = FakeFetcher()
    items = fulltext.fetch_outlet_year(_rows(urls), "dailypost.ng", fetcher, 900, {})
    assert [i["fetch_status"] for i in items][3:] == ["skipped after repeated failures"] * 2
    assert all(i["api_status"] == "no matching post" for i in items)
    page_requests = [u for u, p in fetcher.requested if not p]
    assert len(page_requests) == wirecheck.MAX_CONSECUTIVE_FAILURES


def test_item_saver_merges_rows_by_url(tmp_path):
    saver = fulltext.ItemSaver(2021, tables_dir=tmp_path)
    base = {"outlet": "X", "briefing_group_id": "F", "fetch_status": "failed", "api_status": "", "text_source": ""}
    saver.save([{**base, "url": "u1"}, {**base, "url": "u2"}])
    saver.save([{**base, "url": "u2", "fetch_status": "ok"}])
    table = pd.read_csv(tmp_path / "full_item_checks_2021.csv", keep_default_na=False).set_index("url")
    assert list(table.columns) == wirecheck.ITEM_COLUMNS[1:]
    assert table.loc["u2", "fetch_status"] == "ok" and len(table) == 2


def test_similarity_distribution_bins():
    pairs = pd.DataFrame({"similarity": [0.0, 0.049, 0.05, 0.31, 1.0, None]})
    dist = fulltext.similarity_distribution(pairs, 2021).set_index("bin_low")["pairs"]
    assert len(dist) == 20 and dist.sum() == 5
    assert (dist[0.0], dist[0.05], dist[0.3], dist[0.95]) == (2, 1, 1, 1)


def test_run_writes_item_checks_pairs_and_distribution_without_body_text(tmp_path):
    a, b = "https://dailypost.ng/2021/01/01/a/", "https://dailytrust.com/b/"
    inv = pd.DataFrame({"outlet": ["Daily Post", "Daily Trust"], "url": [a, b], "briefing_group_id": ["F2021-001"] * 2})
    inv.to_csv(tmp_path / "full_inventory_2021.csv", index=False)
    pages = {a: BODY, b: BODY}
    out = fulltext.run(2021, tables_dir=tmp_path, fetcher_factory=lambda: FakeFetcher(pages=pages))
    items = pd.read_csv(tmp_path / "full_item_checks_2021.csv", keep_default_na=False)
    assert items["text_source"].tolist() == ["article page", "article page"]
    pairs = pd.read_csv(tmp_path / "full_copy_similarity_2021.csv", comment="#")
    assert pairs["similarity"].tolist() == [1.0] and pairs["same_wire"].tolist() == [True]
    dist = pd.read_csv(tmp_path / "full_similarity_distribution.csv")
    assert dist["pairs"].sum() == 1 and (dist["year"] == 2021).all()
    written = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("full_*.csv"))
    assert "cleared camp" not in written
    assert "same_wire at 0.3: 1" in fulltext.summary(2021, out["items"], out["pairs"], tables_dir=tmp_path)


def test_outlets_option_fetches_only_named_outlets_and_keeps_other_rows(tmp_path):
    a, b = "https://dailypost.ng/2026/01/01/a/", "https://dailytrust.com/b/"
    inv = pd.DataFrame({"outlet": ["Daily Post", "Daily Trust"], "url": [a, b], "briefing_group_id": ["F2026-001"] * 2})
    inv.to_csv(tmp_path / "full_inventory_2026.csv", index=False)
    saved = {"url": b, "outlet": "Daily Trust", "briefing_group_id": "F2026-001", "fetch_status": "HTTP 500",
             "api_status": "HTTP 500", "text_source": "", "body_words": 0, "nan_credit": False}
    pd.DataFrame([saved]).to_csv(tmp_path / "full_item_checks_2026.csv", index=False)
    fetchers = []

    def factory():
        fetchers.append(FakeFetcher(pages={a: BODY, b: BODY}))
        return fetchers[-1]

    out = fulltext.run(2026, tables_dir=tmp_path, fetcher_factory=factory, outlets=["Daily Post"])
    requested = [u for f in fetchers for u, _ in f.requested]
    assert requested == [a]
    items = out["items"].set_index("url")
    assert items.loc[a, "text_source"] == "article page" and items.loc[b, "fetch_status"] == "HTTP 500"
    with pytest.raises(ValueError):
        fulltext.run(2026, tables_dir=tmp_path, fetcher_factory=factory, outlets=["No Such Outlet"])
