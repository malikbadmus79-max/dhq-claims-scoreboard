"""Wire-copy check on the pilot inventory and preparation of the hand-review sheet.

Usage: python -m scoreboard.wirecheck --year 2024

Article pages are fetched once through the polite fetcher; body text is written
only to data_raw/text/. Outputs hold URLs, flags and similarity scores, never
body or excerpt text.
"""

import argparse
import json
import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from urllib.parse import urlsplit

import pandas as pd
from bs4 import BeautifulSoup

from scoreboard.access_log import log_access
from scoreboard.config import PROJECT_ROOT, load_config
from scoreboard.discover import BUBA, DHQ_RE, TABLES_DIR, clean_html
from scoreboard.fetch import DEFAULT_CACHE_DIR, Fetcher, cache_key

log = logging.getLogger(__name__)

TEXT_DIR = PROJECT_ROOT / "data_raw" / "text"
REVIEW_DIR = PROJECT_ROOT / "data" / "review"
_WIRE_CONFIG = load_config()["wire_copy"]
SAME_WIRE_THRESHOLD = float(_WIRE_CONFIG["same_wire_threshold"])
SENSITIVITY_THRESHOLDS = [float(t) for t in _WIRE_CONFIG["sensitivity_thresholds"]]
HAND_COLUMNS = ["is_operational_briefing", "confirmed_group_id", "headline_body_check", "notes"]
OTHER_AGENCY_RE = re.compile(
    r"\bNDLEA\b|\bEFCC\b|\bpolice\b|\bcustoms\b|\bNSCDC\b|\bimmigration\b|\bnavy\b|\bnaval\b|\bair force\b|\bNAF\b",
    re.I,
)
DHQ_NAME_RE = re.compile(rf"\bDHQ\b|defen[cs]e headquarters|{BUBA}", re.I)
NGRAM = 5
SUGGESTED_GROUP_WINDOW_DAYS = 2
MIN_BODY_WORDS = 80
MAX_CONSECUTIVE_FAILURES = 3

BODY_SELECTORS = [
    "[itemprop=articleBody]",
    "div.single-body",
    "div.entry-content",
    "div.td-post-content",
    "div.post-content",
    "div.article-content",
    "div.single-post-content",
    "article",
]
STRIP_TAGS = ["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "figure"]
NAN_RE = re.compile(r"News Agency of Nigeria|\(NAN\)")
WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
TYPE_RULES = [
    ("fortnightly", re.compile(r"\btwo weeks\b|\b2 weeks\b|\bfortnight", re.I)),
    ("weekly", re.compile(r"\bone week\b|\b1 week\b|\ba week\b|\b(?:last|past) week\b", re.I)),
    ("monthly", re.compile(rf"\b(?:in|month of|during) (?:{MONTHS})\b", re.I)),
    ("annual or year-end", re.compile(r"\b2024\b|\bthis year\b", re.I)),
]
SAME_WIRE_COMMENT = (
    f"# same_wire = similarity >= {SAME_WIRE_THRESHOLD} "
    f"(word {NGRAM}-gram Jaccard on body text with digits removed); threshold to be reviewed by hand"
)


# Text extraction and similarity


def extract_body(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    for selector in BODY_SELECTORS:
        el = soup.select_one(selector)
        if el is not None:
            text = _paragraph_text(el)
            if len(text.split()) >= MIN_BODY_WORDS:
                return text
    # Fallback: the element whose direct <p> children hold the most words.
    best, best_words = "", 0
    for parent in {p.parent for p in soup.find_all("p")}:
        text = " ".join(p.get_text(" ", strip=True) for p in parent.find_all("p", recursive=False))
        if len(text.split()) > best_words:
            best, best_words = text, len(text.split())
    return best


def _paragraph_text(el) -> str:
    paragraphs = [p.get_text(" ", strip=True) for p in el.find_all("p")]
    text = " ".join(p for p in paragraphs if p)
    if len(text.split()) < MIN_BODY_WORDS:
        text = el.get_text(" ", strip=True)
    return " ".join(text.split())


def ngrams(text: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    words = WORD_RE.findall(re.sub(r"\d", " ", text.lower()))
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def similarity(a: str, b: str, n: int = NGRAM) -> float:
    """Word n-gram Jaccard similarity with all digits removed."""
    ga, gb = ngrams(a, n), ngrams(b, n)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def is_challenge_page(page_html: str) -> bool:
    return "slowAES" in page_html or ("<p" not in page_html and "<script" in page_html and len(page_html) < 5000)


def has_nan_credit(text: str) -> bool:
    return bool(NAN_RE.search(text))


# Grouping


class UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)

    def components(self) -> int:
        return len({self.find(i) for i in self.parent})


def independent_copies(urls: list[str], same_wire_pairs: list[tuple[str, str]],
                       nan_credited: list[str] | None = None) -> int:
    """Number of copies once copies linked by same_wire count as one. Copies listed in
    nan_credited (credited to the News Agency of Nigeria) also count as one source together."""
    uf = UnionFind(urls)
    for a, b in same_wire_pairs:
        uf.union(a, b)
    nan_credited = nan_credited or []
    for a, b in zip(nan_credited, nan_credited[1:]):
        uf.union(a, b)
    return uf.components()


def suggested_type(title: str) -> str:
    for label, pattern in TYPE_RULES:
        if pattern.search(title):
            return label
    return ""


def suggested_groups(df: pd.DataFrame, year: int) -> pd.Series:
    """Join items within 2 days that share a suggested_type and name DHQ in the title
    or matched on the excerpt. Headline figures are ignored."""
    eligible = df["suggested_type"].ne("") & (
        df["title"].str.contains(DHQ_RE) | df["matched_field"].isin(["excerpt", "both"])
    )
    dates = pd.to_datetime(df["publish_date"])
    uf = UnionFind(list(df.index))
    idx = list(df.index)
    for i, j in combinations(idx, 2):
        if (
            eligible[i]
            and eligible[j]
            and df.at[i, "suggested_type"] == df.at[j, "suggested_type"]
            and abs((dates[i] - dates[j]).days) <= SUGGESTED_GROUP_WINDOW_DAYS
        ):
            uf.union(i, j)
    roots = {i: uf.find(i) for i in idx}
    first = {}
    for i, r in roots.items():
        first[r] = min(first.get(r, dates[i]), dates[i])
    order = sorted(first, key=lambda r: (first[r], r))
    ids = {r: f"S{year}-{n:03d}" for n, r in enumerate(order, start=1)}
    return pd.Series([ids[roots[i]] for i in idx], index=df.index)


# Pipeline


def text_path(url: str):
    return TEXT_DIR / f"{cache_key(url)}.txt"


def fetch_bodies(urls: list[str], make_fetcher=Fetcher) -> pd.DataFrame:
    """Fetch article bodies with one worker and one fetcher per domain, so each
    domain keeps its own delay while domains proceed in parallel."""
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    by_domain = defaultdict(list)
    for url in urls:
        by_domain[urlsplit(url).netloc].append(url)
    with ThreadPoolExecutor(max_workers=len(by_domain) or 1) as pool:
        results = pool.map(lambda domain_urls: _fetch_domain(domain_urls, make_fetcher()), by_domain.values())
        rows = [row for domain_rows in results for row in domain_rows]
    return pd.DataFrame(rows, columns=["url", "fetch_status", "body"]).set_index("url")


def _fetch_domain(urls: list[str], fetcher: Fetcher) -> list[dict]:
    rows, consecutive_failures = [], 0
    for url in urls:
        path = text_path(url)
        if path.exists():
            body = path.read_text(encoding="utf-8")
            rows.append({"url": url, "fetch_status": "ok (text cached)", "body": body})
            continue
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            rows.append({"url": url, "fetch_status": "skipped after repeated failures", "body": ""})
            continue
        resp = fetcher.get(url)
        if resp is None or resp.status_code >= 500:
            consecutive_failures += 1
        else:
            consecutive_failures = 0
        if consecutive_failures == MAX_CONSECUTIVE_FAILURES:
            log.warning("%s: %d failures in a row; skipping its remaining pages", urlsplit(url).netloc, consecutive_failures)
        if resp is None:
            rows.append({"url": url, "fetch_status": fetcher.skip_reason or "failed", "body": ""})
            continue
        if resp.status_code != 200:
            rows.append({"url": url, "fetch_status": f"HTTP {resp.status_code}", "body": ""})
            continue
        if is_challenge_page(resp.text):
            # Bot-protection pages are recorded, not solved, and are not kept in the cache.
            fetcher.forget(resp.url)
            rows.append({"url": url, "fetch_status": "JS challenge page", "body": ""})
            continue
        body = extract_body(resp.text)
        if not body:
            rows.append({"url": url, "fetch_status": "no body extracted", "body": ""})
            continue
        path.write_text(body, encoding="utf-8")
        rows.append({"url": url, "fetch_status": "ok", "body": body})
    return rows


def sensitivity_column(threshold: float) -> str:
    return f"independent_copies_{round(threshold * 100):03d}"


def compare_groups(inventory: pd.DataFrame, bodies: pd.Series, threshold: float = SAME_WIRE_THRESHOLD,
                   sensitivity: list[float] = SENSITIVITY_THRESHOLDS):
    """Pairwise similarity within each provisional group, and independent copies at the
    primary threshold, with the NAN merge added (strict), and at each sensitivity threshold."""
    nan = {u: has_nan_credit(bodies[u]) for u in inventory["url"]}
    pair_rows, group_rows = [], []
    for gid, grp in inventory.groupby("briefing_group_id", sort=True):
        urls = list(grp["url"])
        scored = []
        for a, b in combinations(urls, 2):
            if not bodies[a] or not bodies[b]:
                sim = None
            else:
                sim = round(similarity(bodies[a], bodies[b]), 3)
                scored.append((a, b, sim))
            pair_rows.append(
                {
                    "briefing_group_id": gid,
                    "url_a": a,
                    "url_b": b,
                    "similarity": sim,
                    "same_wire": sim is not None and sim >= threshold,
                }
            )
        row = {
            "briefing_group_id": gid,
            "copies": len(urls),
            "outlets": grp["outlet"].nunique(),
            "copies_with_text": sum(bool(bodies[u]) for u in urls),
            "max_similarity": max((s for _, _, s in scored), default=None),
            "independent_copies": independent_copies(urls, [(a, b) for a, b, s in scored if s >= threshold]),
            "independent_copies_strict": independent_copies(
                urls, [(a, b) for a, b, s in scored if s >= threshold], [u for u in urls if nan[u]]
            ),
        }
        for t in sensitivity:
            row[sensitivity_column(t)] = independent_copies(urls, [(a, b) for a, b, s in scored if s >= t])
        group_rows.append(row)
    pairs = pd.DataFrame(
        pair_rows, columns=["briefing_group_id", "url_a", "url_b", "similarity", "same_wire"]
    )
    return pairs, pd.DataFrame(group_rows)


def likely_off_topic(title: str, excerpt: str = "") -> bool:
    """Another agency is named and DHQ, Defence Headquarters or Buba is not."""
    text = f"{title} {excerpt}"
    return bool(OTHER_AGENCY_RE.search(text)) and not DHQ_NAME_RE.search(text)


def load_cached_excerpts(cache_dir=DEFAULT_CACHE_DIR) -> dict[str, str]:
    """Excerpts from cached discovery search responses, held in memory only."""
    excerpts = {}
    for path in cache_dir.glob("*.json"):
        raw = path.read_text(encoding="utf-8")
        head = raw[:600]
        if "/wp-json/wp/v2/posts?" not in head or "search=" not in head or "excerpt" not in head:
            continue
        data = json.loads(raw)
        if data.get("status_code") != 200:
            continue
        try:
            posts = json.loads(data["text"])
        except ValueError:
            continue
        for post in posts if isinstance(posts, list) else []:
            if post.get("link"):
                excerpts[post["link"]] = clean_html(post.get("excerpt", {}).get("rendered", ""))
    return excerpts


REVIEW_COLUMNS = [
    "briefing_group_id",
    "outlet",
    "publish_date",
    "title",
    "url",
    "nan_credit",
    "max_similarity_in_group",
    "independent_copies",
    "independent_copies_strict",
    "likely_off_topic",
    "suggested_type",
    "suggested_group",
    *HAND_COLUMNS,
]


def build_review(inventory: pd.DataFrame, items: pd.DataFrame, groups: pd.DataFrame, year: int,
                 excerpts: dict[str, str] | None = None, previous: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per inventory item. Hand-review entries in `previous` are kept by URL."""
    excerpts = excerpts or {}
    by_group = groups.set_index("briefing_group_id")
    df = inventory.copy()
    df["nan_credit"] = df["url"].map(items.set_index("url")["nan_credit"])
    df["max_similarity_in_group"] = df["briefing_group_id"].map(by_group["max_similarity"])
    df["independent_copies"] = df["briefing_group_id"].map(by_group["independent_copies"])
    df["independent_copies_strict"] = df["briefing_group_id"].map(by_group["independent_copies_strict"])
    df["likely_off_topic"] = [likely_off_topic(t, excerpts.get(u, "")) for t, u in zip(df["title"], df["url"])]
    df["suggested_type"] = df["title"].map(suggested_type)
    df["suggested_group"] = suggested_groups(df, year)
    for col in HAND_COLUMNS:
        kept = previous.set_index("url")[col] if previous is not None and col in previous else pd.Series(dtype=str)
        df[col] = df["url"].map(kept).fillna("")
    return df.sort_values(["publish_date", "briefing_group_id"], kind="stable")[REVIEW_COLUMNS].reset_index(drop=True)


def write_outputs(pairs, items, groups, review, year, tables_dir=TABLES_DIR, review_dir=REVIEW_DIR):
    tables_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    with open(tables_dir / f"pilot_copy_similarity_{year}.csv", "w", newline="", encoding="utf-8") as f:
        f.write(SAME_WIRE_COMMENT + "\n")
        pairs.to_csv(f, index=False)
    items.to_csv(tables_dir / f"pilot_item_checks_{year}.csv", index=False)
    groups.to_csv(tables_dir / f"pilot_copy_groups_{year}.csv", index=False)
    review.to_csv(review_dir / f"pilot_review_{year}.csv", index=False)


def summarise(pairs, items, groups, review) -> str:
    lines = [SAME_WIRE_COMMENT.lstrip("# "), ""]
    lines += ["Article fetch status", items["fetch_status"].value_counts().to_string(), ""]
    types = review["suggested_type"].replace("", "(blank)").value_counts()
    lines += ["suggested_type", types.to_string(), ""]
    lines += [
        f"Provisional groups: {review['briefing_group_id'].nunique()}",
        f"Suggested groups: {review['suggested_group'].nunique()}",
        "",
    ]
    sims = pairs["similarity"].dropna()
    bands = pd.cut(sims, [i / 10 for i in range(11)], include_lowest=True, right=False)
    band_counts = bands.value_counts().sort_index()
    band_counts.index = [f"{iv.left:.1f}-{iv.right:.1f}" for iv in band_counts.index]
    if (sims == 1.0).any():
        band_counts.iloc[-1] += int((sims == 1.0).sum())
    lines += [
        f"Pairs compared: {len(pairs)} ({pairs['similarity'].isna().sum()} without text on one side)",
        "Pair similarity by band (0.9-1.0 includes 1.0)",
        band_counts.to_string(),
        f"same_wire pairs: {int(pairs['same_wire'].sum())}",
        "",
    ]
    lines += [f"Groups with 2+ copies: {(groups['copies'] >= 2).sum()}"]
    lines += ["Groups with 2+ independent copies after wire merge, by threshold"]
    for t in [SAME_WIRE_THRESHOLD, *SENSITIVITY_THRESHOLDS]:
        col = "independent_copies" if t == SAME_WIRE_THRESHOLD else sensitivity_column(t)
        label = " (primary)" if t == SAME_WIRE_THRESHOLD else ""
        lines += [f"  {t:.2f}{label}: {(groups[col] >= 2).sum()}"]
    lines += [f"  {SAME_WIRE_THRESHOLD:.2f} plus NAN merge (strict): {(groups['independent_copies_strict'] >= 2).sum()}"]
    lines += [
        f"Items with nan_credit: {int(items['nan_credit'].sum())} of {len(items)}",
        f"Items flagged likely_off_topic: {int(review['likely_off_topic'].sum())}",
    ]
    return "\n".join(lines)


ITEM_COLUMNS = [
    "url",
    "outlet",
    "briefing_group_id",
    "fetch_status",
    "api_status",
    "text_source",
    "body_words",
    "nan_credit",
]


def load_bodies(urls) -> pd.Series:
    return pd.Series(
        {u: text_path(u).read_text(encoding="utf-8") if text_path(u).exists() else "" for u in urls}
    )


def item_checks_path(year: int, tables_dir=TABLES_DIR):
    return tables_dir / f"pilot_item_checks_{year}.csv"


def read_item_checks(year: int, tables_dir=TABLES_DIR) -> pd.DataFrame:
    items = pd.read_csv(item_checks_path(year, tables_dir), keep_default_na=False)
    for col in ITEM_COLUMNS:
        if col not in items:
            items[col] = ""
    return items


def analyse(inventory: pd.DataFrame, items: pd.DataFrame, year: int, **dirs):
    """Similarity, wire merge and review sheet from the text stored in data_raw/text/."""
    bodies = load_bodies(inventory["url"])
    # Item rows follow the current inventory: dropped items leave, group IDs are refreshed.
    items = inventory[["url", "outlet", "briefing_group_id"]].merge(
        items.drop(columns=["outlet", "briefing_group_id"], errors="ignore"), on="url", how="left"
    ).fillna("")
    items["body_words"] = items["url"].map(lambda u: len(bodies[u].split()))
    items["nan_credit"] = items["url"].map(lambda u: has_nan_credit(bodies[u]))
    items = items[ITEM_COLUMNS]
    pairs, groups = compare_groups(inventory, bodies)
    review_path = dirs.get("review_dir", REVIEW_DIR) / f"pilot_review_{year}.csv"
    previous = pd.read_csv(review_path, keep_default_na=False, dtype=str) if review_path.exists() else None
    review = build_review(inventory, items, groups, year, excerpts=load_cached_excerpts(), previous=previous)
    write_outputs(pairs, items, groups, review, year, **dirs)
    return pairs, items, groups, review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--no-fetch", action="store_true", help="rerun the analysis on stored text without any requests"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    inventory = pd.read_csv(TABLES_DIR / f"pilot_inventory_{args.year}.csv", keep_default_na=False)
    if args.no_fetch:
        pairs, items, groups, review = analyse(inventory, read_item_checks(args.year), args.year)
        print(summarise(pairs, items, groups, review))
        return

    previous = (
        read_item_checks(args.year).set_index("url")
        if item_checks_path(args.year).exists()
        else pd.DataFrame(columns=ITEM_COLUMNS).set_index("url")
    )
    fetched = fetch_bodies(list(inventory["url"]))
    items = inventory[["url", "outlet", "briefing_group_id"]].copy()
    items["fetch_status"] = items["url"].map(fetched["fetch_status"])
    items["api_status"] = items["url"].map(previous["api_status"]).fillna("")

    def source(row):
        if row.fetch_status == "ok":
            return "article page"
        if row.fetch_status == "ok (text cached)":
            return previous["text_source"].get(row.url) or "article page"
        return ""

    items["text_source"] = [source(r) for r in items.itertuples()]
    pairs, items, groups, review = analyse(inventory, items, args.year)

    for domain, grp in items.groupby(items["url"].map(lambda u: urlsplit(u).netloc)):
        ok = grp["fetch_status"].str.startswith("ok").sum()
        failed = grp.loc[~grp["fetch_status"].str.startswith("ok"), "fetch_status"]
        log_access(
            domain,
            grp["url"].iloc[0],
            f"{ok} of {len(grp)} article pages fetched",
            f"Wire-copy check {args.year}" + (f"; failures: {failed.value_counts().to_dict()}" if len(failed) else ""),
        )
    print(summarise(pairs, items, groups, review))


if __name__ == "__main__":
    main()
