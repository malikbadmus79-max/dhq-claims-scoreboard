"""Full-collection discovery: candidate inventories per year and yield per outlet.

Usage: python -m scoreboard.collect --start 2021-01-01 --end 2026-10-18

Discovery only: no article text is fetched and the Wayback Machine is not queried (archive
URLs are looked up later by scoreboard.archive, for confirmed briefings only). Each outlet's
WordPress REST API is searched per calendar year with the pilot's search terms and candidate
filter (including the "Buba Marwa" exclusion). An outlet whose API probe fails is logged and
never searched. Requests go through the polite fetcher (robots.txt, configured delay and user
agent); outlets run in parallel, one fetcher each, so each domain keeps its own delay.

Each outlet-year has a time budget (outlet_year_budget_minutes in config/collection.yaml) that
covers its retries; an outlet-year past it is stopped, logged ("time budget exceeded") and
marked incomplete, its counts kept as lower bounds.

Each outlet-year is saved as soon as it finishes: its rows replace that outlet's rows in
outputs/tables/full_inventory_<year>.csv (briefing groups are then reassigned for the year), and
its row replaces the row with the same outlet and year in full_yield_by_outlet_year.csv, so both
tables merge across runs. On Ctrl+C, outlet-years already finished stay saved, unfinished ones
are not written, and the run exits with status 130. Pilot tables are not touched. Excerpts are
held in memory for the filter only.
"""

import argparse
import json
import logging
import sys
import threading
import time
from collections import Counter
from datetime import date, timedelta

import pandas as pd

from scoreboard import access_log
from scoreboard.access_log import log_access
from scoreboard.config import PROJECT_ROOT, load_config
from scoreboard.discover import (
    BUDGET_STOP,
    COMPLETE_STOPS,
    INVENTORY_COLUMNS,
    SEARCH_TERMS,
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
YIELD_FILE = "full_yield_by_outlet_year.csv"
# Per outlet-year: links returned and whether each term's search was complete. Lets a run with
# --terms --merge add one term at a time; links only, kept in data_raw/ and never committed.
STATE_DIR = PROJECT_ROOT / "data_raw" / "discovery_state"
# complete is False when any search for the outlet-year still ended incomplete after the retry
# passes, or the outlet-year ran past its time budget; its counts are then lower bounds, and
# blank (never 0) when no post was returned.
YIELD_COLUMNS = ["outlet", "year", "api_posts_returned", "candidates", "incomplete_queries", "complete"]
# full_inventory_<year>.csv: the pilot inventory columns plus added_by, "discovery" for rows from
# REST API discovery and the name of a later check (e.g. "spokesperson_check") for rows it added.
# Yield candidates count discovery rows only.
DISCOVERY = "discovery"
FULL_INVENTORY_COLUMNS = INVENTORY_COLUMNS + ["added_by"]
ROW_COLUMNS = INVENTORY_COLUMNS[:-2] + ["added_by"]


def year_windows(start: date, end: date) -> list[tuple[int, date, date]]:
    return [(y, max(start, date(y, 1, 1)), min(end, date(y, 12, 31))) for y in range(start.year, end.year + 1)]


def api_bounds(first: date, last: date) -> tuple[str, str]:
    """REST API `after` and `before` strings covering first..last inclusive. For a full calendar
    year these match the pilot's strings, so cached pilot responses are reused."""
    return f"{first - timedelta(days=1)}T23:59:59", f"{last + timedelta(days=1)}T00:00:00"


def _search_year(fetcher: Fetcher, domain: str, year: int, first: date, last: date, attempt: str,
                 should_stop=None, terms=SEARCH_TERMS) -> tuple[dict, dict]:
    after, before = api_bounds(first, last)
    hits, stats = search_window(fetcher, domain, after, before, label=f"Full discovery {year}",
                                should_stop=should_stop, terms=terms)
    stops = pd.Series(stats["stops"]).value_counts().to_dict()
    scope = "" if list(terms) == SEARCH_TERMS else f"terms {list(terms)}; "
    log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?search=<term>&after={after}&before={before}",
               f"{len(hits)} unique posts returned",
               f"Full discovery {year} ({attempt}); {scope}{stats['queries']} queries; stops: {stops}; "
               f"{stats['incomplete']} incomplete; {stats['capped']} hit the page cap; "
               f"{stats['pages'] - stats['cached_pages']} pages requested, {stats['cached_pages']} read from cache")
    log.info("%s %d (%s): %d posts, %d incomplete queries", domain, year, attempt, len(hits), stats["incomplete"])
    return hits, stats


def _merge_hits(into: dict, new: dict) -> None:
    """Union of posts across passes, so a retry cut short by the budget never lowers a count."""
    for link, h in new.items():
        entry = into.setdefault(link, {**h, "terms": list(h.get("terms", []))})
        entry["terms"] += [t for t in h.get("terms", []) if t not in entry["terms"]]


def incomplete_reason(stops: list[str]) -> str:
    """Why an outlet-year is incomplete: the time budget, or the stops of its incomplete queries."""
    if BUDGET_STOP in stops:
        return BUDGET_STOP
    return "; ".join(f"{s} x{n}" for s, n in Counter(s for s in stops if s not in COMPLETE_STOPS).items())


def collect_outlet(outlet: dict, windows, budget_seconds: float = float("inf"), sleep=time.sleep, fetcher=None,
                   clock=time.monotonic, on_done=None, stop: threading.Event | None = None,
                   terms=SEARCH_TERMS) -> dict:
    """API probe and per-year search for one outlet. An outlet whose probe does not return
    "yes" is logged and never searched. Years with incomplete searches are searched again up to
    RETRY_PASSES times; pages already read come from the cache, and posts are pooled across
    passes. An outlet-year's clock starts at its first search; once budget_seconds have passed,
    retries and retry waits included, it is stopped at the next page (or before its next pass)
    and logged. on_done(outlet, year, hits, incomplete, term_complete) is called as each
    outlet-year finishes, term_complete mapping each term to whether its last search was complete;
    its hits are then dropped from memory and out["years"][year] keeps the post count. When
    `stop` is set, the outlet returns at the next page without finishing the year in progress."""
    fetcher = fetcher or Fetcher()
    domain = outlet["domain"]
    api = probe_api(fetcher, domain)
    out = {"outlet": outlet, "api": api, "years": {}, "capped": {}, "incomplete": {}, "reasons": {}}
    if api != "yes":
        log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?per_page=1", api,
                   "Full discovery: outlet skipped, no WordPress REST API; not searched")
        return out
    interrupted = stop.is_set if stop else (lambda: False)
    started, hits, stops = {}, {}, {}

    def finish(year, over_budget):
        incomplete = out["incomplete"].get(year, 0)
        if over_budget:
            incomplete = out["incomplete"][year] = max(incomplete, 1)
            log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?search=<term>", BUDGET_STOP,
                       f"Full discovery {year}: outlet-year stopped after {clock() - started[year]:.0f} s "
                       f"(budget {budget_seconds:.0f} s, retries included); {incomplete} incomplete queries; "
                       f"{len(hits.get(year, {}))} posts kept as a lower bound")
            out["reasons"][year] = BUDGET_STOP
        elif incomplete:
            out["reasons"][year] = incomplete_reason(stops[year])
        year_hits = hits.pop(year, {})
        last_stops = stops.get(year) or [BUDGET_STOP] * len(terms)
        term_complete = {t: s in COMPLETE_STOPS for t, s in zip(terms, last_stops)}
        if on_done:
            on_done(outlet, year, year_hits, incomplete, term_complete)
        out["years"][year] = len(year_hits)

    pending = list(windows)
    for attempt in range(RETRY_PASSES + 1):
        if attempt:
            sleep(RETRY_WAIT_SECONDS)
        label = "first pass" if attempt == 0 else f"retry {attempt}"
        retry = []
        for window in pending:
            if interrupted():
                return out
            year, first, last = window
            started.setdefault(year, clock())

            def over_budget(year=year):
                return clock() - started[year] > budget_seconds

            if over_budget():
                finish(year, True)
                continue

            def should_stop(over_budget=over_budget):
                return interrupted() or over_budget()

            if hasattr(fetcher, "cancel"):
                fetcher.cancel = should_stop
            new, stats = _search_year(fetcher, domain, year, first, last, label, should_stop, terms=terms)
            if interrupted():
                return out
            _merge_hits(hits.setdefault(year, {}), new)
            out["capped"][year], out["incomplete"][year], stops[year] = stats["capped"], stats["incomplete"], stats["stops"]
            if BUDGET_STOP in stats["stops"]:
                finish(year, True)
            elif stats["incomplete"] and attempt < RETRY_PASSES:
                retry.append(window)
            else:
                finish(year, False)
        pending = retry
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


def _read_table(path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_inventory(path) -> pd.DataFrame | None:
    """A full inventory's row columns (group columns dropped); rows written before added_by
    existed are discovery rows."""
    old = _read_table(path)
    if old is None:
        return None
    if "added_by" not in old.columns:
        old["added_by"] = DISCOVERY
    return old[ROW_COLUMNS]


def write_inventory(path, inv: pd.DataFrame) -> pd.DataFrame:
    """Sort, reassign provisional briefing groups across the year, and write."""
    inv = inv[ROW_COLUMNS].sort_values(["publish_date", "outlet", "url"]).reset_index(drop=True)
    inv["briefing_group_id"] = assign_groups(inv, prefix="F") if len(inv) else []
    inv["grouping_status"] = "provisional"
    inv = inv[FULL_INVENTORY_COLUMNS]
    inv.to_csv(path, index=False)
    return inv


def _merge_term_hits(a: str, b: str) -> str:
    terms = [t for t in a.split("; ") if t]
    return "; ".join(terms + [t for t in b.split("; ") if t and t not in terms])


class Saver:
    """Writes each finished outlet-year to the inventory and yield tables, merging with what
    earlier runs wrote. One writer at a time; after close() nothing more is written.

    By default an outlet-year's rows replace that outlet's earlier rows. With merge=True they
    are added to them (a run over some terms only): rows are unioned by URL with their
    search_term_hits combined, api_posts_returned counts the union of links in the outlet-year's
    state file, and incomplete_queries counts the terms whose last search was incomplete.

    A complete row is never replaced by an incomplete one: when the saved row for the outlet-year
    is complete and the new result is not, nothing is written (inventory, yield or state) and an
    access-log row records the rerun instead."""

    def __init__(self, tables_dir, outlet_order: list[str], merge: bool = False, state_dir=STATE_DIR):
        self.tables_dir = tables_dir
        self.order = {name: i for i, name in enumerate(outlet_order)}
        self.merge = merge
        self.state_dir = state_dir
        self.lock = threading.Lock()
        self.closed = False
        self.saved: list[tuple[str, int]] = []
        self.kept: list[tuple[str, int]] = []

    def close(self) -> None:
        with self.lock:
            self.closed = True

    def save(self, outlet: dict, year: int, hits: dict, incomplete: int, term_complete: dict | None = None) -> None:
        name = outlet["name"]
        domain = outlet.get("domain", name)
        rows = candidate_rows(name, hits)
        with self.lock:
            if self.closed:
                return
            posts, state = len(hits), None
            if term_complete is not None:
                state = self._next_state(domain, year, hits, term_complete)
                posts = len(state["links"])
                incomplete = sum(not ok for ok in state["terms"].values())
            saved = self._saved_row(name, year)
            if incomplete and saved is not None and saved["complete"] == "True":
                log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?search=<term>", "incomplete rerun not saved",
                           f"Full discovery {year}: rerun ended with {incomplete} incomplete queries and {posts} posts; "
                           f"the complete row ({saved['api_posts_returned']} posts, {saved['candidates']} candidates) "
                           "is kept")
                self.kept.append((name, year))
                return
            if state is not None:
                self._write_state(domain, year, state)
            candidates = self._write_inventory(name, year, rows)
            self._write_yield(yield_row(name, year, posts, candidates, incomplete))
            self.saved.append((name, year))

    def _saved_row(self, name: str, year: int) -> dict | None:
        old = _read_table(self.tables_dir / YIELD_FILE)
        if old is None:
            return None
        match = old[(old["outlet"] == name) & (old["year"] == str(year))]
        return match.iloc[0].to_dict() if len(match) else None

    def _state_path(self, domain: str, year: int):
        return self.state_dir / str(year) / f"{domain}.json"

    def _next_state(self, domain: str, year: int, hits: dict, term_complete: dict) -> dict:
        path = self._state_path(domain, year)
        state = {"links": [], "terms": {}}
        if self.merge and path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
        links = set(state["links"]) | set(hits)
        return {"links": sorted(links), "terms": {**state["terms"], **term_complete}}

    def _write_state(self, domain: str, year: int, state: dict) -> None:
        path = self._state_path(domain, year)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

    def _write_inventory(self, name: str, year: int, rows: list[dict]) -> int:
        """Writes the year's inventory and returns the outlet's discovery candidate count. Only
        the outlet's "discovery" rows are replaced; rows added by a check are kept unless
        discovery now finds the same link."""
        path = self.tables_dir / f"full_inventory_{year}.csv"
        inv = pd.DataFrame(rows, columns=ROW_COLUMNS[:-1]).astype(str).assign(added_by=DISCOVERY)
        old = read_inventory(path)
        if old is not None:
            mine = (old["outlet"] == name) & (old["added_by"] == DISCOVERY)
            if self.merge:
                earlier = old.loc[mine].set_index("url")
                for i, row in inv.iterrows():
                    if row["url"] in earlier.index:
                        inv.loc[i, "search_term_hits"] = _merge_term_hits(
                            earlier.loc[row["url"], "search_term_hits"], row["search_term_hits"])
                kept = old.loc[~old["url"].isin(inv["url"])]
            else:
                kept = old.loc[~mine & ~old["url"].isin(inv["url"])]
            inv = pd.concat([kept, inv], ignore_index=True)
        write_inventory(path, inv)
        return int(((inv["outlet"] == name) & (inv["added_by"] == DISCOVERY)).sum())

    def _write_yield(self, row: dict) -> None:
        path = self.tables_dir / YIELD_FILE
        table = pd.DataFrame([row], columns=YIELD_COLUMNS).astype(str)
        old = _read_table(path)
        if old is not None:
            same = (old["outlet"] == row["outlet"]) & (old["year"] == str(row["year"]))
            table = pd.concat([old.loc[~same, YIELD_COLUMNS], table], ignore_index=True)
        rank = table["outlet"].map(lambda o: self.order.get(o, len(self.order)))
        table = table.assign(_y=table["year"].astype(int), _r=rank).sort_values(["_y", "_r", "outlet"])
        table[YIELD_COLUMNS].to_csv(path, index=False)


def _join(threads: list[threading.Thread]) -> None:
    # Short joins, so Ctrl+C reaches the main thread on Windows.
    for t in threads:
        while t.is_alive():
            t.join(0.5)


def run(start: date, end: date, tables_dir=TABLES_DIR, fetcher_factory=Fetcher, clock=time.monotonic,
        terms=None, merge: bool = False, state_dir=STATE_DIR, outlets=None) -> dict:
    """`fetcher_factory` builds one fetcher per outlet (tests pass a recording fake). `terms`
    defaults to SEARCH_TERMS; with `merge`, results are added to the saved outlet-years
    (see Saver) rather than replacing them. `outlets` (names or domains) limits the run to those
    outlets, so a rerun sends no request to the others."""
    terms = list(terms or SEARCH_TERMS)
    config = load_config()
    windows = year_windows(start, end)
    budget = float(config["outlet_year_budget_minutes"]) * 60
    selected = [o for o in config["outlets"] if not outlets or o["name"] in outlets or o["domain"] in outlets]
    if outlets and len(selected) != len(set(outlets)):
        raise ValueError(f"unknown outlet in {outlets}")

    # defencehq.mil.ng: one robots.txt retry at the start, when it is among the outlets run;
    # skipped while unreachable.
    dhq_status = "not requested"
    if any(o["domain"] == DHQ_DOMAIN for o in selected):
        dhq_ok, dhq_status = fetcher_factory(config).check_robots(f"https://{DHQ_DOMAIN}/")
        skip_dhq = dhq_status == "unreachable" or not dhq_ok
        log_access(DHQ_DOMAIN, f"https://{DHQ_DOMAIN}/robots.txt", f"robots.txt {dhq_status}",
                   f"Full discovery {start} to {end}: retry at start of run; site "
                   f"{'skipped' if skip_dhq else 'included'}")
        selected = [o for o in selected if not (o["domain"] == DHQ_DOMAIN and skip_dhq)]
    outlets = selected

    saver = Saver(tables_dir, [o["name"] for o in config["outlets"]], merge=merge, state_dir=state_dir)
    stop = threading.Event()
    results, errors = [None] * len(outlets), []

    def work(i, outlet):
        try:
            results[i] = collect_outlet(outlet, windows, budget, sleep=stop.wait, fetcher=fetcher_factory(),
                                        clock=clock, on_done=saver.save, stop=stop, terms=terms)
        except Exception as exc:  # re-raised in the main thread
            log.exception("%s failed", outlet["domain"])
            errors.append(exc)

    # Daemon threads: after Ctrl+C the process exits without waiting for requests in flight.
    threads = [threading.Thread(target=work, args=(i, o), daemon=True) for i, o in enumerate(outlets)]
    for t in threads:
        t.start()
    interrupted = False
    try:
        _join(threads)
    except KeyboardInterrupt:
        saver.close()
        stop.set()
        interrupted = True
        log_access("all outlets", "", "interrupted",
                   f"Full discovery {start} to {end}: stopped by Ctrl+C; {len(saver.saved)} outlet-years saved, "
                   "unfinished outlet-years not written")
    if errors and not interrupted:
        raise errors[0]

    done = [r for r in results if r is not None]
    return {
        "yield": _read_table(tables_dir / YIELD_FILE),
        "saved": saver.saved,
        "kept": saver.kept,
        "interrupted": interrupted,
        "capped": sum(sum(r["capped"].values()) for r in done),
        "reasons": {(r["outlet"]["name"], y): why for r in done for y, why in r["reasons"].items()},
        "dhq": dhq_status,
        "skipped": {r["outlet"]["domain"]: r["api"] for r in done if r["api"] != "yes"},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--terms", nargs="+", help="search only these terms (default: all full-collection terms)")
    parser.add_argument("--merge", action="store_true",
                        help="add results to the saved outlet-years instead of replacing them")
    parser.add_argument("--outlets", nargs="+", help="run only these outlets (names or domains)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    out = run(args.start, args.end, terms=args.terms, merge=args.merge, outlets=args.outlets)
    years = {str(y) for y, _, _ in year_windows(args.start, args.end)}
    table = out["yield"]
    if out["interrupted"]:
        print(f"INTERRUPTED: {len(out['saved'])} outlet-years saved: {out['saved']}")
    print("YIELD (this run's years)")
    print("none" if table is None else table[table["year"].isin(years)].to_string(index=False))
    print("INCOMPLETE OUTLET-YEARS")
    for (name, year), why in sorted(out["reasons"].items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f"  {name} {year}: {why}")
    print(f"COMPLETE ROWS KEPT (incomplete rerun not saved): {out['kept']}")
    print(f"QUERIES AT PAGE CAP: {out['capped']}")
    print(f"DHQ ROBOTS: {out['dhq']}")
    print(f"OUTLETS SKIPPED (API probe): {out['skipped']}")
    if out["interrupted"]:
        # Daemon workers may still be running: hold the access-log lock so none is cut off
        # mid-row when the process exits.
        access_log._LOCK.acquire()
        sys.exit(130)


if __name__ == "__main__":
    main()
