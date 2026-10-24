"""Final per-briefing figures: the automatic agreed values, the hand-extracted values and the corrections.

Usage: python -m scoreboard.final_figures

Checks data/review/figures_hand_coded.csv (check_hand) and data/review/figures_corrections.csv
(check_corrections); each lists every failure and neither file is ever changed. Only when both pass, writes
data/briefings/briefing_figures_final.csv, one row per briefing and outcome:
- rows whose automatic status (data/briefings/briefing_figures.csv) is "agreed": value and qualifier from
  the automatic table, final_status "reported", source "automatic", notes blank;
- rows in the hand file: value, qualifier and final_status from confirmed_value, confirmed_qualifier and
  confirmed_status, source "hand", notes from figure_notes;
- rows in the corrections file (automatic agreed values found wrong in validation, applied after the hand
  file): value, qualifier and final_status from corrected_value, corrected_qualifier and corrected_status,
  source "correction", notes from reason;
- auto_value and auto_status always carry the automatic table's value and status;
- briefing_date (the first publication date) and period_class come from data/briefings/full_briefings.csv,
  with period_classes where the members carry more than one class.
Hand-coding conventions are in docs/review_guide.md ("Hand extraction of briefing figures, 2026-10-24").
"""

import argparse
import re

import pandas as pd

from scoreboard.briefing_figures import BRIEFING_FIGURES
from scoreboard.briefings import BRIEFINGS
from scoreboard.triage_check import REVIEW_DIR

HAND_CODED = REVIEW_DIR / "figures_hand_coded.csv"
CORRECTIONS = REVIEW_DIR / "figures_corrections.csv"
FINAL_FIGURES = BRIEFINGS.parent / "briefing_figures_final.csv"
HAND_ROWS = 357
HAND_STATUSES = ("conflict", "majority", "needs hand extraction")
CONFIRMED_STATUSES = ("reported", "vague", "not reported", "unresolved")
CORRECTED_STATUSES = ("reported", "vague", "not reported")
VAGUE_TERMS = ("several", "scores", "dozens", "many")
QUALIFIERS = ("over", "no fewer than", "at least", *VAGUE_TERMS, "summed categories")
PLUS_RE = re.compile(r"plus [1-9]\d*")
POSITIVE_INT_RE = re.compile(r"[1-9]\d*")
FINAL_COLUMNS = ["briefing_id", "briefing_date", "period_class", "outcome", "value", "qualifier", "final_status",
                 "source", "auto_value", "auto_status", "notes"]


def check_hand(hand: pd.DataFrame, auto: pd.DataFrame, expected: int = HAND_ROWS) -> list[str]:
    """Every failure of the checks on the hand file, one line each; empty when it passes."""
    failures = []
    key = lambda r: f"{r.briefing_id} {r.outcome}"
    if len(hand) != expected:
        failures.append(f"row count {len(hand)}, expected {expected}")
    dupes = hand[hand.duplicated(["briefing_id", "outcome"], keep=False)]
    failures += [f"{key(r)}: duplicate key" for r in dupes.drop_duplicates(["briefing_id", "outcome"]).itertuples()]
    wanted = auto[auto["status"].isin(HAND_STATUSES)]
    have, need = set(zip(hand["briefing_id"], hand["outcome"])), set(zip(wanted["briefing_id"], wanted["outcome"]))
    failures += [f"{b} {o}: not a conflict, majority or needs-hand-extraction row in briefing_figures.csv"
                 for b, o in sorted(have - need)]
    failures += [f"{b} {o}: missing from the hand file" for b, o in sorted(need - have)]
    for r in hand.itertuples():
        status, value, qualifier = r.confirmed_status, r.confirmed_value.strip(), r.confirmed_qualifier
        if status not in CONFIRMED_STATUSES:
            failures.append(f"{key(r)}: confirmed_status {status!r} not one of {', '.join(CONFIRMED_STATUSES)}")
        if status == "reported" and not POSITIVE_INT_RE.fullmatch(value):
            failures.append(f"{key(r)}: reported but confirmed_value {value!r} is not a positive integer")
        if status != "reported" and value:
            failures.append(f"{key(r)}: confirmed_value {value!r} given with status {status!r}")
        if qualifier and qualifier not in QUALIFIERS and not PLUS_RE.fullmatch(qualifier):
            failures.append(f"{key(r)}: confirmed_qualifier {qualifier!r} not allowed")
        if qualifier in VAGUE_TERMS and status != "vague":
            failures.append(f"{key(r)}: vague term {qualifier!r} with status {status!r}")
        if not r.figure_notes.strip():
            failures.append(f"{key(r)}: empty figure_notes")
    return failures


def check_corrections(corrections: pd.DataFrame, auto: pd.DataFrame) -> list[str]:
    """Every failure of the checks on the corrections file, one line each; empty when it passes."""
    failures = []
    key = lambda r: f"{r.briefing_id} {r.outcome}"
    dupes = corrections[corrections.duplicated(["briefing_id", "outcome"], keep=False)]
    failures += [f"{key(r)}: duplicate key" for r in dupes.drop_duplicates(["briefing_id", "outcome"]).itertuples()]
    auto = auto.set_index(["briefing_id", "outcome"])
    for r in corrections.itertuples():
        status, value = r.corrected_status, r.corrected_value.strip()
        if (r.briefing_id, r.outcome) not in auto.index:
            failures.append(f"{key(r)}: not in briefing_figures.csv")
        else:
            a = auto.loc[(r.briefing_id, r.outcome)]
            if a["status"] != "agreed":
                failures.append(f"{key(r)}: status {a['status']!r} in briefing_figures.csv, not agreed")
            if r.auto_value != a["value"]:
                failures.append(f"{key(r)}: auto_value {r.auto_value!r} but briefing_figures.csv has {a['value']!r}")
        if status not in CORRECTED_STATUSES:
            failures.append(f"{key(r)}: corrected_status {status!r} not one of {', '.join(CORRECTED_STATUSES)}")
        if status == "reported" and not POSITIVE_INT_RE.fullmatch(value):
            failures.append(f"{key(r)}: reported but corrected_value {value!r} is not a positive integer")
        if status != "reported" and value:
            failures.append(f"{key(r)}: corrected_value {value!r} given with status {status!r}")
        if not r.reason.strip():
            failures.append(f"{key(r)}: empty reason")
    return failures


def final_table(auto: pd.DataFrame, hand: pd.DataFrame, briefings: pd.DataFrame,
                corrections: pd.DataFrame | None = None) -> pd.DataFrame:
    info = briefings.set_index("briefing_id")
    period = info["period_class"].where(info["period_class"] != "", info["period_classes"])
    hand = hand.set_index(["briefing_id", "outcome"])
    if corrections is None:
        corrections = pd.DataFrame(columns=["briefing_id", "outcome"])
    corrections = corrections.set_index(["briefing_id", "outcome"])
    rows = []
    for a in auto.itertuples():
        row = {"briefing_id": a.briefing_id, "briefing_date": info.at[a.briefing_id, "first_date"],
               "period_class": period[a.briefing_id], "outcome": a.outcome,
               "auto_value": a.value, "auto_status": a.status}
        if (a.briefing_id, a.outcome) in hand.index:
            h = hand.loc[(a.briefing_id, a.outcome)]
            row |= {"value": h["confirmed_value"], "qualifier": h["confirmed_qualifier"],
                    "final_status": h["confirmed_status"], "source": "hand", "notes": h["figure_notes"]}
        elif a.status == "agreed":
            row |= {"value": a.value, "qualifier": a.qualifier, "final_status": "reported", "source": "automatic",
                    "notes": ""}
        else:
            raise ValueError(f"{a.briefing_id} {a.outcome}: status {a.status!r} and no hand row")
        if (a.briefing_id, a.outcome) in corrections.index:
            c = corrections.loc[(a.briefing_id, a.outcome)]
            row |= {"value": c["corrected_value"], "qualifier": c["corrected_qualifier"],
                    "final_status": c["corrected_status"], "source": "correction", "notes": c["reason"]}
        rows.append(row)
    return pd.DataFrame(rows, columns=FINAL_COLUMNS)


def build(hand_path=HAND_CODED, auto_path=BRIEFING_FIGURES, briefings_path=BRIEFINGS, out_path=FINAL_FIGURES,
          corrections_path=CORRECTIONS):
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    hand, auto, corrections = read(hand_path), read(auto_path), read(corrections_path)
    failures = check_hand(hand, auto) + [f"{corrections_path.name}: {f}" for f in check_corrections(corrections, auto)]
    if failures:
        return None, failures
    table = final_table(auto, hand, read(briefings_path), corrections)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path, index=False)
    return table, []


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    table, failures = build()
    if failures:
        print(f"{HAND_CODED.name}, {CORRECTIONS.name}: {len(failures)} failures; final table not written")
        print("\n".join(failures))
        raise SystemExit(1)
    print(f"{HAND_CODED.name}, {CORRECTIONS.name}: all checks pass; {len(table)} rows written")
    print(table["source"].value_counts().to_string())
    t = table.assign(year=table["briefing_date"].str[:4])
    print(pd.crosstab([t["year"], t["outcome"]], t["final_status"], margins=True).to_string())
    changed = t[(t["source"] == "hand") & (t["final_status"] == "reported") & (t["auto_value"] != "")
                & (t["value"] != t["auto_value"])]
    print(f"\nhand-reported values that differ from a non-blank auto_value: {len(changed)}")
    print(changed[["briefing_id", "outcome", "auto_status", "auto_value", "value", "qualifier"]].to_string(index=False))


if __name__ == "__main__":
    main()
