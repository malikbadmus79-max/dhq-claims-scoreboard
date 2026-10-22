"""Merges the hand-coded review batches and joins them with the triage decisions.

Usage: python -m scoreboard.review_merge

Reads data/review/full_review_sheet.csv and data/review/full_review_coded_B01.csv onward (one file per
batch in the sheet) and writes data/review/full_review_coded.csv after these checks, any of which stops
the run with a message: exactly EXPECTED_ITEMS rows numbered R0001 upward without gaps or duplicates;
every coded row matches the sheet on review_id, batch and url; every code is yes, no or unsure; every
row without text is coded unsure and every unsure row is a row without text; no row has empty notes.

The merged codes are then joined with the triage "yes" and "no" items in outputs/tables/full_triage_<year>.csv
to give one row per item in data/review/full_classification.csv (decided_by auto_yes, auto_no or hand),
and counts by year, outlet, decided_by and code in outputs/tables/full_classification_summary.csv.
Discovered items (outputs/tables/full_inventory_<year>.csv) in neither set are counted by reason; the
run stops if any item is both auto-decided and hand-coded.
"""

import argparse

import pandas as pd

from scoreboard.discover import TABLES_DIR
from scoreboard.review_sheet import SHEET
from scoreboard.triage import FULL_LABELS
from scoreboard.triage_check import REVIEW_DIR, YEARS

EXPECTED_ITEMS = 1005
CODES = ("yes", "no", "unsure")
MERGED = REVIEW_DIR / "full_review_coded.csv"
CLASSIFICATION = REVIEW_DIR / "full_classification.csv"
SUMMARY = TABLES_DIR / "full_classification_summary.csv"
MERGED_COLUMNS = ["review_id", "batch", "year", "outlet", "date", "title", "url", "has_text",
                  "is_operational_briefing", "notes"]
CLASSIFICATION_COLUMNS = ["year", "outlet", "date", "url", "decided_by", "is_operational_briefing", "review_id"]
SUMMARY_COLUMNS = ["year", "outlet", "decided_by", "is_operational_briefing", "items"]
AUTO = {"yes": "auto_yes", "no": "auto_no"}


class MergeError(RuntimeError):
    pass


def coded_path(review_dir, batch: str):
    return review_dir / f"full_review_coded_{batch}.csv"


def read_batches(sheet: pd.DataFrame, review_dir=REVIEW_DIR) -> pd.DataFrame:
    batches = sorted(sheet["batch"].unique())
    missing = [b for b in batches if not coded_path(review_dir, b).exists()]
    if missing:
        raise MergeError(f"coded batch files missing: {', '.join(missing)}")
    return pd.concat([pd.read_csv(coded_path(review_dir, b), keep_default_na=False, dtype=str) for b in batches],
                     ignore_index=True)


def merge(sheet: pd.DataFrame, coded: pd.DataFrame, expected=EXPECTED_ITEMS) -> pd.DataFrame:
    """Checks the coded rows against the sheet and returns them in MERGED_COLUMNS, has_text from the sheet."""
    if len(coded) != expected:
        raise MergeError(f"expected {expected} coded rows, found {len(coded)}")
    dupes = sorted(coded.loc[coded["review_id"].duplicated(), "review_id"].unique())
    if dupes:
        raise MergeError(f"duplicate review_id: {', '.join(dupes)}")
    wanted = {f"R{i:04d}" for i in range(1, expected + 1)}
    gaps, extra = sorted(wanted - set(coded["review_id"])), sorted(set(coded["review_id"]) - wanted)
    if gaps or extra:
        raise MergeError(f"review_id not R0001 to R{expected:04d}: missing {gaps[:10]}, unexpected {extra[:10]}")
    both = coded.merge(sheet[["review_id", "batch", "url", "has_text"]], on="review_id", how="left",
                       suffixes=("", "_sheet"), indicator=True)
    mismatch = both[(both["_merge"] != "both") | (both["batch"] != both["batch_sheet"])
                    | (both["url"] != both["url_sheet"])]
    if len(mismatch):
        raise MergeError(f"coded rows differ from the sheet on review_id, batch or url: "
                         f"{', '.join(mismatch['review_id'].head(10))}")
    bad = both[~both["is_operational_briefing"].isin(CODES)]
    if len(bad):
        raise MergeError(f"is_operational_briefing not one of {', '.join(CODES)}: {', '.join(bad['review_id'].head(10))}")
    no_text = both["has_text"].str.lower() != "true"
    unsure = both["is_operational_briefing"] == "unsure"
    if (no_text & ~unsure).any():
        raise MergeError(f"rows without text not coded unsure: {', '.join(both.loc[no_text & ~unsure, 'review_id'].head(10))}")
    if (unsure & ~no_text).any():
        raise MergeError(f"unsure rows that have text: {', '.join(both.loc[unsure & ~no_text, 'review_id'].head(10))}")
    empty = both["notes"].str.strip() == ""
    if empty.any():
        raise MergeError(f"rows with empty notes: {', '.join(both.loc[empty, 'review_id'].head(10))}")
    return both.sort_values("review_id", ignore_index=True)[MERGED_COLUMNS]


def read_years(tables_dir, stem: str) -> pd.DataFrame:
    return pd.concat([pd.read_csv(tables_dir / f"{stem}_{y}.csv", keep_default_na=False, dtype=str).assign(year=str(y))
                      for y in YEARS], ignore_index=True)


def classify(merged: pd.DataFrame, tables_dir=TABLES_DIR, labels_path=FULL_LABELS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns one classification row per auto-decided or hand-coded item, and the discovered items in
    neither set counted by year and reason."""
    triage = read_years(tables_dir, "full_triage")
    auto = triage[triage["decision"].isin(AUTO)]
    overlap = sorted(set(auto["url"]) & set(merged["url"]))
    if overlap:
        raise MergeError(f"{len(overlap)} items are both auto-decided and hand-coded, e.g. {overlap[:5]}")
    if auto["url"].duplicated().any() or merged["url"].duplicated().any():
        raise MergeError("a url appears more than once among auto-decided or hand-coded items")
    stray = sorted(set(merged["url"]) - set(triage.loc[~triage["decision"].isin(AUTO), "url"]))
    if stray:
        raise MergeError(f"{len(stray)} hand-coded items are not undecided triage items, e.g. {stray[:5]}")
    auto_rows = auto.assign(decided_by=auto["decision"].map(AUTO), is_operational_briefing=auto["decision"], review_id="")
    hand_rows = merged.assign(decided_by="hand")
    out = (pd.concat([auto_rows, hand_rows], ignore_index=True)[CLASSIFICATION_COLUMNS]
           .sort_values(["date", "outlet", "url"], ignore_index=True))

    inventory = read_years(tables_dir, "full_inventory")
    rest = inventory[~inventory["url"].isin(out["url"])]
    labels = pd.read_csv(labels_path, keep_default_na=False, dtype=str) if labels_path.exists() else pd.DataFrame(columns=["url", "label_source"])
    source = rest["url"].map(labels.set_index("url")["label_source"])
    in_triage = rest["url"].isin(triage["url"])
    reason = pd.Series("not in triage table, no label", index=rest.index)
    reason[source.notna()] = "not triaged; labelled from " + source[source.notna()] + " review"
    reason[in_triage] = "triage decision " + rest["url"].map(triage.set_index("url")["decision"])[in_triage] + " without hand code"
    unclassified = rest.assign(reason=reason).groupby(["year", "reason"]).size().rename("items").reset_index()
    return out, unclassified


def summary(classification: pd.DataFrame) -> pd.DataFrame:
    return (classification.groupby(SUMMARY_COLUMNS[:-1]).size().rename("items").reset_index()[SUMMARY_COLUMNS])


def run(sheet_path=SHEET, review_dir=REVIEW_DIR, tables_dir=TABLES_DIR, labels_path=FULL_LABELS,
        merged_path=MERGED, classification_path=CLASSIFICATION, summary_path=SUMMARY, expected=EXPECTED_ITEMS):
    sheet = pd.read_csv(sheet_path, keep_default_na=False, dtype=str)
    merged = merge(sheet, read_batches(sheet, review_dir), expected)
    classification, unclassified = classify(merged, tables_dir, labels_path)
    table = summary(classification)
    merged.to_csv(merged_path, index=False)
    classification.to_csv(classification_path, index=False)
    table.to_csv(summary_path, index=False)
    return merged, classification, table, unclassified


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    try:
        merged, classification, table, unclassified = run()
    except MergeError as e:
        raise SystemExit(f"review merge failed: {e}")
    print(f"merged rows: {len(merged)}; classified items: {len(classification)}")
    print(pd.crosstab([classification["year"], classification["decided_by"]],
                      classification["is_operational_briefing"], margins=True).to_string())
    print("\nnot classified:")
    print(unclassified.to_string(index=False) if len(unclassified) else "none")


if __name__ == "__main__":
    main()
