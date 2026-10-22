"""Spokesperson check: personal names next to the DHQ media-office phrases in the full inventory.

Usage:
  python -m scoreboard.spokesperson names
  python -m scoreboard.spokesperson dry-search --names "Name One" "Name Two"
  python -m scoreboard.spokesperson add

A coverage check, not part of discovery: discovery search terms and its filter are unchanged.

`names` reads titles from outputs/tables/full_inventory_<year>.csv and the excerpts of the same
links from the cached REST API search pages (offline: no request is sent). Names are taken only
from text next to the phrases in PHRASES; no outside list of names is used. Prints names with
counts by year (an item counts once per name) and writes them to
outputs/tables/full_spokesperson_names.csv.

`dry-search` searches each name per year on every outlet through the polite fetcher and counts
links not already in that year's inventory that pass the candidate filter, in two variants: the
discovery filter (DHQ_RE), and the same filter with SPOKESPERSON_NAMES as DHQ references
(NAMES_DHQ_RE). Counts go to outputs/tables/full_spokesperson_dry_search.csv; nothing is written
to the inventory.

`add` reads the cached dry-search pages only (offline: no request is sent) and adds to
outputs/tables/full_inventory_<year>.csv each distinct link not already present that passes the
filter with the names as DHQ references, with added_by "spokesperson_check" and
search_term_hits the spellings that returned it.
"""

import argparse
import logging
import re
import threading
from collections import Counter, defaultdict

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.collect import DHQ_DOMAIN, ROW_COLUMNS, api_bounds, read_inventory, write_inventory, year_windows
from scoreboard.config import load_config
from scoreboard.discover import (
    BUBA,
    DHQ_CORE,
    FIELDS,
    PER_PAGE,
    SEARCH_TERMS,
    TABLES_DIR,
    _satisfies,
    clean_html,
    match_field,
    paginate,
    period_phrase,
    probe_api,
)
from scoreboard.fetch import Fetcher

log = logging.getLogger(__name__)

YEARS = range(2021, 2027)
CHECK = "spokesperson_check"
# The 2021-2023 names other than Buba found next to the PHRASES in the inventory text, spelled
# as found (outputs/tables/full_spokesperson_names.csv). Used by this check only.
SPOKESPERSON_NAMES = ["John Enenche", "Bernard Onyeuko", "Benard Onyeuko", "Bernard Onyeuku", "Benard Onyeuku",
                      "Musa Danmadami"]
NAMES_RE = "|".join(r"\b" + r"\s+".join(n.split()) + r"\b" for n in SPOKESPERSON_NAMES)
NAMES_DHQ_RE = re.compile(rf"{DHQ_CORE}|{BUBA}|{NAMES_RE}", re.I)
PHRASES = [
    r"Director,?\s+Defen[cs]e\s+Media\s+Operations",
    r"Defen[cs]e\s+Media\s+Operations",
    r"Defen[cs]e\s+spokesperson",
    r"DHQ\s+spokesperson",
]
PHRASE_RE = re.compile("|".join(f"(?:{p})" for p in PHRASES), re.I)
# Rank and title words stripped from a name; they are not part of the personal name.
RANK_WORDS = {
    "maj", "major", "gen", "general", "brig", "brigadier", "col", "colonel", "lt", "lieutenant",
    "air", "vice", "marshal", "avm", "rear", "admiral", "commodore", "cdre", "capt", "captain",
    "mr", "mrs", "dr", "the", "director", "acting", "defence", "defense", "media", "operations",
    "headquarters", "dhq", "spokesperson", "spokesman", "army", "navy", "nigerian", "said",
    "coordinator", "according", "speaking",
}
CAP_WORD = r"[A-Z][a-zA-Z'’\-]+\.?"
NAME_SEQ = re.compile(rf"(?:{CAP_WORD}[\s\-]+){{1,6}}{CAP_WORD}")
WINDOW = 70


RANKS = {"maj", "major", "gen", "general", "brig", "brigadier", "col", "colonel", "lt", "lieutenant",
         "marshal", "avm", "admiral", "commodore", "cdre", "capt", "captain"}


def _is_rank(word: str) -> bool:
    parts = [p.strip(".,").lower() for p in word.split("-")]
    return all(p in RANKS for p in parts if p) and any(parts)


def _person(seq: str) -> str | None:
    """The personal name in a capitalised sequence: the words after its last rank word, up to
    three, stopping at a word that ends a sentence. None without a rank word or with fewer than
    two name words, so place names next to the phrase are not taken as names."""
    words = seq.split()
    ranks = [i for i, w in enumerate(words) if _is_rank(w)]
    if not ranks:
        return None
    kept = []
    for w in words[ranks[-1] + 1:]:
        if w.strip(".,").lower() in RANK_WORDS:
            break
        kept.append(w.strip(".,"))
        if w.endswith(".") or len(kept) == 3:
            break
    return " ".join(kept) if len(kept) >= 2 else None


def names_near_phrases(text: str) -> set[str]:
    """Names in the capitalised word run directly after the phrase (", Maj.-Gen. A B") or
    directly before it ("Maj.-Gen. A B, Director, ...")."""
    found = set()
    for m in PHRASE_RE.finditer(text):
        after = text[m.end():m.end() + WINDOW]
        a = re.match(rf"\s*,?\s*({NAME_SEQ.pattern})", after)
        if a and (name := _person(a.group(1))):
            found.add(name)
        before = text[max(0, m.start() - WINDOW):m.start()]
        b = re.search(rf"({NAME_SEQ.pattern})\s*,?\s*(?:the\s+)?$", before)
        if b and (name := _person(b.group(1))):
            found.add(name)
    return found


def cached_posts(fetcher: Fetcher, domain: str, year: int, terms) -> dict[str, dict]:
    """{link: post} from the cached search pages for one outlet-year (offline fetcher)."""
    w = year_windows(pd.Timestamp(f"{year}-01-01").date(), pd.Timestamp("2026-10-18").date())[0]
    after, before = api_bounds(w[1], w[2])
    posts = {}
    for term in terms:
        params = {"search": term, "after": after, "before": before, "_fields": FIELDS}
        for page in range(1, 51):
            resp = fetcher.get(f"https://{domain}/wp-json/wp/v2/posts", params={**params, "per_page": PER_PAGE, "page": page})
            if resp is None or resp.status_code != 200:
                break
            try:
                batch = resp.json()
            except ValueError:
                break
            if not isinstance(batch, list) or not batch:
                break
            for p in batch:
                if isinstance(p, dict) and p.get("link"):
                    posts.setdefault(p["link"], p)
    return posts


def inventory(year: int) -> pd.DataFrame:
    return pd.read_csv(TABLES_DIR / f"full_inventory_{year}.csv", dtype=str, keep_default_na=False)


def names_by_year() -> tuple[pd.DataFrame, dict]:
    config = load_config()
    fetcher = Fetcher(config, offline=True)
    counts, examples = Counter(), defaultdict(list)
    for year in YEARS:
        inv = inventory(year)
        excerpts = {}
        for outlet in config["outlets"]:
            posts = cached_posts(fetcher, outlet["domain"], year, SEARCH_TERMS + SPOKESPERSON_NAMES)
            excerpts.update({l: clean_html(p.get("excerpt", {}).get("rendered", "")) for l, p in posts.items()})
        for row in inv.itertuples():
            text = f"{row.title} {excerpts.get(row.url, '')}"
            for name in names_near_phrases(text):
                counts[(name, year)] += 1
                if len(examples[name]) < 2:
                    m = PHRASE_RE.search(text)
                    examples[name].append(text[max(0, m.start() - 90):m.end() + 90])
        log.info("%d: %d inventory rows, %d with a cached excerpt", year, len(inv),
                 sum(u in excerpts for u in inv["url"]))
    table = pd.Series(counts).unstack(fill_value=0) if counts else pd.DataFrame()
    return table, examples


DRY_SEARCH_FILE = "full_spokesperson_dry_search.csv"
DRY_SEARCH_COLUMNS = ["name", "year", "outlet", "posts", "complete", "new_current_filter", "new_with_name_terms"]


def dry_search(names: list[str]) -> pd.DataFrame:
    """One row per name, year and outlet: posts returned, whether the search was complete, and
    links not in that year's inventory that pass the candidate filter, under the pilot filter
    (DHQ_RE) and with the spokesperson names as DHQ references (NAMES_DHQ_RE)."""
    config = load_config()
    outlets = [o for o in config["outlets"] if o["domain"] != DHQ_DOMAIN]
    known = {y: set(inventory(y)["url"]) for y in YEARS}
    rows, lock = [], threading.Lock()

    def work(outlet):
        fetcher = Fetcher(config)
        domain = outlet["domain"]
        api = probe_api(fetcher, domain)
        if api != "yes":
            return
        for year in YEARS:
            w = year_windows(pd.Timestamp(f"{year}-01-01").date(), pd.Timestamp("2026-10-18").date())[0]
            after, before = api_bounds(w[1], w[2])
            for name in names:
                res = paginate(fetcher, domain, {"search": name, "after": after, "before": before, "_fields": FIELDS},
                               label=f"Spokesperson dry search {year} '{name}'")
                new_current = new_full = 0
                for p in res["posts"]:
                    if p["link"] in known[year]:
                        continue
                    title = clean_html(p.get("title", {}).get("rendered", ""))
                    excerpt = clean_html(p.get("excerpt", {}).get("rendered", ""))
                    new_current += match_field(title, excerpt) is not None
                    new_full += match_field(title, excerpt, NAMES_DHQ_RE) is not None
                n_posts, stop, complete = len(res["posts"]), res["stop"], res["complete"]
                del res
                log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?search={name}&after={after}&before={before}",
                           f"{n_posts} posts returned",
                           f"Spokesperson dry search {year}; stop: {stop}; {new_current} new candidates under the "
                           f"current filter, {new_full} with the spokesperson names as DHQ references; "
                           "not written to the inventory")
                with lock:
                    rows.append({"name": name, "year": year, "outlet": outlet["name"], "posts": n_posts,
                                 "complete": complete, "new_current_filter": new_current,
                                 "new_with_name_terms": new_full})

    threads = [threading.Thread(target=work, args=(o,), daemon=True) for o in outlets]
    for t in threads:
        t.start()
    for t in threads:
        while t.is_alive():
            t.join(0.5)
    return pd.DataFrame(rows, columns=DRY_SEARCH_COLUMNS)


def save_dry_search(df: pd.DataFrame, tables_dir=TABLES_DIR) -> pd.DataFrame:
    """Merge into outputs/tables/full_spokesperson_dry_search.csv: rows for the names searched
    replace earlier rows for those names."""
    path = tables_dir / DRY_SEARCH_FILE
    if path.exists():
        old = pd.read_csv(path)
        df = pd.concat([old[~old["name"].isin(df["name"].unique())], df], ignore_index=True)
    df = df.sort_values(["name", "year", "outlet"])[DRY_SEARCH_COLUMNS]
    df.to_csv(path, index=False)
    return df


def add_from_cache(tables_dir=TABLES_DIR, fetcher: Fetcher | None = None) -> pd.DataFrame:
    """Adds to each year's inventory the distinct links, not already present, that the cached
    dry-search pages return and that pass the filter with the names as DHQ references (posts
    dated inside the year only). Returns the rows added."""
    config = load_config()
    fetcher = fetcher or Fetcher(config, offline=True)
    added = []
    for year in YEARS:
        path = tables_dir / f"full_inventory_{year}.csv"
        inv = read_inventory(path)
        if inv is None:
            continue
        known, new = set(inv["url"]), {}
        _, first, last = year_windows(pd.Timestamp(f"{year}-01-01").date(), pd.Timestamp("2026-10-18").date())[0]
        first, last = str(first), str(last)
        for outlet in config["outlets"]:
            if outlet["domain"] == DHQ_DOMAIN:
                continue
            for name in SPOKESPERSON_NAMES:
                for link, p in cached_posts(fetcher, outlet["domain"], year, [name]).items():
                    day = p.get("date", "")[:10]
                    if link in known or not first <= day <= last:
                        continue
                    title = clean_html(p.get("title", {}).get("rendered", ""))
                    excerpt = clean_html(p.get("excerpt", {}).get("rendered", ""))
                    field = match_field(title, excerpt, NAMES_DHQ_RE)
                    if field is None:
                        continue
                    row = new.setdefault(link, {
                        "outlet": outlet["name"], "url": link, "title": title, "publish_date": day,
                        "search_term_hits": [], "period_phrase": period_phrase(title), "matched_field": field,
                        "kept_by_title_alone": str(_satisfies(title, NAMES_DHQ_RE)), "added_by": CHECK,
                    })
                    if name not in row["search_term_hits"]:
                        row["search_term_hits"].append(name)
        rows = pd.DataFrame([{**r, "search_term_hits": "; ".join(r["search_term_hits"])} for r in new.values()],
                            columns=ROW_COLUMNS)
        # Every year is rewritten, so each inventory carries the added_by column.
        write_inventory(path, pd.concat([inv, rows], ignore_index=True))
        if len(rows):
            added.append(rows.assign(year=year))
    return pd.concat(added, ignore_index=True) if added else pd.DataFrame(columns=ROW_COLUMNS + ["year"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("names")
    sub.add_parser("add")
    dry = sub.add_parser("dry-search")
    dry.add_argument("--names", nargs="+", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pd.set_option("display.width", 200)
    if args.cmd == "add":
        rows = add_from_cache()
        print("LINKS ADDED PER YEAR (added_by spokesperson_check)")
        print(rows.groupby("year").size().to_string() if len(rows) else "none")
        print(rows[["year", "outlet", "publish_date", "title", "search_term_hits"]].to_string(index=False))
    elif args.cmd == "names":
        table, examples = names_by_year()
        long = table.rename_axis("name").reset_index().melt(id_vars="name", var_name="year", value_name="inventory_items")
        long[long["inventory_items"] > 0].sort_values(["name", "year"]).to_csv(
            TABLES_DIR / "full_spokesperson_names.csv", index=False)
        print("NAMES BY YEAR (inventory items with the name next to a phrase)")
        print(table.to_string())
        print("EXAMPLES")
        for name, ex in examples.items():
            for e in ex:
                print(f"  {name}: ...{e}...")
    else:
        df = dry_search(args.names)
        save_dry_search(df)
        print("TOTALS BY NAME AND YEAR")
        print(df.groupby(["name", "year"])[["new_current_filter", "new_with_name_terms"]].sum().to_string())
        print(f"INCOMPLETE SEARCHES: {int((~df['complete'].astype(bool)).sum())}")


if __name__ == "__main__":
    main()
