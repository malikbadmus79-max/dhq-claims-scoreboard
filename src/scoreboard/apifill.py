"""Fill missing article text through outlets' WordPress REST APIs.

Usage: python -m scoreboard.apifill --year 2024

Applies to items whose article page gave no text and whose outlet answered the
WordPress API in discovery. Posts are looked up by slug and accepted only when
the returned link matches the inventory URL. Text is stored only in
data_raw/text/; bot-challenge pages are never solved, and cached ones are deleted.
"""

import argparse
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pandas as pd
from bs4 import BeautifulSoup

from scoreboard.access_log import log_access
from scoreboard.discover import TABLES_DIR
from scoreboard.fetch import DEFAULT_CACHE_DIR, Fetcher
from scoreboard.wirecheck import (
    STRIP_TAGS,
    TEXT_DIR,
    _paragraph_text,
    analyse,
    is_challenge_page,
    read_item_checks,
    summarise,
    text_path,
)

log = logging.getLogger(__name__)


def slug_candidates(url: str) -> list[str]:
    """Slug of the last path segment, with and without a leading numeric post ID."""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    if not segments:
        return []
    slug = re.sub(r"\.html?$", "", unquote(segments[-1]))
    candidates = [slug]
    m = re.match(r"^\d+-(.+)$", slug)
    if m:
        candidates.append(m.group(1))
    return candidates


def normalise_link(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{unquote(parts.path).rstrip('/')}".lower()


def content_text(content_html: str) -> str:
    soup = BeautifulSoup(content_html, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    return _paragraph_text(soup)


def fill_from_api(fetcher: Fetcher, domain: str, url: str) -> tuple[str, str]:
    """Return (api_status, text). Text is empty unless a post with the same link is found."""
    status = "no matching post"
    for slug in slug_candidates(url):
        resp = fetcher.get(
            f"https://{domain}/wp-json/wp/v2/posts", params={"slug": slug, "_fields": "link,content"}
        )
        if resp is None:
            return fetcher.skip_reason or "request failed", ""
        if resp.status_code != 200:
            status = f"HTTP {resp.status_code}"
            continue
        try:
            posts = resp.json()
        except ValueError:
            status = "non-JSON response"
            continue
        for post in posts if isinstance(posts, list) else []:
            if normalise_link(post.get("link", "")) != normalise_link(url):
                continue
            text = content_text(post.get("content", {}).get("rendered", ""))
            return ("ok", text) if text else ("empty content", "")
    return status, ""


def purge_challenge_pages(cache_dir: Path = DEFAULT_CACHE_DIR) -> int:
    removed = 0
    for path in cache_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status_code") == 200 and is_challenge_page(data.get("text", "")):
            path.unlink()
            removed += 1
    return removed


def _fill_domain(domain: str, urls: list[str]) -> list[tuple[str, str]]:
    fetcher = Fetcher()
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for url in urls:
        status, text = fill_from_api(fetcher, domain, url)
        if text:
            text_path(url).write_text(text, encoding="utf-8")
        results.append((url, status))
    return results


def fetch_status_table(items: pd.DataFrame, column: str) -> pd.DataFrame:
    return pd.crosstab(items["outlet"], items[column].replace("", "(none)"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    inventory = pd.read_csv(TABLES_DIR / f"pilot_inventory_{args.year}.csv", keep_default_na=False)
    outlets = pd.read_csv(TABLES_DIR / f"pilot_outlets_{args.year}.csv", keep_default_na=False)
    items = read_item_checks(args.year)
    ok = items["fetch_status"].str.startswith("ok")
    items.loc[ok & items["text_source"].eq(""), "text_source"] = "article page"
    before = fetch_status_table(items, "fetch_status")

    removed = purge_challenge_pages()
    log.info("deleted %d cached challenge pages", removed)

    api_domains = dict(zip(outlets.loc[outlets["wp_api"] == "yes", "outlet"], outlets.loc[outlets["wp_api"] == "yes", "domain"]))
    targets = items[~ok & items["outlet"].isin(api_domains) & items["text_source"].eq("")]
    by_domain = defaultdict(list)
    for row in targets.itertuples():
        by_domain[api_domains[row.outlet]].append(row.url)
    with ThreadPoolExecutor(max_workers=len(by_domain) or 1) as pool:
        results = dict(
            r for domain_results in pool.map(lambda kv: _fill_domain(*kv), by_domain.items()) for r in domain_results
        )

    items["api_status"] = [results.get(u, s) for u, s in zip(items["url"], items["api_status"])]
    filled = items["url"].map(lambda u: results.get(u) == "ok")
    items.loc[filled, "text_source"] = "WordPress API"

    pairs, items, groups, review = analyse(inventory, items, args.year)

    for domain, urls in by_domain.items():
        statuses = pd.Series([results[u] for u in urls]).value_counts().to_dict()
        log_access(
            domain,
            f"https://{domain}/wp-json/wp/v2/posts?slug=<slug>&_fields=link,content",
            f"{statuses.get('ok', 0)} of {len(urls)} missing texts filled from WordPress API",
            f"API text fill {args.year}; statuses: {statuses}",
        )

    print(f"Cached challenge pages deleted: {removed}\n")
    print("Article-page fetch status by outlet (before)")
    print(before.to_string(), "\n")
    print("Text source by outlet (after)")
    print(fetch_status_table(items, "text_source").to_string(), "\n")
    print("API status of attempted items")
    print(pd.Series(results).value_counts().to_string() if results else "(none attempted)", "\n")
    print(summarise(pairs, items, groups, review))


if __name__ == "__main__":
    main()
