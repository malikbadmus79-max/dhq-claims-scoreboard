"""Full-collection discovery: candidate inventories per year and yield per outlet.

Usage: python -m scoreboard.collect --start 2021-01-01 --end 2026-10-18

Discovery only: no article text is fetched and the Wayback Machine is not queried (archive
URLs are looked up later by scoreboard.archive, for confirmed briefings only). Each outlet's
WordPress REST API is searched per calendar year with the pilot's search terms and candidate
filter (including the "Buba Marwa" exclusion). An outlet whose API probe fails is logged and
never searched. Requests go through the polite fetcher (robots.txt, configured delay and user
agent); outlets run in parallel, one fetcher each, so each domain keeps its own delay.

Writes outputs/tables/full_inventory_<year>.csv and full_yield_by_outlet_year.csv. Pilot tables
are not touched. Excerpts are held in memory for the filter only.
"""

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.config import load_config
from scoreboard.discover import (
    INVENTORY_COLUMNS,
    TABLES_DIR,
    _satisfies,
    assign_groups,
    match_field,
    period_phrase,
    probe_api,
    search_window,
)
from scoreboard.fetch import Fetcher

log = logging.getLogger(__name__)

DHQ_DOMAIN = "defencehq.mil.ng"
RETRY_PASSES = 2
RETRY_WAIT_SECONDS = 60
# complete is False when any search for the outlet-year still ended incomplete after the retry
# passes; its counts are then lower bounds, and blank (never 0) when no post was returned.
YIELD_COLUMNS = ["outlet", "year", "api_posts_returned", "candidates", "incomplete_queries", "complete"]


def year_windows(start: date, end: date) -> list[tuple[int, date, date]]:
    return [(y, max(start, date(y, 1, 1)), min(end, date(y, 12, 31))) for y in range(start.year, end.year + 1)]


def api_bounds(first: date, last: date) -> tuple[str, str]:
    """REST API `after` and `before` strings covering first..last inclusive. For a full calendar
    year these match the pilot's strings, so cached pilot responses are reused."""
    return f"{first - timedelta(days=1)}T23:59:59", f"{last + timedelta(days=1)}T00:00:00"


def _search_year(fetcher: Fetcher, domain: str, year: int, first: date, last: date, attempt: str) -> tuple[dict, dict]:
    after, before = api_bounds(first, last)
    hits, stats = search_window(fetcher, domain, after, before, label=f"Full discovery {year}")
    stops = pd.Series(stats["stops"]).value_counts().to_dict()
    log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?search=<term>&after={after}&before={before}",
               f"{len(hits)} unique posts returned",
               f"Full discovery {year} ({attempt}); {stats['queries']} queries; stops: {stops}; "
               f"{stats['incomplete']} incomplete; {stats['capped']} hit the page cap; "
               f"{stats['pages'] - stats['cached_pages']} pages requested, {stats['cached_pages']} read from cache")
    log.info("%s %d (%s): %d posts, %d incomplete queries", domain, year, attempt, len(hits), stats["incomplete"])
    return hits, stats


def collect_outlet(outlet: dict, windows, sleep=time.sleep, fetcher=None) -> dict:
    """API probe and per-year search for one outlet. An outlet whose probe does not return
    "yes" is logged and never searched. Years with incomplete searches are searched again up to
    RETRY_PASSES times; pages already read come from the cache."""
    fetcher = fetcher or Fetcher()
    domain = outlet["domain"]
    api = probe_api(fetcher, domain)
    out = {"outlet": outlet, "api": api, "years": {}, "capped": {}, "incomplete": {}}
    if api != "yes":
        log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?per_page=1", api,
                   "Full discovery: outlet skipped, no WordPress REST API; not searched")
        return out
    pending = list(windows)
    for attempt in range(RETRY_PASSES + 1):
        if attempt:
            sleep(RETRY_WAIT_SECONDS)
        label = "first pass" if attempt == 0 else f"retry {attempt}"
        for year, first, last in pending:
            hits, stats = _search_year(fetcher, domain, year, first, last, label)
            out["years"][year], out["capped"][year], out["incomplete"][year] = hits, stats["capped"], stats["incomplete"]
        pending = [w for w in windows if out["incomplete"][w[0]]]
        if not pending:
            break
    return out


def candidate_rows(outlet_name: str, hits: dict) -> list[dict]:
    rows = []
    for link, h in hits.items():
        field = match_field(h["title"], h["excerpt"])
        if field is None:
            continue
        rows.append({
            "outlet": outlet_name,
            "url": link,
            "title": h["title"],
            "publish_date": h["date"],
            "search_term_hits": "; ".join(h["terms"]),
            "period_phrase": period_phrase(h["title"]),
            "matched_field": field,
            "kept_by_title_alone": _satisfies(h["title"]),
        })
    return rows


def yield_row(name: str, year: int, posts: int, candidates: int, incomplete: int) -> dict:
    """One yield row. An incomplete outlet-year keeps its counts as lower bounds, except that a
    search that failed and returned nothing is blank rather than 0."""
    complete = incomplete == 0
    blank = not complete and posts == 0
    return {
        "outlet": name,
        "year": year,
        "api_posts_returned": "" if blank else posts,
        "candidates": "" if blank else candidates,
        "incomplete_queries": incomplete,
        "complete": complete,
    }


def build_yield(results: list[dict], inventories: dict, windows) -> pd.DataFrame:
    rows = []
    for res in results:
        if res["api"] != "yes":
            continue
        name = res["outlet"]["name"]
        for year, _, _ in windows:
            inv = inventories[year]
            rows.append(yield_row(name, year, len(res["years"].get(year, {})),
                                  int((inv["outlet"] == name).sum()), res["incomplete"].get(year, 0)))
    return pd.DataFrame(rows, columns=YIELD_COLUMNS)


def run(start: date, end: date, tables_dir=TABLES_DIR, fetcher_factory=Fetcher) -> dict:
    """`fetcher_factory` builds one fetcher per outlet (tests pass a recording fake)."""
    config = load_config()
    windows = year_windows(start, end)

    # defencehq.mil.ng: one robots.txt retry at the start; skipped while unreachable.
    dhq_ok, dhq_status = fetcher_factory(config).check_robots(f"https://{DHQ_DOMAIN}/")
    skip_dhq = dhq_status == "unreachable" or not dhq_ok
    log_access(DHQ_DOMAIN, f"https://{DHQ_DOMAIN}/robots.txt", f"robots.txt {dhq_status}",
               f"Full discovery {start} to {end}: retry at start of run; site {'skipped' if skip_dhq else 'included'}")
    outlets = [o for o in config["outlets"] if not (o["domain"] == DHQ_DOMAIN and skip_dhq)]

    with ThreadPoolExecutor(max_workers=len(outlets)) as pool:
        results = list(pool.map(lambda o: collect_outlet(o, windows, fetcher=fetcher_factory()), outlets))

    inventories = {}
    for year, _, _ in windows:
        rows = [r for res in results for r in candidate_rows(res["outlet"]["name"], res["years"].get(year, {}))]
        inv = pd.DataFrame(rows, columns=INVENTORY_COLUMNS[:-2])
        inv = inv.sort_values(["publish_date", "outlet", "url"]).reset_index(drop=True)
        inv["briefing_group_id"] = assign_groups(inv, prefix="F") if len(inv) else []
        inv["grouping_status"] = "provisional"
        inventories[year] = inv[INVENTORY_COLUMNS]
        inventories[year].to_csv(tables_dir / f"full_inventory_{year}.csv", index=False)

    yield_table = build_yield(results, inventories, windows)
    yield_table.to_csv(tables_dir / "full_yield_by_outlet_year.csv", index=False)
    return {
        "yield": yield_table,
        "capped": sum(sum(r["capped"].values()) for r in results),
        "dhq": dhq_status,
        "skipped": {r["outlet"]["domain"]: r["api"] for r in results if r["api"] != "yes"},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    out = run(args.start, args.end)
    print("YIELD")
    print(out["yield"].to_string(index=False))
    print(f"QUERIES AT PAGE CAP: {out['capped']}")
    print(f"DHQ ROBOTS: {out['dhq']}")
    print(f"OUTLETS SKIPPED (API probe): {out['skipped']}")


if __name__ == "__main__":
    main()
