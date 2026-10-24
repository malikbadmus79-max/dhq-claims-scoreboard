"""Merges the hand-coded review batches and joins them with the triage decisions.

Usage: python -m scoreboard.review_merge

Reads data/review/full_review_sheet.csv and data/review/full_review_coded_B01.csv onward (one file per
batch in the sheet) and writes data/review/full_review_coded.csv after these checks, any of which stops
the run with a message: exactly EXPECTED_ITEMS rows numbered R0001 upward without gaps or duplicates;
every coded row matches the sheet on review_id, batch and url; every code is yes, no or unsure; every
row without text is coded unsure and every unsure row is a row without text; no row has empty notes.

The merged codes are then joined with the triage "yes" and "no" items in outputs/tables/full_triage_<year>.csv
and the 2024 pilot items in data/review/full_labels.csv (label_source "pilot"; review_id holds the pilot
item ID) to give one row per item in data/review/full_classification.csv (decided_by auto_yes, auto_no,
hand or pilot). Pilot items take recheck_code from data/review/pilot_recheck_coded.csv, checked against
data/review/pilot_recheck_sheet.csv: RECHECK_ITEMS rows numbered P001 upward, urls matching the sheet,
recheck_code yes or no, changed "yes" exactly when recheck_code differs from pilot_code, no empty notes.
The original pilot label is kept in original_pilot_code; the label files are not changed. Codes listed in
data/review/classification_overrides.csv (url, from_code, to_code, reason) are then applied, with decided_by
kept and overridden "yes"; an override whose from_code does not match stops the run. Counts by year,
outlet, decided_by and code go to outputs/tables/full_classification_summary.csv.
Discovered items (outputs/tables/full_inventory_<year>.csv) in none of these sets are counted by reason;
the run stops if any item falls in more than one.
"""

import argparse

import pandas as pd

from scoreboard.discover import TABLES_DIR
from scoreboard.pilot_recheck import RECHECK_SHEET
from scoreboard.review_sheet import SHEET
from scoreboard.triage import FULL_LABELS
from scoreboard.triage_check import REVIEW_DIR, YEARS

EXPECTED_ITEMS = 1005
RECHECK_ITEMS = 230
CODES = ("yes", "no", "unsure")
RECHECK_CODES = ("yes", "no")
MERGED = REVIEW_DIR / "full_review_coded.csv"
RECHECK_CODED = REVIEW_DIR / "pilot_recheck_coded.csv"
OVERRIDES = REVIEW_DIR / "classification_overrides.csv"
OVERRIDE_COLUMNS = ["url", "from_code", "to_code", "reason"]
CLASSIFICATION = REVIEW_DIR / "full_classification.csv"
SUMMARY = TABLES_DIR / "full_classification_summary.csv"
MERGED_COLUMNS = ["review_id", "batch", "year", "outlet", "date", "title", "url", "has_text",
                  "is_operational_briefing", "notes"]
CLASSIFICATION_COLUMNS = ["year", "outlet", "date", "url", "decided_by", "is_operational_briefing", "review_id",
                          "original_pilot_code", "overridden"]
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


def check_recheck(sheet: pd.DataFrame, coded: pd.DataFrame, expected=RECHECK_ITEMS) -> pd.DataFrame:
    """Checks the pilot recheck against its sheet and returns it unchanged."""
    if len(coded) != expected:
        raise MergeError(f"expected {expected} pilot recheck rows, found {len(coded)}")
    wanted = [f"P{i:03d}" for i in range(1, expected + 1)]
    if coded["review_id"].duplicated().any() or sorted(coded["review_id"]) != wanted:
        raise MergeError(f"pilot recheck review_id is not P001 to P{expected:03d} without gaps or duplicates")
    both = coded.merge(sheet[["review_id", "url"]], on="review_id", how="left", suffixes=("", "_sheet"))
    mismatch = both[both["url"] != both["url_sheet"]]
    if len(mismatch):
        raise MergeError(f"pilot recheck urls differ from the sheet: {', '.join(mismatch['review_id'].head(10))}")
    bad = coded[~coded["recheck_code"].isin(RECHECK_CODES)]
    if len(bad):
        raise MergeError(f"recheck_code not yes or no: {', '.join(bad['review_id'].head(10))}")
    wrong = coded[(coded["changed"] == "yes") != (coded["recheck_code"] != coded["pilot_code"])]
    if len(wrong) or not coded["changed"].isin(["yes", "no"]).all():
        raise MergeError(f"changed does not match recheck_code against pilot_code: {', '.join(wrong['review_id'].head(10))}")
    empty = coded["notes"].str.strip() == ""
    if empty.any():
        raise MergeError(f"pilot recheck rows with empty notes: {', '.join(coded.loc[empty, 'review_id'].head(10))}")
    return coded


def read_years(tables_dir, stem: str) -> pd.DataFrame:
    return pd.concat([pd.read_csv(tables_dir / f"{stem}_{y}.csv", keep_default_na=False, dtype=str).assign(year=str(y))
                      for y in YEARS], ignore_index=True)


def classify(merged: pd.DataFrame, recheck: pd.DataFrame, tables_dir=TABLES_DIR,
             labels_path=FULL_LABELS) -> tuple[pd.DataFrame, pd.DataFrame]:
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

    inventory = read_years(tables_dir, "full_inventory")
    labels = pd.read_csv(labels_path, keep_default_na=False, dtype=str) if labels_path.exists() else pd.DataFrame(
        columns=["url", "is_operational_briefing", "label_source", "pilot_item_id"])
    pilot = labels[labels["label_source"] == "pilot"]
    taken = set(auto["url"]) | set(merged["url"])
    clash = sorted(set(pilot["url"]) & taken)
    if clash:
        raise MergeError(f"{len(clash)} pilot-labelled items are also auto-decided or hand-coded, e.g. {clash[:5]}")
    if sorted(recheck["url"]) != sorted(pilot["url"]):
        raise MergeError("pilot recheck urls are not the pilot-labelled items in the label file")
    pilot = (pilot.rename(columns={"is_operational_briefing": "original_pilot_code"})
             .merge(recheck[["url", "recheck_code"]], on="url", validate="one_to_one"))
    pilot_rows = (inventory[inventory["url"].isin(pilot["url"])].rename(columns={"publish_date": "date"})
                  .merge(pilot[["url", "recheck_code", "original_pilot_code", "pilot_item_id"]], on="url",
                         validate="one_to_one")
                  .assign(decided_by="pilot", review_id=lambda d: d["pilot_item_id"],
                          is_operational_briefing=lambda d: d["recheck_code"]))
    out = (pd.concat([auto_rows, hand_rows, pilot_rows], ignore_index=True)
           .assign(original_pilot_code=lambda d: d["original_pilot_code"].fillna(""), overridden="no")[CLASSIFICATION_COLUMNS]
           .sort_values(["date", "outlet", "url"], ignore_index=True))

    rest = inventory[~inventory["url"].isin(out["url"])]
    in_triage = rest["url"].isin(triage["url"])
    reason = pd.Series("not in triage table, no label", index=rest.index)
    reason[in_triage] = "triage decision " + rest["url"].map(triage.set_index("url")["decision"])[in_triage] + " without hand code"
    unclassified = rest.assign(reason=reason).groupby(["year", "reason"]).size().rename("items").reset_index()
    if out["url"].duplicated().any() or not set(out["url"]) <= set(inventory["url"]):
        raise MergeError("classification does not hold each discovered item at most once")
    return out, unclassified


def apply_overrides(classification: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    """Sets to_code on each override url whose current code is from_code; decided_by is kept and
    overridden is "yes". Stops on an override whose url is not classified or whose from_code does not match."""
    out = classification.assign(overridden="no")
    if overrides["url"].duplicated().any():
        raise MergeError("an override url appears more than once")
    for o in overrides.itertuples():
        hit = out["url"] == o.url
        if hit.sum() != 1:
            raise MergeError(f"override url not classified: {o.url}")
        if out.loc[hit, "is_operational_briefing"].iloc[0] != o.from_code:
            raise MergeError(f"override from_code {o.from_code} does not match the code of {o.url}")
        if o.to_code not in CODES or not o.reason.strip():
            raise MergeError(f"override for {o.url} needs a to_code in {', '.join(CODES)} and a reason")
        out.loc[hit, ["is_operational_briefing", "overridden"]] = [o.to_code, "yes"]
    return out


def summary(classification: pd.DataFrame) -> pd.DataFrame:
    return (classification.groupby(SUMMARY_COLUMNS[:-1]).size().rename("items").reset_index()[SUMMARY_COLUMNS])


def run(sheet_path=SHEET, review_dir=REVIEW_DIR, tables_dir=TABLES_DIR, labels_path=FULL_LABELS,
        merged_path=MERGED, classification_path=CLASSIFICATION, summary_path=SUMMARY, expected=EXPECTED_ITEMS,
        recheck_sheet_path=RECHECK_SHEET, recheck_path=RECHECK_CODED, recheck_expected=RECHECK_ITEMS,
        overrides_path=OVERRIDES):
    sheet = pd.read_csv(sheet_path, keep_default_na=False, dtype=str)
    merged = merge(sheet, read_batches(sheet, review_dir), expected)
    recheck = check_recheck(pd.read_csv(recheck_sheet_path, keep_default_na=False, dtype=str),
                            pd.read_csv(recheck_path, keep_default_na=False, dtype=str), recheck_expected)
    classification, unclassified = classify(merged, recheck, tables_dir, labels_path)
    overrides = (pd.read_csv(overrides_path, keep_default_na=False, dtype=str) if overrides_path.exists()
                 else pd.DataFrame(columns=OVERRIDE_COLUMNS))
    classification = apply_overrides(classification, overrides)
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
    pilot = classification[classification["decided_by"] == "pilot"]
    changed = int((pilot["is_operational_briefing"] != pilot["original_pilot_code"]).sum())
    print(f"merged rows: {len(merged)}; classified items: {len(classification)}; pilot codes changed by recheck: {changed}; "
          f"overridden: {int((classification['overridden'] == 'yes').sum())}")
    print(pd.crosstab([classification["year"], classification["decided_by"]],
                      classification["is_operational_briefing"], margins=True).to_string())
    print("\nnot classified:")
    print(unclassified.to_string(index=False) if len(unclassified) else "none")


if __name__ == "__main__":
    main()
