"""Briefing figures from the national-marker body values of each briefing's copies.

Usage: python -m scoreboard.briefing_figures

Reads data/review/extraction_sheet_v3.csv and the stored body text in data_raw/text/ (no requests), and
writes data/briefings/briefing_figures.csv, one row per briefing and outcome. Only body values found by
the national-marker rule (body_<outcome>_rule "national marker", with a number) are used.

Independent copies follow the pilot (scoreboard.extract, docs/audit_rules.md): copies of one briefing
whose bodies reach the same_wire similarity threshold (SAME_WIRE_THRESHOLD, 0.3) count once, and so do
copies credited to the News Agency of Nigeria. The value and status come from scoreboard.extract.majority:
- value: the national-marker value given by most independent copies (then most copies, then the lower
  value), with qualifier the most common qualifier among the copies giving it (on a tie, that of the first
  such copy in sheet order); blank when two values tie on independent copies.
- copies_with_value, independent_copies_with_value: copies giving that value (in a tie, the first-ranked
  tied value). copies_other, independent_copies_other: copies giving any other national-marker value;
  other_values lists those values as "value (copies, independent)", in rank order.
- status: "agreed" when all national-marker copies give one value, "majority" when one value has the most
  independent copies, "conflict" when values tie on independent copies, "needs hand extraction" when no
  copy has a national-marker value.
"""

import argparse

import pandas as pd

from scoreboard.briefings import BRIEFINGS
from scoreboard.extract import OUTCOMES, count_independent, majority, same_wire_pairs
from scoreboard.extraction_sheet import EXTRACTION_SHEET
from scoreboard.wirecheck import has_nan_credit, load_bodies

BRIEFING_FIGURES = BRIEFINGS.parent / "briefing_figures.csv"
NATIONAL_RULE = "national marker"
STATUSES = ("agreed", "majority", "conflict", "needs hand extraction")
FIGURE_COLUMNS = ["briefing_id", "outcome", "value", "qualifier", "copies_with_value",
                  "independent_copies_with_value", "copies_other", "independent_copies_other", "other_values",
                  "national_copies", "items", "status"]


def ranked_values(values: dict[str, int], pairs, nan_urls: set[str]) -> list[tuple[int, list[str], int]]:
    """(value, urls, independent copies) per value, ranked as scoreboard.extract.majority ranks them."""
    by_value: dict[int, list[str]] = {}
    for url, v in values.items():
        by_value.setdefault(v, []).append(url)
    rows = [(v, urls, count_independent(urls, pairs, nan_urls)) for v, urls in by_value.items()]
    return sorted(rows, key=lambda r: (-r[2], -len(r[1]), r[0]))


def outcome_row(briefing_id: str, outcome: str, items: pd.DataFrame, pairs, nan_urls: set[str]) -> dict:
    national = items[(items[f"body_{outcome}_rule"] == NATIONAL_RULE) & (items[f"body_{outcome}"] != "")]
    values = dict(zip(national["url"], pd.to_numeric(national[f"body_{outcome}"]).astype(int)))
    row = {"briefing_id": briefing_id, "outcome": outcome, "value": "", "qualifier": "", "copies_with_value": 0,
           "independent_copies_with_value": 0, "copies_other": 0, "independent_copies_other": 0,
           "other_values": "", "national_copies": len(national), "items": len(items)}
    if not values:
        return {**row, "status": "needs hand extraction"}
    m = majority(values, pairs, nan_urls)
    ranked = ranked_values(values, pairs, nan_urls)
    (top_value, top_urls, top_independent), others = ranked[0], ranked[1:]
    other_urls = [u for _, urls, _ in others for u in urls]
    row |= {"copies_with_value": len(top_urls), "independent_copies_with_value": top_independent,
            "copies_other": len(other_urls),
            "independent_copies_other": count_independent(other_urls, pairs, nan_urls) if other_urls else 0,
            "other_values": "; ".join(f"{v:,} ({len(urls)}, {ind})" for v, urls, ind in others)}
    if m["tie"]:
        return {**row, "other_values": "; ".join(f"{v:,} ({len(urls)}, {ind})" for v, urls, ind in ranked),
                "status": "conflict"}
    quals = national.loc[national["url"].isin(top_urls), f"body_{outcome}_qualifier"]
    qualifier = max(dict.fromkeys(quals), key=lambda q: (quals == q).sum())
    return {**row, "value": int(m["value"]), "qualifier": qualifier,
            "status": "majority" if m["conflict"] else "agreed"}


def briefing_figures(sheet: pd.DataFrame, bodies: pd.Series) -> pd.DataFrame:
    rows = []
    for b, g in sheet.groupby("briefing_id", sort=True):
        urls = list(g["url"])
        pairs = same_wire_pairs(urls, bodies)
        nan_urls = {u for u in urls if has_nan_credit(bodies[u])}
        rows += [outcome_row(b, o, g, pairs, nan_urls) for o in OUTCOMES]
    return pd.DataFrame(rows, columns=FIGURE_COLUMNS)


def build(sheet_path=EXTRACTION_SHEET, out_path=BRIEFING_FIGURES, load_bodies=load_bodies) -> pd.DataFrame:
    sheet = pd.read_csv(sheet_path, keep_default_na=False, dtype=str)
    table = briefing_figures(sheet, load_bodies(sheet["url"]))
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
