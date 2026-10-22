"""Archive-depth check: whether each outlet's REST API serves posts for each year at all.

Usage: python -m scoreboard.archive_depth [--reclassify]

For every configured outlet and year 2021-2026, page 1 of /wp-json/wp/v2/posts is requested with
only after/before set (no search term), per_page=100 and _fields=date,link, through the polite
fetcher. Each outlet's earliest and latest served post dates come from order=asc and order=desc
with per_page=1. Writes outputs/tables/full_archive_depth.csv.

classification, from the page-1 posts dated inside the year: "thin" when page 1 holds 1 to 99
(so the whole year holds fewer than 100 posts), or when page 1 is full (100 posts) but its
earliest post is dated in January of that year (the API lists newest first, so the whole year
then holds little more than 100 posts); "archive present" when page 1 is full and its earliest
post is dated after January; "archive missing" when it holds none; and "not checked (<reason>)"
when no JSON list was returned. posts_outside_window counts page-1 posts dated outside the
requested year (a site that ignores the date filter). --reclassify applies these classes to the
saved table without sending any request, keeping one row per outlet and year (the last).
"""

import argparse
import logging
import threading
from datetime import date

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.collect import api_bounds
from scoreboard.config import load_config
from scoreboard.discover import PER_PAGE, TABLES_DIR
from scoreboard.fetch import Fetcher

log = logging.getLogger(__name__)

YEARS = range(2021, 2027)
LAST_DAY = date(2026, 10, 18)
FIELDS = "date,link"
COLUMNS = ["outlet", "domain", "year", "status", "posts_on_page_1", "posts_outside_window",
           "earliest_on_page_1", "latest_on_page_1", "outlet_earliest_post", "outlet_latest_post",
           "classification"]
WATCH = [("Voice of Nigeria", 2022), ("Voice of Nigeria", 2024), ("News Agency of Nigeria", 2022), ("Leadership", 2021)]


def _list(fetcher: Fetcher, url: str, params: dict) -> tuple[str, list | None]:
    resp = fetcher.get(url, params=params)
    if resp is None:
        return fetcher.skip_reason or "request failed", None
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}", None
    try:
        body = resp.json()
    except ValueError:
        return "HTTP 200, not JSON", None
    return ("HTTP 200", body) if isinstance(body, list) else ("HTTP 200, not a list", None)


def outlet_rows(outlet: dict, fetcher: Fetcher) -> list[dict]:
    domain = outlet["domain"]
    url = f"https://{domain}/wp-json/wp/v2/posts"
    ends = {}
    for order in ("asc", "desc"):
        _, body = _list(fetcher, url, {"order": order, "per_page": 1, "_fields": FIELDS})
        ends[order] = body[0].get("date", "")[:10] if body else ""
    rows = []
    for year in YEARS:
        first, last = date(year, 1, 1), min(date(year, 12, 31), LAST_DAY)
        after, before = api_bounds(first, last)
        status, body = _list(fetcher, url, {"after": after, "before": before, "per_page": 100, "_fields": FIELDS})
        dates = sorted(p.get("date", "")[:10] for p in body or [] if isinstance(p, dict))
        inside = [d for d in dates if str(first) <= d <= str(last)]
        classification = classify(status, len(inside) if body is not None else None, year,
                                  inside[0] if inside else "")
        rows.append({
            "outlet": outlet["name"], "domain": domain, "year": year, "status": status,
            "posts_on_page_1": len(dates) if body is not None else "",
            "posts_outside_window": len(dates) - len(inside) if body is not None else "",
            "earliest_on_page_1": dates[0] if dates else "", "latest_on_page_1": dates[-1] if dates else "",
            "outlet_earliest_post": ends["asc"], "outlet_latest_post": ends["desc"],
            "classification": classification,
        })
        log_access(domain, f"{url}?after={after}&before={before}&per_page=100", status,
                   f"Archive-depth check {year}: {classification}; {len(dates)} posts on page 1, "
                   f"{len(dates) - len(inside)} outside the year")
    return rows


def classify(status: str, posts_in_year: int | None, year: int | None = None, earliest: str = "") -> str:
    """Class of an outlet-year from its page-1 posts dated inside the year (None: no JSON list)
    and the earliest of those posts' dates (YYYY-MM-DD)."""
    if posts_in_year is None:
        return f"not checked ({status})"
    if posts_in_year == 0:
        return "archive missing"
    if posts_in_year < PER_PAGE or (year is not None and earliest.startswith(f"{year}-01")):
        return "thin"
    return "archive present"


def reclassify(tables_dir=TABLES_DIR) -> pd.DataFrame:
    """Applies classify() to the saved table, keeping one row per outlet and year (the last);
    no request is sent."""
    path = tables_dir / "full_archive_depth.csv"
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    table = table.drop_duplicates(["outlet", "year"], keep="last").reset_index(drop=True)
    listed = table["posts_on_page_1"] != ""
    inside = pd.to_numeric(table["posts_on_page_1"], errors="coerce") - pd.to_numeric(
        table["posts_outside_window"], errors="coerce")
    table["classification"] = [
        classify(s, int(n) if ok else None, int(y), e)
        for s, n, ok, y, e in zip(table["status"], inside, listed, table["year"], table["earliest_on_page_1"])]
    table.to_csv(path, index=False)
    return table


def run(tables_dir=TABLES_DIR, fetcher_factory=Fetcher) -> pd.DataFrame:
    config = load_config()
    results, lock = [], threading.Lock()

    def work(outlet):
        rows = outlet_rows(outlet, fetcher_factory())
        with lock:
            results.extend(rows)

    threads = [threading.Thread(target=work, args=(o,), daemon=True) for o in config["outlets"]]
    for t in threads:
        t.start()
    for t in threads:
        while t.is_alive():
            t.join(0.5)
    order = {o["name"]: i for i, o in enumerate(config["outlets"])}
    table = pd.DataFrame(results, columns=COLUMNS)
    table = table.assign(_r=table["outlet"].map(order)).sort_values(["_r", "year"])[COLUMNS]
    table.to_csv(tables_dir / "full_archive_depth.csv", index=False)
    return table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reclassify", action="store_true", help="reclassify the saved table; no requests")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pd.set_option("display.width", 250)
    table = reclassify() if args.reclassify else run()
    table["year"] = table["year"].astype(int)
    print(table.drop(columns=["domain"]).to_string(index=False))
    print("FLAGGED OUTLET-YEARS")
    for name, year in WATCH:
        row = table[(table["outlet"] == name) & (table["year"] == year)]
        print(row.drop(columns=["domain"]).to_string(index=False, header=False))


if __name__ == "__main__":
    main()
