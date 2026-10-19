"""Spokesperson check: personal names next to the DHQ media-office phrases in the full inventory.

Usage:
  python -m scoreboard.spokesperson names
  python -m scoreboard.spokesperson dry-search --names "Name One" "Name Two"

`names` reads titles from outputs/tables/full_inventory_<year>.csv and the excerpts of the same
links from the cached REST API search pages (offline: no request is sent). Names are taken only
from text next to the phrases in PHRASES; no outside list of names is used. Prints names with
counts by year (an item counts once per name).

`dry-search` searches each name per year on every outlet through the polite fetcher and prints
how many links passing the candidate filter are not already in that year's inventory, in two
variants: the current filter, and the filter with the name treated as a DHQ reference (as
"Buba" is). Nothing is written to the inventory.
"""

import argparse
import logging
import re
import threading
from collections import Counter, defaultdict

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.collect import DHQ_DOMAIN, api_bounds, year_windows
from scoreboard.config import load_config
from scoreboard.discover import (
    DHQ_RE,
    FIELDS,
    OUTCOME_RE,
    PER_PAGE,
    SEARCH_TERMS,
    TABLES_DIR,
    clean_html,
    match_field,
    paginate,
    probe_api,
)
from scoreboard.fetch import Fetcher

log = logging.getLogger(__name__)

YEARS = range(2021, 2027)
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
            posts = cached_posts(fetcher, outlet["domain"], year, SEARCH_TERMS)
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


def _filter_with(name: str):
    alias = re.compile(r"\b" + r"\s+".join(map(re.escape, name.split())) + r"\b|\b" + re.escape(name.split()[-1]) + r"\b", re.I)

    def keep(title, excerpt):
        text = f"{title} {excerpt}"
        return bool((DHQ_RE.search(text) or alias.search(text)) and OUTCOME_RE.search(text))
    return keep


def dry_search(names: list[str]) -> pd.DataFrame:
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
                keep = _filter_with(name)
                new_current = new_alias = 0
                for p in res["posts"]:
                    if p["link"] in known[year]:
                        continue
                    title = clean_html(p.get("title", {}).get("rendered", ""))
                    excerpt = clean_html(p.get("excerpt", {}).get("rendered", ""))
                    new_current += match_field(title, excerpt) is not None
                    new_alias += keep(title, excerpt)
                log_access(domain, f"https://{domain}/wp-json/wp/v2/posts?search={name}&after={after}&before={before}",
                           f"{len(res['posts'])} posts returned",
                           f"Spokesperson dry search {year}; stop: {res['stop']}; {new_current} new candidates under the "
                           f"current filter, {new_alias} with the name as a DHQ reference; not written to the inventory")
                with lock:
                    rows.append({"name": name, "year": year, "outlet": outlet["name"], "posts": len(res["posts"]),
                                 "complete": res["complete"], "new_current_filter": new_current,
                                 "new_with_name_as_dhq": new_alias})

    threads = [threading.Thread(target=work, args=(o,), daemon=True) for o in outlets]
    for t in threads:
        t.start()
    for t in threads:
        while t.is_alive():
            t.join(0.5)
    return pd.DataFrame(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("names")
    dry = sub.add_parser("dry-search")
    dry.add_argument("--names", nargs="+", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pd.set_option("display.width", 200)
    if args.cmd == "names":
        table, examples = names_by_year()
        print("NAMES BY YEAR (inventory items with the name next to a phrase)")
        print(table.to_string())
        print("EXAMPLES")
        for name, ex in examples.items():
            for e in ex:
                print(f"  {name}: ...{e}...")
    else:
        df = dry_search(args.names)
        print(df.sort_values(["name", "year", "outlet"]).to_string(index=False))
        print("TOTALS BY NAME AND YEAR")
        print(df.groupby(["name", "year"])[["new_current_filter", "new_with_name_as_dhq"]].sum().to_string())
        print(f"INCOMPLETE SEARCHES: {int((~df['complete']).sum())}")


if __name__ == "__main__":
    main()
