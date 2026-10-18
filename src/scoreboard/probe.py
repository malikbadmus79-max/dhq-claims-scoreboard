"""Source access check for candidate outlets.

Usage: python -m scoreboard.probe --start 2024-03-01 --end 2024-03-31 dailytrust.com punchng.com ...

For each domain: robots.txt for the REST API path and for an article path, a REST API probe
and, when the API answers, one search for "Defence Headquarters" inside the date window. Every
attempt is logged to docs/source_access_log.csv. Requests go through the polite fetcher
(robots.txt, configured delay and user agent). Titles and excerpts are held in memory for
the candidate filter only; titles and dates of candidates are returned, not written.
"""

import argparse
import logging
from datetime import date

from scoreboard.access_log import log_access
from scoreboard.discover import FIELDS, PER_PAGE, clean_html, is_candidate, probe_api
from scoreboard.fetch import Fetcher

log = logging.getLogger(__name__)

TEST_TERM = "Defence Headquarters"
MAX_TEST_PAGES = 5


def probe_domain(fetcher: Fetcher, domain: str, start: date, end: date) -> dict:
    api_url = f"https://{domain}/wp-json/wp/v2/posts"
    api_ok, robots_status = fetcher.check_robots(api_url)
    log_access(domain, f"https://{domain}/robots.txt", f"robots.txt {robots_status}",
               f"Source access check; /wp-json/wp/v2/posts {'allowed' if api_ok else 'disallowed'}")
    row = {"outlet": domain, "robots": robots_status, "robots_api": "allowed" if api_ok else "disallowed",
           "robots_article": "", "api": "", "hits": "", "candidates": "", "candidate_items": []}

    api = probe_api(fetcher, domain)
    row["api"] = api
    log_access(domain, f"{api_url}?per_page=1", api if api != "yes" else "HTTP 200, API answers",
               "Source access check; REST API probe")
    if api != "yes":
        article_ok, _ = fetcher.check_robots(f"https://{domain}/")
        row["robots_article"] = "allowed" if article_ok else "disallowed"
        return row

    items, total, page, pages = [], None, 1, 1
    while page <= min(pages, MAX_TEST_PAGES):
        params = {"search": TEST_TERM, "after": f"{start.isoformat()}T00:00:00",
                  "before": f"{end.isoformat()}T23:59:59", "per_page": PER_PAGE, "page": page, "_fields": FIELDS}
        resp = fetcher.get(api_url, params=params)
        if resp is None or resp.status_code != 200:
            reason = fetcher.skip_reason if resp is None else f"HTTP {resp.status_code}"
            log_access(domain, f"{api_url}?search={TEST_TERM}&after={start}&before={end}&page={page}", reason,
                       "Source access check; test search")
            break
        headers = {k.lower(): v for k, v in resp.headers.items()}
        total = int(headers.get("x-wp-total", 0) or 0) if total is None else total
        posts = resp.json() if resp.text.strip().startswith("[") else []
        # Some sites send X-WP-Total 0 with a full page of posts; then page on while pages are full.
        header_pages = int(headers.get("x-wp-totalpages", 0) or 0)
        pages = header_pages if header_pages else (page + 1 if len(posts) == PER_PAGE else page)
        for post in posts:
            title = clean_html(post.get("title", {}).get("rendered", ""))
            excerpt = clean_html(post.get("excerpt", {}).get("rendered", ""))
            items.append({"date": post.get("date", "")[:10], "title": title, "link": post.get("link", ""),
                          "candidate": is_candidate(title, excerpt)})
        page += 1
    if total is not None:
        candidates = [i for i in items if i["candidate"]]
        header_ok = total > 0 or not items
        hits = total if header_ok else len(items)
        row.update(hits=hits, candidates=len(candidates), candidate_items=candidates,
                   hits_basis="X-WP-Total" if header_ok else "posts returned (X-WP-Total sent as 0)")
        log_access(domain, f"{api_url}?search={TEST_TERM.replace(' ', '+')}&after={start}&before={end}",
                   f"HTTP 200, X-WP-Total {total}" + ("" if header_ok else f", {hits} posts returned"),
                   f"Source access check; test search {start} to {end}; {len(candidates)} pass the candidate filter"
                   + ("" if header_ok else "; X-WP-Total header unreliable, hit count is posts returned"))
    article = next((i["link"] for i in items if i["link"]), f"https://{domain}/")
    article_ok, _ = fetcher.check_robots(article)
    row["robots_article"] = "allowed" if article_ok else "disallowed"
    return row


WAYBACK_TEST_URL = "https://blueprint.ng/how-nigeria-military-neutralised-43-terrorists-arrested-115-official/"


def retry_failed_sources(fetcher: Fetcher) -> list[dict]:
    """One retry each of defencehq.mil.ng (robots.txt) and the Wayback Machine (robots.txt and
    one availability query for a pilot URL)."""
    rows = []
    ok, status = fetcher.check_robots("https://defencehq.mil.ng/")
    rows.append({"source": "defencehq.mil.ng", "test": "robots.txt", "result": status,
                 "allowed": ok})
    log_access("defencehq.mil.ng", "https://defencehq.mil.ng/robots.txt", f"robots.txt {status}",
               f"Retry before full collection; site {'allowed' if ok else 'skipped'}")
    ok, status = fetcher.check_robots("https://web.archive.org/web/")
    rows.append({"source": "web.archive.org", "test": "robots.txt", "result": status, "allowed": ok})
    log_access("web.archive.org", "https://web.archive.org/robots.txt", f"robots.txt {status}",
               f"Retry before full collection; /web/ {'allowed' if ok else 'disallowed'}")
    resp = fetcher.get("https://archive.org/wayback/available", params={"url": WAYBACK_TEST_URL})
    if resp is None:
        result = fetcher.skip_reason or "request failed"
    else:
        result = f"HTTP {resp.status_code}"
        if resp.status_code == 200:
            try:
                snap = resp.json().get("archived_snapshots", {}).get("closest")
                result += f", snapshot {'found ' + snap.get('timestamp', '') if snap else 'not found'}"
            except ValueError:
                result += ", non-JSON"
    rows.append({"source": "archive.org", "test": "wayback availability", "result": result, "allowed": resp is not None})
    log_access("archive.org", f"https://archive.org/wayback/available?url={WAYBACK_TEST_URL}", result,
               "Retry before full collection; availability API for one pilot URL")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--retry-failed", action="store_true",
                        help="retry defencehq.mil.ng and the Wayback Machine once instead of probing domains")
    parser.add_argument("domains", nargs="*")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    fetcher = Fetcher()
    if args.retry_failed:
        for row in retry_failed_sources(fetcher):
            print("RETRY", row)
        return
    if not (args.start and args.end and args.domains):
        parser.error("--start, --end and at least one domain are required")
    for domain in args.domains:
        row = probe_domain(fetcher, domain, args.start, args.end)
        print("ROW", {k: v for k, v in row.items() if k != "candidate_items"})
        for item in row["candidate_items"]:
            print("CAND", domain, item["date"], item["title"])


if __name__ == "__main__":
    main()
