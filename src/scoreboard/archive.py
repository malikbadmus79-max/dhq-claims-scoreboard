"""Archive URLs for confirmed briefings, from the Wayback Machine availability API.

Usage: python -m scoreboard.archive --year 2024

Runs only on items coded is_operational_briefing = yes in the review file for the year
(data/review/review_<year>.csv, or pilot_review_<year>.csv for the pilot year). For each item
the snapshot closest to its publication date is recorded; snapshots are never downloaded.
Requests go through the polite fetcher (robots.txt, configured delay and user agent). Failed
lookups are logged in docs/source_access_log.csv.

Writes outputs/tables/archive_urls_<year>.csv: confirmed_group_id, outlet, url, publish_date,
archive_url, archive_timestamp, lookup_status. Both archive fields are blank when no snapshot
exists or the lookup fails.
"""

import argparse
import logging

import pandas as pd

from scoreboard.access_log import log_access
from scoreboard.discover import TABLES_DIR
from scoreboard.fetch import Fetcher
from scoreboard.wirecheck import REVIEW_DIR

log = logging.getLogger(__name__)

WAYBACK_API = "https://archive.org/wayback/available"
ARCHIVE_COLUMNS = ["confirmed_group_id", "outlet", "url", "publish_date", "archive_url", "archive_timestamp",
                   "lookup_status"]


def review_path(year: int, review_dir=REVIEW_DIR):
    for name in (f"review_{year}.csv", f"pilot_review_{year}.csv"):
        if (review_dir / name).exists():
            return review_dir / name
    raise FileNotFoundError(f"no review file for {year} in {review_dir}")


def confirmed_briefings(review: pd.DataFrame) -> pd.DataFrame:
    return review[review["is_operational_briefing"] == "yes"].reset_index(drop=True)


def lookup_archive(fetcher: Fetcher, url: str, publish_date: str) -> tuple[str, str, str]:
    """(archive_url, archive_timestamp, status) of the snapshot closest to the publication date.
    Blank URL and timestamp when there is none or the lookup fails."""
    resp = fetcher.get(WAYBACK_API, params={"url": url, "timestamp": publish_date.replace("-", "")})
    if resp is None:
        return "", "", fetcher.skip_reason or "request failed"
    if resp.status_code != 200:
        return "", "", f"HTTP {resp.status_code}"
    try:
        closest = resp.json().get("archived_snapshots", {}).get("closest") or {}
    except (ValueError, AttributeError):
        return "", "", "non-JSON response"
    if not closest.get("available") or not closest.get("url"):
        return "", "", "no snapshot"
    return closest["url"], closest.get("timestamp", ""), "ok"


def archive_items(items: pd.DataFrame, fetcher: Fetcher, year: int) -> pd.DataFrame:
    rows = []
    for n, item in enumerate(items.itertuples(), start=1):
        archive_url, stamp, status = lookup_archive(fetcher, item.url, item.publish_date)
        if status not in ("ok", "no snapshot"):
            log_access("archive.org", f"{WAYBACK_API}?url={item.url}", status,
                       f"Archive lookup {year}: Wayback availability lookup failed")
        rows.append({
            "confirmed_group_id": item.confirmed_group_id,
            "outlet": item.outlet,
            "url": item.url,
            "publish_date": item.publish_date,
            "archive_url": archive_url,
            "archive_timestamp": stamp,
            "lookup_status": status,
        })
        if n % 50 == 0:
            log.info("archive lookups: %d of %d", n, len(items))
    out = pd.DataFrame(rows, columns=ARCHIVE_COLUMNS)
    counts = out["lookup_status"].value_counts().to_dict()
    log_access("archive.org", f"{WAYBACK_API}?url=<briefing copy>&timestamp=<publish date>",
               f"{counts.get('ok', 0)} of {len(out)} confirmed briefing copies have a snapshot",
               f"Archive lookup {year}; statuses: {counts}")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    review = pd.read_csv(review_path(args.year), keep_default_na=False, dtype=str)
    out = archive_items(confirmed_briefings(review), Fetcher(), args.year)
    out.to_csv(TABLES_DIR / f"archive_urls_{args.year}.csv", index=False)
    print(out["lookup_status"].value_counts().to_string())


if __name__ == "__main__":
    main()
