"""Blind validation sample (docs/audit_rules.md, Validation): coding sheets without any extracted figure.

Usage: python -m scoreboard.validation_sample

Briefings: SAMPLE_SHARE of the confirmed briefings in data/briefings/full_briefings.csv, drawn at random
by briefing and stratified by briefing year. Each year gets SAMPLE_SHARE of its briefings; the shares are
rounded down and the remaining places go to the years with the largest remainders (ties to the earlier
year), so the total is SAMPLE_SHARE of all briefings, rounded. Within each year, in year order, briefings
are drawn without replacement with one numpy Generator seeded with SEED. data/validation/
blind_briefing_sheet.csv lists each sampled briefing's copy outlets and urls (data/review/
group_review_coded.csv, in date order) and blank columns for the author; no date, period, headline or
figure is included.

Auto-no items: SAMPLE_SHARE of the items with decided_by "auto_no" in data/review/full_classification.csv
(rounded), drawn without replacement with a fresh Generator seeded with SEED. data/validation/
blind_auto_no_sheet.csv gives an item_id (V001 upward in url order), outlet, url and headline (from
outputs/tables/full_inventory_<year>.csv) and blank code and notes columns; decided_by is not included.

Neither sheet is overwritten once the author has started coding it.
"""

import argparse

import numpy as np
import pandas as pd

from scoreboard.briefings import BRIEFINGS, GROUP_CODED
from scoreboard.config import PROJECT_ROOT
from scoreboard.discover import TABLES_DIR
from scoreboard.review_merge import CLASSIFICATION
from scoreboard.triage_check import YEARS

SEED = 20261024
SAMPLE_SHARE = 0.15
STRATUM = "year"
VALIDATION_DIR = PROJECT_ROOT / "data" / "validation"
BRIEFING_SHEET = VALIDATION_DIR / "blind_briefing_sheet.csv"
AUTO_NO_SHEET = VALIDATION_DIR / "blind_auto_no_sheet.csv"
OUTCOMES = ("neutralised", "arrested", "rescued")
BRIEFING_CODE_COLUMNS = [c for o in OUTCOMES for c in (o, f"{o}_qualifier", f"{o}_status")] + [
    "period_start", "period_end", "notes"]
BRIEFING_COLUMNS = ["briefing_id", "copy_outlets", "copy_urls", *BRIEFING_CODE_COLUMNS]
AUTO_NO_COLUMNS = ["item_id", "outlet", "url", "headline", "code", "notes"]


def allocate(counts: pd.Series, share: float = SAMPLE_SHARE) -> pd.Series:
    """Sample size per stratum: proportional, rounded down, remaining places by largest remainder."""
    exact = counts * share
    sizes = np.floor(exact).astype(int)
    extra = int(round(counts.sum() * share)) - sizes.sum()
    order = sorted(counts.index, key=lambda s: (-(exact[s] - sizes[s]), s))
    for s in order[:extra]:
        sizes[s] += 1
    return sizes


def draw_briefings(briefings: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    counts = briefings.groupby(STRATUM).size().sort_index()
    sizes = allocate(counts)
    picked = []
    for stratum, n in sizes.items():
        ids = sorted(briefings.loc[briefings[STRATUM] == stratum, "briefing_id"])
        picked += list(rng.choice(ids, size=n, replace=False))
    return briefings[briefings["briefing_id"].isin(picked)].sort_values("briefing_id", ignore_index=True)


def draw_auto_no(classification: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    items = classification[classification["decided_by"] == "auto_no"].sort_values("url", ignore_index=True)
    n = int(round(len(items) * SAMPLE_SHARE))
    return items.loc[sorted(rng.choice(len(items), size=n, replace=False))].reset_index(drop=True)


def briefing_sheet(sample: pd.DataFrame, coded: pd.DataFrame) -> pd.DataFrame:
    copies = coded[coded["confirmed_group_id"].isin(sample["briefing_id"])].sort_values(["date", "outlet", "url"])
    by_id = copies.groupby("confirmed_group_id")
    return pd.DataFrame({"briefing_id": sample["briefing_id"],
                         "copy_outlets": sample["briefing_id"].map(by_id["outlet"].agg("; ".join)),
                         "copy_urls": sample["briefing_id"].map(by_id["url"].agg("; ".join)),
                         **{c: "" for c in BRIEFING_CODE_COLUMNS}})[BRIEFING_COLUMNS]


def auto_no_sheet(sample: pd.DataFrame, titles: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"item_id": [f"V{i:03d}" for i in range(1, len(sample) + 1)], "outlet": sample["outlet"],
                         "url": sample["url"], "headline": sample["url"].map(titles).fillna(""),
                         "code": "", "notes": ""})[AUTO_NO_COLUMNS]


def write_blank(df: pd.DataFrame, path, coded_columns) -> None:
    if path.exists() and (pd.read_csv(path, keep_default_na=False, dtype=str)[list(coded_columns)] != "").any().any():
        raise RuntimeError(f"{path} has coding in it; not overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def build(briefings_path=BRIEFINGS, coded_path=GROUP_CODED, classification_path=CLASSIFICATION,
          tables_dir=TABLES_DIR, briefing_out=BRIEFING_SHEET, auto_no_out=AUTO_NO_SHEET):
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    briefings = draw_briefings(read(briefings_path))
    items = draw_auto_no(read(classification_path))
    titles = pd.concat([read(tables_dir / f"full_inventory_{y}.csv")[["url", "title"]] for y in YEARS])
    sheets = (briefing_sheet(briefings, read(coded_path)), auto_no_sheet(items, titles.set_index("url")["title"]))
    write_blank(sheets[0], briefing_out, BRIEFING_CODE_COLUMNS)
    write_blank(sheets[1], auto_no_out, ["code", "notes"])
    return briefings, items


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    briefings, items = build()
    # Counts only: the sample is coded blind.
    print("briefings drawn per year:", briefings.groupby(STRATUM).size().to_dict(), f"total {len(briefings)}")
    print("auto_no items drawn:", len(items))


if __name__ == "__main__":
    main()
