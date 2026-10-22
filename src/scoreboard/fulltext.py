"""Body text and wire check for the full collection, one year at a time.

Usage: python -m scoreboard.fulltext --year 2021

Text uses the pilot pipeline unchanged: the article page through the polite fetcher
(scoreboard.wirecheck: body extraction, JS challenge pages recorded and never solved, a domain's
remaining pages skipped after MAX_CONSECUTIVE_FAILURES failures in a row), then, for items still
without text, the WordPress API content field looked up by slug (scoreboard.apifill, accepted only
when the returned link matches). Body text is written only to data_raw/text/<sha256>.txt, with the
source in a .src file beside it. Text already on disk is not fetched again, so a run resumes.

Each outlet-year has the time budget of discovery (outlet_year_budget_minutes); items not reached
are recorded with fetch_status "time budget exceeded" and are tried again by the next run. Item
rows are saved as each outlet-year finishes.

The wire check is the pilot's, unchanged (scoreboard.wirecheck.compare_groups): pairs within each
provisional briefing group of the inventory, word 5-gram Jaccard with digits removed, same_wire at
the frozen threshold, sensitivity thresholds from config. No briefing is grouped here and no
figure is extracted.

Writes outputs/tables/full_item_checks_<year>.csv (pilot item columns),
full_copy_similarity_<year>.csv (pilot pair columns) and full_similarity_distribution.csv (pairs
per 0.05 similarity bin and year). Outputs hold URLs, flags and scores, never body text.
"""

import argparse
import logging
import threading
import time
from collections import defaultdict
from urllib.parse import urlsplit

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.apifill import fill_from_api
from scoreboard.config import load_config
from scoreboard.discover import TABLES_DIR
from scoreboard.fetch import Fetcher
from scoreboard.wirecheck import (
    ITEM_COLUMNS,
    MAX_CONSECUTIVE_FAILURES,
    SAME_WIRE_COMMENT,
    SAME_WIRE_THRESHOLD,
    SENSITIVITY_THRESHOLDS,
    TEXT_DIR,
    compare_groups,
    extract_body,
    has_nan_credit,
    is_challenge_page,
    text_path,
)

log = logging.getLogger(__name__)

PAGE, API = "article page", "WordPress API"
BUDGET_STATUS = "time budget exceeded"
BIN = 0.05
DISTRIBUTION_FILE = "full_similarity_distribution.csv"
DISTRIBUTION_COLUMNS = ["year", "bin_low", "bin_high", "pairs"]


def source_path(url: str):
    return text_path(url).with_suffix(".src")


def stored_text(url: str) -> tuple[str, str]:
    """(text, source) on disk. Text without a .src file was stored by the pilot; its source is
    taken from the pilot item checks by the caller, else the article page."""
    path = text_path(url)
    if not path.exists():
        return "", ""
    src = source_path(url)
    return path.read_text(encoding="utf-8"), src.read_text(encoding="utf-8").strip() if src.exists() else ""


def store_text(url: str, text: str, source: str) -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    text_path(url).write_text(text, encoding="utf-8")
    source_path(url).write_text(source, encoding="utf-8")


def pilot_sources() -> dict[str, str]:
    sources = {}
    for path in TABLES_DIR.glob("pilot_item_checks_*.csv"):
        items = pd.read_csv(path, keep_default_na=False)
        sources.update(dict(zip(items["url"], items["text_source"])))
    return sources


def fetch_outlet_year(rows: pd.DataFrame, domain: str, fetcher: Fetcher, budget_seconds: float,
                      known_sources: dict, clock=time.monotonic, stop: threading.Event | None = None) -> list[dict]:
    """Text for one outlet-year's items: stored text first, then the article page, then the API.
    Returns one item row per URL (without body_words and nan_credit)."""
    started = clock()

    def spent():
        return clock() - started > budget_seconds or bool(stop and stop.is_set())

    fetcher.cancel = spent
    out, need_api, failures = {}, [], 0
    for row in rows.itertuples():
        url = row.url
        base = {"url": url, "outlet": row.outlet, "briefing_group_id": row.briefing_group_id, "api_status": ""}
        text, source = stored_text(url)
        if text:
            out[url] = {**base, "fetch_status": "ok (text cached)", "text_source": source or known_sources.get(url) or PAGE}
            continue
        if spent():
            out[url] = {**base, "fetch_status": BUDGET_STATUS, "text_source": ""}
            continue
        if failures >= MAX_CONSECUTIVE_FAILURES:
            out[url] = {**base, "fetch_status": "skipped after repeated failures", "text_source": ""}
            need_api.append(url)
            continue
        resp = fetcher.get(url)
        failures = failures + 1 if resp is None or resp.status_code >= 500 else 0
        if resp is None:
            status = BUDGET_STATUS if spent() else fetcher.skip_reason or "failed"
        elif resp.status_code != 200:
            status = f"HTTP {resp.status_code}"
        elif is_challenge_page(resp.text):
            fetcher.forget(resp.url)
            status = "JS challenge page"
        else:
            body = extract_body(resp.text)
            if body:
                store_text(url, body, PAGE)
                out[url] = {**base, "fetch_status": "ok", "text_source": PAGE}
                continue
            status = "no body extracted"
        out[url] = {**base, "fetch_status": status, "text_source": ""}
        if status != BUDGET_STATUS:
            need_api.append(url)
    for url in need_api:
        if spent():
            out[url]["api_status"] = BUDGET_STATUS
            continue
        status, text = fill_from_api(fetcher, domain, url)
        out[url]["api_status"] = BUDGET_STATUS if status == "cancelled" else status
        if text:
            store_text(url, text, API)
            out[url]["text_source"] = API
    fetcher.cancel = None
    return [out[u] for u in rows["url"]]


def item_checks_path(year: int, tables_dir=TABLES_DIR):
    return tables_dir / f"full_item_checks_{year}.csv"


def with_text_measures(items: pd.DataFrame) -> pd.DataFrame:
    bodies = {u: stored_text(u)[0] for u in items["url"]}
    items = items.copy()
    items["body_words"] = items["url"].map(lambda u: len(bodies[u].split()))
    items["nan_credit"] = items["url"].map(lambda u: has_nan_credit(bodies[u]))
    return items[ITEM_COLUMNS]


class ItemSaver:
    """Merges each finished outlet-year's item rows into full_item_checks_<year>.csv."""

    def __init__(self, year: int, tables_dir=TABLES_DIR):
        self.path = item_checks_path(year, tables_dir)
        self.lock = threading.Lock()
        self.closed = False

    def save(self, rows: list[dict]) -> None:
        new = with_text_measures(pd.DataFrame(rows))
        with self.lock:
            if self.closed:
                return
            if self.path.exists():
                old = pd.read_csv(self.path, keep_default_na=False)
                new = pd.concat([old[~old["url"].isin(new["url"])], new], ignore_index=True)
            new[ITEM_COLUMNS].to_csv(self.path, index=False)


def similarity_distribution(pairs: pd.DataFrame, year: int) -> pd.DataFrame:
    sims = pd.to_numeric(pairs["similarity"], errors="coerce").dropna()
    bins = int(round(1 / BIN))
    index = (sims / BIN).astype(int).clip(upper=bins - 1)  # 1.0 falls in the last bin
    counts = index.value_counts()
    return pd.DataFrame([{"year": year, "bin_low": round(i * BIN, 2), "bin_high": round((i + 1) * BIN, 2),
                          "pairs": int(counts.get(i, 0))} for i in range(bins)], columns=DISTRIBUTION_COLUMNS)


def wire_check(year: int, inventory: pd.DataFrame, tables_dir=TABLES_DIR) -> pd.DataFrame:
    bodies = pd.Series({u: stored_text(u)[0] for u in inventory["url"]})
    pairs, _ = compare_groups(inventory, bodies)
    with open(tables_dir / f"full_copy_similarity_{year}.csv", "w", newline="", encoding="utf-8") as f:
        f.write(SAME_WIRE_COMMENT + "\n")
        pairs.to_csv(f, index=False)
    dist = similarity_distribution(pairs, year)
    path = tables_dir / DISTRIBUTION_FILE
    if path.exists():
        old = pd.read_csv(path)
        dist = pd.concat([old[old["year"] != year], dist], ignore_index=True)
    dist.sort_values(["year", "bin_low"])[DISTRIBUTION_COLUMNS].to_csv(path, index=False)
    return pairs


def run(year: int, tables_dir=TABLES_DIR, fetcher_factory=Fetcher, clock=time.monotonic, outlets=None) -> dict:
    """`outlets` (names) limits fetching to those outlets; the others keep their saved item rows,
    and the wire check is recomputed over the whole year."""
    config = load_config()
    budget = float(config["outlet_year_budget_minutes"]) * 60
    domains = {o["name"]: o["domain"] for o in config["outlets"]}
    inventory = pd.read_csv(tables_dir / f"full_inventory_{year}.csv", keep_default_na=False)
    if outlets:
        unknown = set(outlets) - set(inventory["outlet"])
        if unknown:
            raise ValueError(f"no {year} inventory rows for {sorted(unknown)}")
    known = pilot_sources()
    saver, stop = ItemSaver(year, tables_dir), threading.Event()
    errors = []

    def work(outlet, rows):
        try:
            domain = domains.get(outlet) or urlsplit(rows["url"].iloc[0]).netloc
            items = fetch_outlet_year(rows, domain, fetcher_factory(), budget, known, clock=clock, stop=stop)
            if stop.is_set():
                return
            saver.save(items)
            statuses = pd.Series([i["fetch_status"] for i in items]).value_counts().to_dict()
            sources = pd.Series([i["text_source"] or "none" for i in items]).value_counts().to_dict()
            log_access(domain, rows["url"].iloc[0], f"{sources.get(PAGE, 0) + sources.get(API, 0)} of {len(items)} texts",
                       f"Full text {year}; text sources: {sources}; page fetch: {statuses}")
        except Exception as exc:  # re-raised in the main thread
            log.exception("%s failed", outlet)
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(o, g), daemon=True) for o, g in inventory.groupby("outlet")
               if not outlets or o in outlets]
    for t in threads:
        t.start()
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.5)
    except KeyboardInterrupt:
        with saver.lock:
            saver.closed = True
        stop.set()
        return {"interrupted": True}
    if errors:
        raise errors[0]

    items = pd.read_csv(item_checks_path(year, tables_dir), keep_default_na=False)
    items = inventory[["url"]].merge(items, on="url", how="left").fillna("")
    items = with_text_measures(items)
    items.to_csv(item_checks_path(year, tables_dir), index=False)
    pairs = wire_check(year, inventory, tables_dir)
    return {"interrupted": False, "items": items, "pairs": pairs}


def summary(year: int, items: pd.DataFrame, pairs: pd.DataFrame, tables_dir=TABLES_DIR) -> str:
    sims = pd.to_numeric(pairs["similarity"], errors="coerce")
    source = items["text_source"].replace({PAGE: "page", API: "API", "": "none"}).value_counts()
    lines = [f"YEAR {year}", f"items: {len(items)}",
             f"text by source: page {source.get('page', 0)}, API {source.get('API', 0)}, none {source.get('none', 0)}",
             f"budget not reached: {int((items['fetch_status'] == BUDGET_STATUS).sum())}",
             f"pairs compared: {int(sims.notna().sum())} (of {len(pairs)} pairs; the rest lack text on one side)"]
    for t in [SAME_WIRE_THRESHOLD] + SENSITIVITY_THRESHOLDS:
        lines.append(f"same_wire at {t}: {int((sims >= t).sum())}")
    lines.append(f"items crediting NAN: {int(items['nan_credit'].astype(str).eq('True').sum())}")
    dist = pd.read_csv(tables_dir / DISTRIBUTION_FILE)
    dist = dist[(dist["year"] == year) & (dist["pairs"] > 0)]
    lines.append("similarity histogram (bin: pairs)")
    lines += [f"  {r.bin_low:.2f}-{r.bin_high:.2f}: {r.pairs}" for r in dist.itertuples()]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--outlets", nargs="+", help="fetch only these outlets (names); others keep their saved rows")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    out = run(args.year, outlets=args.outlets)
    if out["interrupted"]:
        print("INTERRUPTED: finished outlet-years are saved; rerun to resume")
        raise SystemExit(130)
    print(summary(args.year, out["items"], out["pairs"]))


if __name__ == "__main__":
    main()
