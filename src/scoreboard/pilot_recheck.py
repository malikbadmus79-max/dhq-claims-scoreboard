"""Recheck sheet for the 230 pilot items against the full-review conventions in docs/review_guide.md.

Usage: python -m scoreboard.pilot_recheck

Takes every item in data/review/pilot_review_2024.csv, orders them by publication date, then outlet, then
URL, and numbers them P001 upward in one batch P01. Writes data/review/pilot_recheck_sheet.csv in the
column layout of data/review/full_review_sheet.csv, with the existing pilot label and notes in pilot_code
and pilot_notes. The pilot file is only read; no pilot label changes. It refuses to overwrite a sheet in
which recheck coding has begun.
"""

import argparse

import pandas as pd

from scoreboard.review_sheet import SHEET_COLUMNS
from scoreboard.triage import PILOT_REVIEW
from scoreboard.triage_check import REVIEW_DIR
from scoreboard.wirecheck import text_path

BATCH = "P01"
RECHECK_SHEET = REVIEW_DIR / "pilot_recheck_sheet.csv"
RECHECK_COLUMNS = SHEET_COLUMNS + ["pilot_code", "pilot_notes"]


def recheck_items(pilot_path=PILOT_REVIEW, text_path=text_path) -> pd.DataFrame:
    pilot = pd.read_csv(pilot_path, keep_default_na=False, dtype=str)
    items = (pilot.rename(columns={"publish_date": "date", "is_operational_briefing": "pilot_code", "notes": "pilot_notes"})
             .sort_values(["date", "outlet", "url"], ignore_index=True))
    paths = [text_path(u) for u in items["url"]]
    items["has_text"] = [p.exists() and p.stat().st_size > 0 for p in paths]
    items["text_path"] = [str(p) if has else "" for p, has in zip(paths, items["has_text"])]
    items["review_id"] = [f"P{i:03d}" for i in range(1, len(items) + 1)]
    items["year"] = items["date"].str[:4]
    return items.assign(batch=BATCH, is_operational_briefing="", notes="")[RECHECK_COLUMNS]


def build(pilot_path=PILOT_REVIEW, sheet=RECHECK_SHEET, text_path=text_path) -> pd.DataFrame:
    if sheet.exists():
        coded = pd.read_csv(sheet, keep_default_na=False, dtype=str)
        if (coded["is_operational_briefing"] != "").any() or (coded["notes"] != "").any():
            raise RuntimeError(f"{sheet} has coding in it; not overwritten")
    items = recheck_items(pilot_path, text_path)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    items.to_csv(sheet, index=False)
    return items


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    items = build()
    print(f"items: {len(items)}; without text: {int((~items['has_text']).sum())}; "
          f"{items['review_id'].iloc[0]} {items['date'].iloc[0]} to {items['review_id'].iloc[-1]} {items['date'].iloc[-1]}")
    print(items["pilot_code"].value_counts().to_string())


if __name__ == "__main__":
    main()
