"""Inventory candidate DHQ operational briefings through outlets' WordPress REST APIs.

Usage: python -m scoreboard.discover --year 2024
"""

import argparse
import html
import logging
import re
from datetime import date

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.config import PROJECT_ROOT, load_config
from scoreboard.fetch import OFFLINE_MISS, Fetcher, full_url

log = logging.getLogger(__name__)

TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
SEARCH_TERMS = ["Defence Headquarters", "DHQ", "Defence Media Operations", "Buba"]
FIELDS = "date,link,title,excerpt"
PER_PAGE = 100
MAX_PAGES = 50
GROUP_WINDOW_DAYS = 3

# "Buba" names the DHQ spokesman, except in "Buba Marwa" (chairman of the NDLEA).
BUBA = r"\bbuba\b(?![\s-]+marwa\b)"
DHQ_RE = re.compile(
    rf"\bdhq\b|defen[cs]e headquarters|defen[cs]e media operations|defen[cs]e information|{BUBA}",
    re.I,
)
OUTCOME_RE = re.compile(
    r"neutrali[sz]|kill|eliminat|arrest|apprehend|rescu|surrender", re.I
)
MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
PERIOD_RE = re.compile(rf"\bone week\b|\btwo weeks\b|\bin (?:{MONTHS})\b|\b2024\b", re.I)
FIGURE_RE = re.compile(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b")
TAG_RE = re.compile(r"<[^>]+>")
INVENTORY_COLUMNS = [
    "outlet",
    "url",
    "title",
    "publish_date",
    "search_term_hits",
    "period_phrase",
    "matched_field",
    "kept_by_title_alone",
    "briefing_group_id",
    "grouping_status",
]


def _satisfies(text: str) -> bool:
    return bool(DHQ_RE.search(text) and OUTCOME_RE.search(text))


def _has_terms(text: str) -> bool:
    return bool(DHQ_RE.search(text) or OUTCOME_RE.search(text))


def match_field(title: str, excerpt: str = "") -> str | None:
    """Return "title", "excerpt" or "both" for a candidate, or None if the rule fails.

    The rule: title or excerpt names DHQ (or its media office or spokesman), and
    title or excerpt contains an outcome word. "title" or "excerpt" means that
    field alone holds every matched term; "both" means matched terms occur in both.
    """
    if not _satisfies(f"{title} {excerpt}"):
        return None
    in_title, in_excerpt = _has_terms(title), _has_terms(excerpt)
    if in_title and in_excerpt:
        return "both"
    return "title" if in_title else "excerpt"


def is_candidate(title: str, excerpt: str = "") -> bool:
    return match_field(title, excerpt) is not None


def clean_html(text: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", text)).split())


def period_phrase(title: str) -> str:
    return "; ".join(m.group(0) for m in PERIOD_RE.finditer(title))


def headline_figures(title: str) -> set[int]:
    """Numbers of 10 or more in a title, excluding bare years 2000-2030."""
    figures = set()
    for m in FIGURE_RE.finditer(title):
        raw = m.group(0)
        value = int(raw.replace(",", ""))
        if value < 10 or ("," not in raw and 2000 <= value <= 2030):
            continue
        figures.add(value)
    return figures


def assign_groups(df: pd.DataFrame, prefix: str = "P") -> pd.Series:
    """Link rows within GROUP_WINDOW_DAYS that share a headline figure; return group IDs."""
    parent = list(range(len(df)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    dates = pd.to_datetime(df["publish_date"]).tolist()
    figures = [headline_figures(t) for t in df["title"]]
    for i in range(len(df)):
        for j in range(i + 1, len(df)):
            if abs((dates[i] - dates[j]).days) <= GROUP_WINDOW_DAYS and figures[i] & figures[j]:
                parent[find(i)] = find(j)

    roots = [find(i) for i in range(len(df))]
    first_date = {}
    for root, d in zip(roots, dates):
        first_date[root] = min(first_date.get(root, d), d)
    order = sorted(first_date, key=lambda r: (first_date[r], r))
    year = dates[0].year if dates else 0
    ids = {root: f"{prefix}{year}-{n:03d}" for n, root in enumerate(order, start=1)}
    return pd.Series([ids[r] for r in roots], index=df.index)


def probe_api(fetcher: Fetcher, domain: str) -> str:
    resp = fetcher.get(
        f"https://{domain}/wp-json/wp/v2/posts", params={"per_page": 1, "_fields": FIELDS}
    )
    if resp is None:
        return f"not checked ({fetcher.skip_reason})"
    if resp.status_code != 200:
        return f"no API (HTTP {resp.status_code})"
    try:
        body = resp.json()
    except ValueError:
        return "no API (non-JSON)"
    return "yes" if isinstance(body, list) else "no API (unexpected JSON)"


INVALID_PAGE_CODE = "rest_post_invalid_page_number"
# Stops that mean every available page was read (or the cap was reached). Any other stop, such
# as a request that failed after retries, leaves the query incomplete.
COMPLETE_STOPS = {"empty page", "invalid page number", "page cap"}
# Stop recorded when the caller's should_stop() turns true (time budget spent); incomplete.
BUDGET_STOP = "time budget exceeded"
# "invalid response" (not JSON, or not a JSON list) and "repeated page" (a page adding no new
# links) are incomplete: the site may hold posts it did not serve.


def _error_code(resp) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    return body.get("code", "") if isinstance(body, dict) else ""


def paginate(fetcher: Fetcher, domain: str, params: dict, label: str = "", should_stop=None) -> dict:
    """All posts for one REST API query. X-WP-Total and X-WP-TotalPages are not used, since some
    sites send them as 0 or too low: pages are requested until one returns zero posts or the API
    answers HTTP 400 with rest_post_invalid_page_number, up to MAX_PAGES. Posts are de-duplicated
    by link; a page adding no new link stops paging ("repeated page"). A body that is not a JSON
    list stops paging ("invalid response"). Posts dated outside the after/before window are
    dropped and counted, and a log row records that the site ignores the date filter. A query
    that reaches the cap is logged with pages requested and unique posts. When `should_stop()` is
    true before a page is read, or after a request fails, paging stops with BUDGET_STOP.

    Returns {"posts", "pages", "stop", "capped", "cached_pages", "dropped_outside_window",
    "complete"}; "pages" counts pages requested, "stop" is why paging ended."""
    url = f"https://{domain}/wp-json/wp/v2/posts"
    posts: list[dict] = []
    seen: set[str] = set()
    cached = dropped = requested = 0
    after, before = params.get("after"), params.get("before")

    def done(stop, capped=False):
        if dropped:
            log_access(domain, full_url(url, params), f"{dropped} posts outside the date window dropped",
                       f"{label}; the site ignores the after/before date filter")
        return {"posts": posts, "pages": requested, "stop": stop, "capped": capped, "cached_pages": cached,
                "dropped_outside_window": dropped, "complete": stop in COMPLETE_STOPS}

    stopped = should_stop or (lambda: False)
    for page in range(1, MAX_PAGES + 1):
        if stopped():
            return done(BUDGET_STOP)
        resp = fetcher.get(url, params={**params, "per_page": PER_PAGE, "page": page})
        if resp is None:
            return done(BUDGET_STOP if stopped() else fetcher.skip_reason or "request failed")
        requested += 1
        cached += int(getattr(resp, "from_cache", False))
        if resp.status_code == 400 and _error_code(resp) == INVALID_PAGE_CODE:
            return done("invalid page number")
        if resp.status_code != 200:
            return done(f"HTTP {resp.status_code}")
        try:
            batch = resp.json()
        except ValueError:
            return done("invalid response")
        if not isinstance(batch, list):
            return done("invalid response")
        if not batch:
            return done("empty page")
        new = [p for p in batch if isinstance(p, dict) and p.get("link") and p["link"] not in seen]
        if not new:
            # The site serves the same posts again, e.g. it ignores the page parameter.
            return done("repeated page")
        for post in new:
            seen.add(post["link"])
            stamp = post.get("date", "")
            if stamp and ((after and stamp <= after) or (before and stamp >= before)):
                dropped += 1
                continue
            posts.append(post)
    log_access(
        domain,
        full_url(url, params),
        f"page cap reached ({requested} pages requested)",
        f"{label}; {len(seen)} unique posts returned, {len(posts)} inside the date window; later pages not requested",
    )
    return done("page cap", capped=True)


def search_window(fetcher: Fetcher, domain: str, after: str, before: str, label: str = "",
                  should_stop=None) -> tuple[dict, dict]:
    """Search hits for every term between `after` and `before` (REST API date strings).

    Returns ({link: {title, excerpt, date, terms}}, {"queries", "capped", "stops"}). Excerpts are
    held in memory for filtering only and are never written out."""
    hits: dict[str, dict] = {}
    stats = {"queries": 0, "capped": 0, "incomplete": 0, "pages": 0, "cached_pages": 0, "stops": []}
    for term in SEARCH_TERMS:
        result = paginate(fetcher, domain, {"search": term, "after": after, "before": before, "_fields": FIELDS},
                          label=f"{label} search '{term}'", should_stop=should_stop)
        stats["queries"] += 1
        stats["capped"] += int(result["capped"])
        stats["incomplete"] += int(not result["complete"])
        stats["pages"] += result["pages"]
        stats["cached_pages"] += result["cached_pages"]
        stats["stops"].append(result["stop"])
        for post in result["posts"]:
            link = post.get("link")
            if not link:
                continue
            entry = hits.setdefault(
                link,
                {
                    "title": clean_html(post.get("title", {}).get("rendered", "")),
                    "excerpt": clean_html(post.get("excerpt", {}).get("rendered", "")),
                    "date": post.get("date", "")[:10],
                    "terms": [],
                },
            )
            if term not in entry["terms"]:
                entry["terms"].append(term)
    return hits, stats


def search_outlet(fetcher: Fetcher, domain: str, year: int) -> dict[str, dict]:
    """Return {link: {title, excerpt, date, terms}} for all search hits in the year."""
    hits, _ = search_window(fetcher, domain, f"{year - 1}-12-31T23:59:59", f"{year + 1}-01-01T00:00:00",
                            label=f"Discovery {year}")
    return hits


def build_inventory(year: int, fetcher: Fetcher | None = None):
    config = load_config()
    fetcher = fetcher or Fetcher(config)
    start, end = date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()
    outlet_rows, rows = [], []
    for outlet in config["outlets"]:
        domain = outlet["domain"]
        api = probe_api(fetcher, domain)
        log.info("%s: API %s", domain, api)
        hits = search_outlet(fetcher, domain, year) if api == "yes" else {}
        found = 0
        for link, h in hits.items():
            if not (start <= h["date"] <= end):
                continue
            field = match_field(h["title"], h["excerpt"])
            if field is None:
                continue
            found += 1
            rows.append(
                {
                    "outlet": outlet["name"],
                    "url": link,
                    "title": h["title"],
                    "publish_date": h["date"],
                    "search_term_hits": "; ".join(h["terms"]),
                    "period_phrase": period_phrase(h["title"]),
                    "matched_field": field,
                    "kept_by_title_alone": _satisfies(h["title"]),
                }
            )
        outlet_rows.append(
            {
                "outlet": outlet["name"],
                "domain": domain,
                "wp_api": api,
                "search_hits": len(hits),
                "candidates": found,
            }
        )

    inventory = pd.DataFrame(rows, columns=INVENTORY_COLUMNS[:-2])
    inventory = inventory.sort_values(["publish_date", "outlet", "url"]).reset_index(drop=True)
    inventory["briefing_group_id"] = assign_groups(inventory) if len(inventory) else []
    inventory["grouping_status"] = "provisional"
    return inventory[INVENTORY_COLUMNS], pd.DataFrame(outlet_rows)


def write_outputs(inventory: pd.DataFrame, outlets: pd.DataFrame, year: int, tables_dir=TABLES_DIR):
    tables_dir.mkdir(parents=True, exist_ok=True)
    inventory[INVENTORY_COLUMNS].to_csv(tables_dir / f"pilot_inventory_{year}.csv", index=False)
    outlets.to_csv(tables_dir / f"pilot_outlets_{year}.csv", index=False)


def summarise(inventory: pd.DataFrame, outlets: pd.DataFrame) -> str:
    lines = ["Outlets", outlets.to_string(index=False), ""]
    by_month = inventory["publish_date"].str[:7].value_counts().sort_index()
    lines += ["Candidates by month", by_month.to_string(), ""]
    copies = inventory.groupby("briefing_group_id")["outlet"].nunique()
    bands = pd.cut(copies, [0, 1, 2, float("inf")], labels=["1", "2", "3+"]).value_counts().sort_index()
    lines += [f"Provisional briefing groups: {len(copies)}", "Groups by outlet copies", bands.to_string(), ""]
    dhq = inventory[inventory["url"].str.contains("defencehq.mil.ng", regex=False)]
    lines += [f"defencehq.mil.ng items: {len(dhq)}", ""]
    lines += ["Candidates by matched field", inventory["matched_field"].value_counts().to_string()]
    excerpt_only = int((~inventory["kept_by_title_alone"].astype(bool)).sum())
    lines += [f"Kept only because of the excerpt: {excerpt_only}", ""]
    recent = inventory.sort_values("publish_date", ascending=False).head(15)
    lines += ["15 most recent", recent[["outlet", "publish_date", "title"]].to_string(index=False)]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--offline", action="store_true", help="rebuild from cached responses only; no requests are sent"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.offline:
        inventory, outlets = build_inventory(args.year, fetcher=Fetcher(offline=True))
        # Outlets whose API probe is not cached keep the status recorded when they were tried.
        previous = pd.read_csv(TABLES_DIR / f"pilot_outlets_{args.year}.csv", keep_default_na=False)
        recorded = previous.set_index("domain")["wp_api"]
        missed = outlets["wp_api"].str.contains(OFFLINE_MISS, regex=False)
        outlets.loc[missed, "wp_api"] = outlets.loc[missed, "domain"].map(recorded)
        write_outputs(inventory, outlets, args.year)
        print(summarise(inventory, outlets))
        return

    inventory, outlets = build_inventory(args.year)
    write_outputs(inventory, outlets, args.year)
    for row in outlets.itertuples():
        log_access(
            row.domain,
            f"https://{row.domain}/wp-json/wp/v2/posts?per_page=1",
            row.wp_api,
            f"Discovery {args.year}: {row.search_hits} search hits, {row.candidates} candidates",
        )
    print(summarise(inventory, outlets))


if __name__ == "__main__":
    main()
