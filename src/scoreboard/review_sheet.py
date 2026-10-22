"""Hand-review sheet for the full collection: every item the triage leaves undecided.

Usage: python -m scoreboard.review_sheet

Takes every item in outputs/tables/full_triage_<year>.csv whose decision is "uncertain" or "no text",
orders them by publication date, then outlet, then URL, and numbers them R0001 upward in batches of
BATCH_SIZE. Writes data/review/full_review_sheet.csv (blind: no triage decision, rule name or guard
flag) and data/review/full_review_batches.csv. It refuses to overwrite a sheet in which coding has begun.
"""

import argparse

import pandas as pd

from scoreboard.discover import TABLES_DIR
from scoreboard.triage_check import REVIEW_DIR, YEARS
from scoreboard.wirecheck import text_path

BATCH_SIZE = 60
REVIEW_DECISIONS = ("uncertain", "no text")
SHEET = REVIEW_DIR / "full_review_sheet.csv"
BATCHES = REVIEW_DIR / "full_review_batches.csv"
SHEET_COLUMNS = ["review_id", "batch", "year", "outlet", "date", "title", "url", "has_text", "text_path",
                 "is_operational_briefing", "notes"]
BATCH_COLUMNS = ["batch", "first_review_id", "last_review_id", "first_date", "last_date", "items"]


def review_items(tables_dir=TABLES_DIR, text_path=text_path) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        triage = pd.read_csv(tables_dir / f"full_triage_{year}.csv", keep_default_na=False, dtype=str)
        inv = pd.read_csv(tables_dir / f"full_inventory_{year}.csv", keep_default_na=False, dtype=str)
        picked = triage[triage["decision"].isin(REVIEW_DECISIONS)]
        frames.append(picked.merge(inv[["url", "title"]], on="url", validate="one_to_one").assign(year=year))
    items = pd.concat(frames, ignore_index=True).sort_values(["date", "outlet", "url"], ignore_index=True)
    paths = [text_path(u) for u in items["url"]]
    items["has_text"] = [p.exists() and p.stat().st_size > 0 for p in paths]
    items["text_path"] = [str(p) if has else "" for p, has in zip(paths, items["has_text"])]
    items["review_id"] = [f"R{i:04d}" for i in range(1, len(items) + 1)]
    items["batch"] = [f"B{i // BATCH_SIZE + 1:02d}" for i in range(len(items))]
    return items.assign(is_operational_briefing="", notes="")[SHEET_COLUMNS]


def batch_table(sheet: pd.DataFrame) -> pd.DataFrame:
    return (sheet.groupby("batch", sort=True)
            .agg(first_review_id=("review_id", "first"), last_review_id=("review_id", "last"),
                 first_date=("date", "first"), last_date=("date", "last"), items=("review_id", "size"))
            .reset_index()[BATCH_COLUMNS])


def build(tables_dir=TABLES_DIR, sheet=SHEET, batches=BATCHES, text_path=text_path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sheet.exists():
        coded = pd.read_csv(sheet, keep_default_na=False, dtype=str)
        if (coded["is_operational_briefing"] != "").any() or (coded["notes"] != "").any():
            raise RuntimeError(f"{sheet} has coding in it; not overwritten")
    items = review_items(tables_dir, text_path)
    table = batch_table(items)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    items.to_csv(sheet, index=False)
    table.to_csv(batches, index=False)
    return items, table


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    items, table = build()
    print(table.to_string(index=False))
    print(f"\ntotal items: {len(items)}; without text: {int((~items['has_text']).sum())}")
    print(items.groupby("year").size().to_string())


if __name__ == "__main__":
    main()
