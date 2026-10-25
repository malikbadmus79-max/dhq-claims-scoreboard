"""DHQ statements from archived copies of defencehq.mil.ng in the Wayback Machine (v1.1).

Usage: python -m scoreboard.dhq_wayback [--index-only]

1. Index: the Wayback CDX API (CDX_API) is queried for defencehq.mil.ng/* captures from START to today,
   status 200 and HTML only, collapsed by urlkey, paged with resume keys. Writes
   data/dhq_site/wayback_index.csv: original url, first and last capture timestamp, number of captures.
2. Post pages are the URLs with a /YYYY/MM/DD/slug/ path (with or without /index.php) dated from START, a
   ?p=ID query, a /news/slug path, or a single top-level article slug (SLUG_MIN_HYPHENS or more hyphens,
   not a site section in SECTIONS or SECTION_SLUG_PREFIXES). Only dated paths carry a date before fetching; the others take the
   post date from the archived page (article:published_time or <time>).
   Candidates are post pages whose slug matches CANDIDATE_RE; ?p=ID pages, which have no slug, are
   candidates too and are kept only when the archived title matches CANDIDATE_RE. The earliest capture of
   each candidate is fetched as an id_ URL (the archived page without the Wayback banner); its body text
   goes to data_raw/dhq/ (not committed) and its title, post date and snapshot timestamp to
   data/dhq_site/wayback_candidates.csv.
3. Candidates are matched to v1.0 briefings as in scoreboard.dhq_site.match (post date within MATCH_DAYS
   days either side of the briefing date; stated period where the text gives one). Writes
   data/dhq_site/matches.csv with source "wayback" and the snapshot timestamp.

Requests go through scoreboard.fetch.Fetcher (web.archive.org's robots.txt, the configured delay for that
host, the project user agent, cached responses), and every request is logged in
docs/source_access_log.csv. Evidence label of these texts: "DHQ statement, archived copy" (docs/sources.md).
No figures are extracted.
"""

import argparse
import json
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pandas as pd
from bs4 import BeautifulSoup

from scoreboard.access_log import log_access
from scoreboard.audit_inputs import CHECK_BRIEFINGS
from scoreboard.briefings import BRIEFINGS
from scoreboard.dhq_site import MATCH_COLUMNS, MATCHES, OUT_DIR, START, TEXT_DIR, coverage_by_year, match
from scoreboard.fetch import Fetcher, cache_key
from scoreboard.wirecheck import extract_body

SOURCE = "web.archive.org"
CDX_API = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT_URL = "https://web.archive.org/web/{timestamp}id_/{url}"
DOMAIN_QUERY = "defencehq.mil.ng/*"
PAGE_LIMIT = 5000
EVIDENCE_LABEL = "DHQ statement, archived copy"
INDEX = OUT_DIR / "wayback_index.csv"
CANDIDATES = OUT_DIR / "wayback_candidates.csv"
INDEX_COLUMNS = ["original", "first_timestamp", "last_timestamp", "captures"]
CANDIDATE_COLUMNS = ["url", "post_date", "title", "snapshot_timestamp", "snapshot_url", "fetch_status"]
WAYBACK_MATCH_COLUMNS = [*MATCH_COLUMNS, "source", "snapshot_timestamp", "title"]
POST_PATH_RE = re.compile(r"^(?:/index\.php)?/(20\d\d)/(\d\d)/(\d\d)/([^/?#]+)/?$")
NEWS_PATH_RE = re.compile(r"^(?:/index\.php)?/news/([^/?#]+)/?$")
TOP_SLUG_RE = re.compile(r"^(?:/index\.php)?/([^/?#]+)/?$")
SECTIONS = {"news", "cds", "gallery", "about", "departments", "directorates", "services", "triservices",
            "contact", "contact-us", "home"}
SLUG_MIN_HYPHENS = 4
# Slugs of department and directorate pages, which are site sections, not statements.
SECTION_SLUG_PREFIXES = ("department-", "directorate-")
CANDIDATE_RE = re.compile(
    r"operations?[-\s]+update|update[-\s]+on[-\s]+(?:the[-\s]+)?armed[-\s]+forces|press[-\s]+briefing"
    r"|defen[cs]e[-\s]+media[-\s]+operations|\btroops?\b|neutrali[sz]|\boperations?\b|terrorists?|insurgents?"
    r"|bandits?|kidnap|rescue|apprehend|arrest", re.I)


def _log(url: str, result: str, notes: str) -> None:
    log_access(SOURCE, url, result, f"v1.1 DHQ archived copies: {notes}")


# Index


def cdx_rows(fetcher, end: date) -> list[list[str]]:
    """All CDX rows (urlkey, original, timestamp, groupcount, endtimestamp) for the domain, paged with resume
    keys. Stops with what it has if a page fails."""
    params = {"url": DOMAIN_QUERY, "from": START.strftime("%Y%m%d"), "to": end.strftime("%Y%m%d"),
              "filter": ["statuscode:200", "mimetype:text/html"], "collapse": "urlkey", "output": "json",
              "fl": "urlkey,original,timestamp,groupcount,endtimestamp", "showGroupCount": "true",
              "lastSkipTimestamp": "true",
              "limit": PAGE_LIMIT, "showResumeKey": "true"}
    rows, page = [], 0
    while True:
        page += 1
        resp = fetcher.get(CDX_API, params)
        result = f"HTTP {resp.status_code}" if resp else fetcher.skip_reason
        _log(CDX_API, result, f"CDX page {page}, resume key {params.get('resumeKey', '-')}")
        if resp is None or resp.status_code != 200 or not resp.text.strip():
            break
        data = json.loads(resp.text)
        header, body = data[0], data[1:]
        resume = None
        # With showResumeKey the last two rows are an empty row and the key.
        if len(body) >= 2 and body[-2] == []:
            resume, body = body[-1][0], body[:-2]
        rows += [dict(zip(header, r)) for r in body if r]
        if not resume:
            break
        params = {**params, "resumeKey": resume}
    return rows


def index_table(rows: list[dict]) -> pd.DataFrame:
    """One row per URL key: original url, first and last capture timestamp, number of captures."""
    out = []
    for r in rows:
        first = r.get("timestamp", "")
        out.append({"original": r.get("original", ""), "first_timestamp": first,
                    "last_timestamp": r.get("endtimestamp") or first, "captures": int(r.get("groupcount") or 1)})
    df = pd.DataFrame(out, columns=INDEX_COLUMNS)
    return df.sort_values(["first_timestamp", "original"]).drop_duplicates("original").reset_index(drop=True)


# Post pages and candidates


def post_info(url: str) -> dict | None:
    """date (from the path) and slug of a post page, or None when the URL is not one."""
    parts = urlsplit(url if "://" in url else f"http://{url}")
    m = POST_PATH_RE.match(parts.path)
    if m:
        y, mo, d, slug = m.groups()
        return {"date": f"{y}-{mo}-{d}", "slug": slug} if f"{y}-{mo}-{d}" >= START.isoformat() else None
    if parts.path in ("", "/", "/index.php", "/index.php/") and "p" in parse_qs(parts.query):
        return {"date": "", "slug": ""}
    if parts.query:
        return None
    m = NEWS_PATH_RE.match(parts.path) or TOP_SLUG_RE.match(parts.path)
    slug = m.group(1).lower() if m else ""
    if m and slug not in SECTIONS and not slug.startswith(SECTION_SLUG_PREFIXES) and slug.count("-") >= SLUG_MIN_HYPHENS:
        return {"date": "", "slug": m.group(1)}
    return None


def post_pages(index: pd.DataFrame) -> pd.DataFrame:
    info = index["original"].map(post_info)
    pages = index[info.notna()].copy()
    pages["post_date"] = [i["date"] for i in info[info.notna()]]
    pages["slug"] = [i["slug"] for i in info[info.notna()]]
    return pages.reset_index(drop=True)


def slug_candidates(pages: pd.DataFrame) -> pd.DataFrame:
    """Dated post pages whose slug matches CANDIDATE_RE, and every ?p=ID page (title checked after fetch)."""
    keep = pages["slug"].str.replace("-", " ").str.contains(CANDIDATE_RE) | (pages["slug"] == "")
    return pages[keep].reset_index(drop=True)


def page_title_and_date(page_html: str) -> tuple[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    meta = soup.find("meta", property="og:title")
    heading = soup.find("h1")
    title = (meta.get("content") if meta else "") or (heading.get_text() if heading else "") or \
        (soup.title.get_text() if soup.title else "")
    published = soup.find("meta", property="article:published_time")
    when = soup.find("time")
    d = (published.get("content") if published else "") or (when.get("datetime") if when else "") or ""
    return " ".join(title.split()), d[:10]


def text_file(url: str):
    return TEXT_DIR / f"{cache_key(url)}.txt"


def fetch_candidates(fetcher, cands: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    rows, texts = [], {}
    for c in cands.to_dict("records"):
        no_slug = c["slug"] == ""
        snap = SNAPSHOT_URL.format(timestamp=c["first_timestamp"], url=c["original"])
        resp = fetcher.get(snap)
        status = f"HTTP {resp.status_code}" if resp else fetcher.skip_reason
        _log(snap, status, "earliest capture of a candidate post")
        row = {"url": c["original"], "post_date": c["post_date"], "title": "",
               "snapshot_timestamp": c["first_timestamp"], "snapshot_url": snap, "fetch_status": status}
        if resp is not None and resp.status_code == 200:
            title, page_date = page_title_and_date(resp.text)
            # ?p=ID pages had no slug to test: they stay only when the archived title is a candidate title.
            if no_slug and not CANDIDATE_RE.search(title):
                continue
            body = extract_body(resp.text)
            row |= {"title": title, "post_date": c["post_date"] or page_date}
            text_file(c["original"]).write_text(body, encoding="utf-8")
            texts[c["original"]] = body
        rows.append(row)
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS), texts


def wayback_matches(cands: pd.DataFrame, texts: dict[str, str], briefings: pd.DataFrame,
                    periods: pd.DataFrame | None) -> pd.DataFrame:
    fetched = cands[(cands["fetch_status"] == "HTTP 200") & (cands["post_date"] != "")]
    m = match(fetched.rename(columns={"post_date": "date"}), texts, briefings, periods)
    info = fetched.set_index("url")
    m["source"] = "wayback"
    m["snapshot_timestamp"] = m["post_url"].map(info["snapshot_timestamp"])
    m["title"] = m["post_url"].map(info["title"])
    return m[WAYBACK_MATCH_COLUMNS]


def run(fetcher=None, end: date | None = None, index_only: bool = False):
    fetcher = fetcher or Fetcher()
    end = end or date.today()
    allowed, status = fetcher.check_robots(CDX_API)
    _log("https://web.archive.org/robots.txt", f"robots.txt {status}", "check before the CDX query")
    if not allowed:
        raise RuntimeError(f"web.archive.org robots.txt {status}: CDX API not queried")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = index_table(cdx_rows(fetcher, end))
    index.to_csv(INDEX, index=False)
    pages = post_pages(index)
    cands = slug_candidates(pages)
    if index_only:
        return index, pages, cands, None, None
    fetched, texts = fetch_candidates(fetcher, cands)
    fetched.to_csv(CANDIDATES, index=False)
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    briefings = read(BRIEFINGS)
    matches = wayback_matches(fetched, texts, briefings, read(CHECK_BRIEFINGS) if CHECK_BRIEFINGS.exists() else None)
    matches.to_csv(MATCHES, index=False)
    return index, pages, fetched, matches, coverage_by_year(matches, briefings)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index-only", action="store_true", help="query the CDX index only; fetch no captures")
    args = parser.parse_args(argv)
    index, pages, cands, matches, cov = run(index_only=args.index_only)
    years = index["first_timestamp"].str[:4]
    print(f"archived URLs: {len(index)} ({years.value_counts().sort_index().to_dict()}); post pages: {len(pages)}; "
          f"candidates: {len(cands)}")
    if matches is not None:
        print(f"briefings with a matched archived DHQ statement: {len(matches)}")
        print(cov.to_string())


if __name__ == "__main__":
    main()
