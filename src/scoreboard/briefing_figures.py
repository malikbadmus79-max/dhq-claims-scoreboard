"""Briefing figures from the national-marker body values of each briefing's copies.

Usage: python -m scoreboard.briefing_figures

Reads data/review/extraction_sheet_v2.csv and writes data/briefings/briefing_figures.csv, one row per
briefing and outcome. Only body values found by the national-marker rule (body_<outcome>_rule
"national marker", with a number) are used; each item is one copy. Per briefing and outcome:
- value: the most common national-marker value, with qualifier the most common qualifier among the
  copies giving it (on a tie, that of the first such copy in sheet order); blank when two or more values
  tie for most common.
- copies_with_value: copies giving that value (in a tie, the copies giving each tied value).
- copies_other: copies giving a different national-marker value; other_values lists those values with
  their copy counts (in a tie, every value), most copies first, then ascending value.
- status: "agreed" when all national-marker copies give one value, "majority" when one value is most
  common, "conflict" when values tie, "needs hand extraction" when no copy has a national-marker value.
"""

import argparse

import pandas as pd

from scoreboard.briefings import BRIEFINGS
from scoreboard.extract import OUTCOMES
from scoreboard.extraction_sheet import EXTRACTION_SHEET

BRIEFING_FIGURES = BRIEFINGS.parent / "briefing_figures.csv"
NATIONAL_RULE = "national marker"
STATUSES = ("agreed", "majority", "conflict", "needs hand extraction")
FIGURE_COLUMNS = ["briefing_id", "outcome", "value", "qualifier", "copies_with_value", "copies_other", "other_values",
                  "national_copies", "items", "status"]


def outcome_row(briefing_id: str, outcome: str, items: pd.DataFrame) -> dict:
    national = items[(items[f"body_{outcome}_rule"] == NATIONAL_RULE) & (items[f"body_{outcome}"] != "")]
    values = pd.to_numeric(national[f"body_{outcome}"]).astype(int)
    counts = values.value_counts().sort_index(kind="stable").sort_values(ascending=False, kind="stable")
    row = {"briefing_id": briefing_id, "outcome": outcome, "value": "", "qualifier": "", "copies_with_value": 0,
           "copies_other": 0, "other_values": "", "national_copies": len(national), "items": len(items)}
    if counts.empty:
        return {**row, "status": "needs hand extraction"}
    top = counts.iloc[0]
    tied = counts[counts == top]
    listing = lambda c: "; ".join(f"{v:,} ({n})" for v, n in c.items())
    if len(tied) > 1:
        return {**row, "copies_with_value": int(top), "copies_other": int(len(values) - top),
                "other_values": listing(counts), "status": "conflict"}
    value = counts.index[0]
    quals = national.loc[values == value, f"body_{outcome}_qualifier"]
    qualifier = max(dict.fromkeys(quals), key=lambda q: (quals == q).sum())
    others = counts.iloc[1:]
    return {**row, "value": int(value), "qualifier": qualifier, "copies_with_value": int(top),
            "copies_other": int(others.sum()), "other_values": listing(others),
            "status": "agreed" if others.empty else "majority"}


def briefing_figures(sheet: pd.DataFrame) -> pd.DataFrame:
    rows = [outcome_row(b, o, g) for b, g in sheet.groupby("briefing_id", sort=True) for o in OUTCOMES]
    return pd.DataFrame(rows, columns=FIGURE_COLUMNS)


def build(sheet_path=EXTRACTION_SHEET, out_path=BRIEFING_FIGURES) -> pd.DataFrame:
    table = briefing_figures(pd.read_csv(sheet_path, keep_default_na=False, dtype=str))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path, index=False)
    return table


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    table = build()
    print(f"briefings: {table['briefing_id'].nunique()}; rows: {len(table)}")
    print(pd.crosstab(table["status"], table["outcome"], margins=True).reindex([*STATUSES, "All"]).fillna(0)
          .astype(int).to_string())


if __name__ == "__main__":
    main()
