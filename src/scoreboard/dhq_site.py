"""Coverage of DHQ's own published statements on defencehq.mil.ng (v1.1).

Usage: python -m scoreboard.dhq_site

Lists every post on defencehq.mil.ng dated from START to today, trying in order:
1. the WordPress REST API (API_PATHS), paged, fields id, date, link and title;
2. the WordPress sitemap (wp-sitemap.xml and its post sitemaps), with the date taken from a /YYYY/MM/DD/
   path where the URL has one, else from lastmod;
3. the blog and category archive pages (ARCHIVE_PATHS), paged.
Requests go through scoreboard.fetch.Fetcher: robots.txt is honoured, the configured delay
(min_delay_seconds in config/collection.yaml, at least MIN_DELAY_SECONDS) and user agent are used, and
responses are cached in data_raw/cache/. Every attempt is logged in docs/source_access_log.csv. When
robots.txt cannot be read the site counts as disallowed and nothing else is requested.

Writes data/dhq_site/posts.csv (id, date, url, title). Posts whose title matches CANDIDATE_RE are
candidate operational statements; only those are fetched, with their body text saved to data_raw/dhq/
(not committed). Each candidate is matched to the v1.0 briefings in data/briefings/full_briefings.csv
whose briefing date lies within MATCH_DAYS days of the post date; where the text states a date range
(scoreboard.audit_inputs.stated_ranges) and it equals the briefing's period in
data/briefings/check_briefings.csv, the match basis is "date and period", else "date"; among several
briefings in the window, a period match wins, then the nearest date. Writes data/dhq_site/matches.csv.
No figures are extracted.
"""

import argparse
import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

import pandas as pd
from bs4 import BeautifulSoup

from scoreboard.access_log import log_access
from scoreboard.audit_inputs import CHECK_BRIEFINGS, LEAD_CHARS, stated_ranges
from scoreboard.briefings import BRIEFINGS
from scoreboard.config import PROJECT_ROOT, load_config
from scoreboard.fetch import Fetcher, cache_key
from scoreboard.wirecheck import extract_body

DOMAIN = "defencehq.mil.ng"
ORIGIN = f"https://{DOMAIN}"
START = date(2021, 1, 1)
MIN_DELAY_SECONDS = 2
API_PATHS = ["/index.php/wp-json/wp/v2/posts", "/wp-json/wp/v2/posts"]
SITEMAP_PATH = "/wp-sitemap.xml"
ARCHIVE_PATHS = ["/blog/", "/category/news/", "/category/press-release/"]
PER_PAGE = 100
MAX_PAGES = 200
OUT_DIR = PROJECT_ROOT / "data" / "dhq_site"
POSTS = OUT_DIR / "posts.csv"
MATCHES = OUT_DIR / "matches.csv"
TEXT_DIR = PROJECT_ROOT / "data_raw" / "dhq"
POST_COLUMNS = ["id", "date", "url", "title"]
MATCH_COLUMNS = ["briefing_id", "post_url", "post_date", "match_basis", "stated_period"]
MATCH_DAYS = 3
CANDIDATE_RE = re.compile(
    r"update on (?:the )?armed forces of nigeria operations|press briefing|defen[cs]e media operations"
    r"|\boperations?\b|\btroops\b", re.I)
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
PATH_DATE_RE = re.compile(r"/(20\d\d)/(\d\d)/(\d\d)/")


def make_fetcher(config: dict | None = None) -> Fetcher:
    config = dict(config or load_config())
    config["min_delay_seconds"] = max(float(config["min_delay_seconds"]), MIN_DELAY_SECONDS)
    return Fetcher(config)


def _log(url: str, result: str, notes: str) -> None:
    log_access(DOMAIN, url, result, f"v1.1 DHQ site listing: {notes}")


def _clean_title(raw: str) -> str:
    return " ".join(BeautifulSoup(html.unescape(raw or ""), "html.parser").get_text().split())


def _in_range(d: str, end: date) -> bool:
    return bool(d) and START.isoformat() <= d[:10] <= end.isoformat()


# Listing


def posts_from_api(fetcher, end: date) -> list[dict] | None:
    """Every post from the REST API, or None when no API path answers with JSON."""
    for path in API_PATHS:
        url = ORIGIN + path
        posts = []
        for page in range(1, MAX_PAGES + 1):
            params = {"per_page": PER_PAGE, "page": page, "after": f"{START}T00:00:00",
                      "before": f"{end + timedelta(days=1)}T00:00:00", "_fields": "id,date,link,title",
                      "orderby": "date", "order": "asc"}
            resp = fetcher.get(url, params)
            if resp is None or resp.status_code != 200:
                _log(url, f"HTTP {resp.status_code}" if resp else fetcher.skip_reason, f"REST API page {page}")
                break
            try:
                batch = resp.json()
            except ValueError:
                _log(url, "not JSON", f"REST API page {page}")
                break
            posts += [{"id": str(p.get("id", "")), "date": str(p.get("date", ""))[:10], "url": p.get("link", ""),
                       "title": _clean_title((p.get("title") or {}).get("rendered", ""))} for p in batch]
            total_pages = int(resp.headers.get("X-WP-TotalPages") or resp.headers.get("x-wp-totalpages") or 0)
            if not batch or (total_pages and page >= total_pages):
                break
        if posts:
            _log(url, "HTTP 200", f"REST API: {len(posts)} posts")
            return posts
    return None


def _sitemap_locs(text: str) -> list[tuple[str, str]]:
    root = ET.fromstring(text)
    out = []
    for el in root.findall("s:sitemap", SITEMAP_NS) + root.findall("s:url", SITEMAP_NS):
        loc = el.findtext("s:loc", default="", namespaces=SITEMAP_NS).strip()
        lastmod = el.findtext("s:lastmod", default="", namespaces=SITEMAP_NS).strip()
        out.append((loc, lastmod))
    return out


def date_from_url(url: str, lastmod: str = "") -> str:
    m = PATH_DATE_RE.search(urlsplit(url).path)
    return "-".join(m.groups()) if m else lastmod[:10]


def title_from_url(url: str) -> str:
    slug = [s for s in urlsplit(url).path.split("/") if s]
    return slug[-1].replace("-", " ") if slug else ""


def posts_from_sitemap(fetcher, end: date) -> list[dict] | None:
    resp = fetcher.get(ORIGIN + SITEMAP_PATH)
    if resp is None or resp.status_code != 200:
        _log(ORIGIN + SITEMAP_PATH, f"HTTP {resp.status_code}" if resp else fetcher.skip_reason, "sitemap index")
        return None
    posts = []
    for loc, _ in _sitemap_locs(resp.text):
        if "posts-post" not in loc:
            continue
        sub = fetcher.get(loc)
        if sub is None or sub.status_code != 200:
            _log(loc, f"HTTP {sub.status_code}" if sub else fetcher.skip_reason, "post sitemap")
            continue
        posts += [{"id": "", "date": date_from_url(u, lm), "url": u, "title": title_from_url(u)}
                  for u, lm in _sitemap_locs(sub.text)]
    posts = [p for p in posts if _in_range(p["date"], end)]
    if posts:
        _log(ORIGIN + SITEMAP_PATH, "HTTP 200", f"sitemap: {len(posts)} posts")
    return posts or None


def archive_entries(page_html: str) -> list[dict]:
    """Posts on one archive page: each <article> with a heading link and a <time datetime>."""
    soup = BeautifulSoup(page_html, "html.parser")
    out = []
    for art in soup.find_all("article"):
        link = art.select_one("h1 a[href], h2 a[href], h3 a[href]") or art.find("a", href=True)
        when = art.find("time")
        if not link:
            continue
        d = (when.get("datetime") or "")[:10] if when else ""
        out.append({"id": "", "date": d or date_from_url(link["href"]), "url": link["href"],
                    "title": " ".join(link.get_text().split())})
    return out


def posts_from_archive(fetcher, end: date) -> list[dict] | None:
    seen, posts = set(), []
    for path in ARCHIVE_PATHS:
        for page in range(1, MAX_PAGES + 1):
            url = ORIGIN + path + (f"page/{page}/" if page > 1 else "")
            resp = fetcher.get(url)
            if resp is None or resp.status_code != 200:
                _log(url, f"HTTP {resp.status_code}" if resp else fetcher.skip_reason, f"archive page {page}")
                break
            entries = [e for e in archive_entries(resp.text) if e["url"] not in seen]
            if not entries:
                break
            seen.update(e["url"] for e in entries)
            posts += entries
            if min(e["date"] for e in entries if e["date"]) < START.isoformat():
                break
    posts = [p for p in posts if _in_range(p["date"], end)]
    return posts or None


def list_posts(fetcher, end: date) -> tuple[pd.DataFrame, str]:
    """All posts from START to end and the method that listed them ("REST API", "sitemap", "archive"),
    or an empty table and the reason nothing could be listed."""
    allowed, status = fetcher.check_robots(ORIGIN + "/")
    _log(ORIGIN + "/robots.txt", f"robots.txt {status}", "check before listing posts")
    if not allowed:
        return pd.DataFrame(columns=POST_COLUMNS), f"not listed: robots.txt {status}"
    for method, lister in (("REST API", posts_from_api), ("sitemap", posts_from_sitemap),
                           ("archive", posts_from_archive)):
        posts = lister(fetcher, end)
        if posts:
            df = pd.DataFrame(posts, columns=POST_COLUMNS).drop_duplicates("url").sort_values(["date", "url"])
            return df.reset_index(drop=True), method
    return pd.DataFrame(columns=POST_COLUMNS), "not listed: no method returned posts"


# Candidates and matching


def candidates(posts: pd.DataFrame) -> pd.DataFrame:
    return posts[posts["title"].str.contains(CANDIDATE_RE, na=False)].reset_index(drop=True)


def text_file(url: str):
    return TEXT_DIR / f"{cache_key(url)}.txt"


def fetch_texts(fetcher, cands: pd.DataFrame) -> dict[str, str]:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    texts = {}
    for url in cands["url"]:
        path = text_file(url)
        if path.exists():
            texts[url] = path.read_text(encoding="utf-8")
            continue
        resp = fetcher.get(url)
        if resp is None or resp.status_code != 200:
            _log(url, f"HTTP {resp.status_code}" if resp else fetcher.skip_reason, "candidate statement")
            continue
        texts[url] = extract_body(resp.text)
        path.write_text(texts[url], encoding="utf-8")
    return texts


def match(cands: pd.DataFrame, texts: dict[str, str], briefings: pd.DataFrame,
          periods: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per briefing matched to a candidate post (the best post for each briefing)."""
    period = {} if periods is None else {r["confirmed_group_id"]: (r["period_start"], r["period_end"])
                                          for r in periods.to_dict("records")}
    rows = []
    for c in cands.to_dict("records"):
        if not c["date"]:
            continue
        pdate = date.fromisoformat(c["date"][:10])
        ranges = stated_ranges((texts.get(c["url"]) or "")[:LEAD_CHARS])
        stated = f"{ranges[0][0]} to {ranges[0][1]}" if ranges else ""
        stated_pair = (str(ranges[0][0]), str(ranges[0][1])) if ranges else None
        for b in briefings.to_dict("records"):
            days = abs((date.fromisoformat(b["first_date"]) - pdate).days)
            if days > MATCH_DAYS:
                continue
            by_period = stated_pair is not None and period.get(b["briefing_id"]) == stated_pair
            rows.append({"briefing_id": b["briefing_id"], "post_url": c["url"], "post_date": c["date"][:10],
                         "match_basis": "date and period" if by_period else "date", "stated_period": stated,
                         "_rank": (0 if by_period else 1, days)})
    if not rows:
        return pd.DataFrame(columns=MATCH_COLUMNS)
    df = pd.DataFrame(rows).sort_values(["briefing_id", "_rank", "post_url"])
    return df.drop_duplicates("briefing_id")[MATCH_COLUMNS].reset_index(drop=True)


def coverage_by_year(matches: pd.DataFrame, briefings: pd.DataFrame) -> pd.DataFrame:
    years = briefings["briefing_id"].str[1:5]
    matched = years[briefings["briefing_id"].isin(matches["briefing_id"])]
    return pd.DataFrame({"briefings": years.value_counts(), "matched": matched.value_counts()}).fillna(0).astype(int)


def run(fetcher=None, end: date | None = None):
    fetcher = fetcher or make_fetcher()
    end = end or date.today()
    posts, method = list_posts(fetcher, end)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    posts.to_csv(POSTS, index=False)
    cands = candidates(posts)
    texts = fetch_texts(fetcher, cands) if len(cands) else {}
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    briefings = read(BRIEFINGS)
    periods = read(CHECK_BRIEFINGS) if CHECK_BRIEFINGS.exists() else None
    matches = match(cands, texts, briefings, periods)
    matches.to_csv(MATCHES, index=False)
    return method, posts, cands, matches, coverage_by_year(matches, briefings)


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    method, posts, cands, matches, cov = run()
    print(f"listing: {method}; posts {START} to {date.today()}: {len(posts)}; candidates: {len(cands)}")
    print(f"briefings with a matched DHQ statement: {len(matches)} of {cov['briefings'].sum()}")
    print(cov.to_string())


if __name__ == "__main__":
    main()
