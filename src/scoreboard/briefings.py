"""Briefing table from the confirmed briefing groups.

Usage: python -m scoreboard.briefings

Checks data/review/group_review_coded.csv against data/review/group_review_sheet.csv and stops with a
message if any check fails: the same rows and urls; no column other than confirmed_group_id and
group_notes changed; every confirmed_group_id has the form B<year>-<NNN>, its year is the year of the
group's first publication date, and the IDs of each year run from 001 without gaps in order of first
publication date; no group_notes is empty.

Writes data/briefings/full_briefings.csv, one row per confirmed_group_id: first and last publication
date, year, period class, numbers of items and outlets, the outlets, items by decided_by, the candidate
groups merged into it, the old pilot ID (pilot_group_id, from the confirmed_group_id column of
data/review/pilot_review_2024.csv, whose B2024-NNN numbering differs), figure_flag and merge_note.
period_class is the class shared by the members that have one; a group whose members carry more than one
class has period_class blank and every class with its item count in period_classes. figure_flag lists the
outcomes whose headline figures differ within the confirmed group. merge_note holds the group_notes other
than CONFIRMED_NOTE. Each old pilot group should map to exactly one briefing; any that does not, or any
briefing holding more than one old pilot group, is reported. The pilot files are only read.
"""

import argparse

import pandas as pd

from scoreboard.config import PROJECT_ROOT
from scoreboard.group_candidates import GROUP_SHEET, OUTCOMES, figure_flags
from scoreboard.triage import PILOT_REVIEW
from scoreboard.triage_check import REVIEW_DIR

GROUP_CODED = REVIEW_DIR / "group_review_coded.csv"
BRIEFINGS = PROJECT_ROOT / "data" / "briefings" / "full_briefings.csv"
CODED_COLUMNS = ("confirmed_group_id", "group_notes")
CONFIRMED_NOTE = "Candidate group confirmed"
DECIDED_BY = ("auto_yes", "hand", "pilot")
BRIEFING_COLUMNS = ["briefing_id", "year", "first_date", "last_date", "period_class", "period_classes", "items",
                    "outlets", "outlet_list", *[f"items_{d}" for d in DECIDED_BY], "candidate_groups",
                    "pilot_group_id", "figure_flag", "merge_note"]


class BriefingError(RuntimeError):
    pass


def check_coded(sheet: pd.DataFrame, coded: pd.DataFrame) -> dict:
    """Runs the checks in the module docstring; returns the numbers of groups, candidate groups, merges
    (candidate groups joined into another) and candidate groups split across briefings."""
    if len(coded) != len(sheet) or sorted(coded["url"]) != sorted(sheet["url"]) or coded["url"].duplicated().any():
        raise BriefingError(f"coded rows ({len(coded)}) do not match the sheet's {len(sheet)} rows and urls")
    both = coded.merge(sheet, on="url", suffixes=("", "_sheet"))
    changed = [c for c in sheet.columns if c != "url" and c not in CODED_COLUMNS and (both[c] != both[f"{c}_sheet"]).any()]
    if changed:
        raise BriefingError(f"columns changed from the sheet: {', '.join(changed)}")
    bad = coded.loc[~coded["confirmed_group_id"].str.fullmatch(r"B\d{4}-\d{3}"), "url"]
    if len(bad):
        raise BriefingError(f"{len(bad)} rows without a confirmed_group_id of the form B<year>-<NNN>, e.g. {bad.iloc[0]}")
    empty = coded.loc[coded["group_notes"].str.strip() == "", "url"]
    if len(empty):
        raise BriefingError(f"{len(empty)} rows with empty group_notes, e.g. {empty.iloc[0]}")
    groups = coded.groupby("confirmed_group_id").agg(first=("date", "min"), candidates=("candidate_group", "nunique"))
    groups["id_year"], groups["number"] = groups.index.str[1:5], groups.index.str[6:].astype(int)
    wrong_year = groups.index[groups["id_year"] != groups["first"].str[:4]]
    if len(wrong_year):
        raise BriefingError(f"ID year differs from the first publication date: {', '.join(wrong_year)}")
    for year, g in groups.groupby("id_year"):
        ordered = g.sort_values(["first", "number"])["number"].tolist()
        if ordered != list(range(1, len(g) + 1)):
            raise BriefingError(f"{year} IDs are not numbered 001 upward in date order without gaps")
    splits = coded.groupby("candidate_group")["confirmed_group_id"].nunique()
    return {"groups": len(groups), "candidate groups": int(coded["candidate_group"].nunique()),
            "merges": int((groups["candidates"] - 1).sum()), "candidate groups split": int((splits > 1).sum())}


def pilot_ids(coded: pd.DataFrame, pilot: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    """Old pilot ID per briefing, and a line for each old pilot group not mapping to exactly one briefing
    and each briefing holding more than one old pilot group."""
    old = pilot.loc[pilot["confirmed_group_id"] != "", ["url", "confirmed_group_id"]].rename(
        columns={"confirmed_group_id": "pilot_group_id"})
    both = old.merge(coded[["url", "confirmed_group_id"]], on="url", how="left")
    problems = [f"pilot group {p}: {', '.join(sorted(g['confirmed_group_id'].fillna('not in briefings').unique()))}"
                for p, g in both.groupby("pilot_group_id") if g["confirmed_group_id"].nunique(dropna=False) != 1
                or g["confirmed_group_id"].isna().any()]
    per_briefing = both.dropna().groupby("confirmed_group_id")["pilot_group_id"].unique()
    problems += [f"briefing {b}: holds pilot groups {', '.join(sorted(p))}" for b, p in per_briefing.items() if len(p) > 1]
    return per_briefing.map(lambda p: ", ".join(sorted(p))), problems


def briefings(coded: pd.DataFrame, pilot: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    items = coded.copy()
    for o in OUTCOMES:
        items[o] = pd.to_numeric(items[o], errors="coerce")
    items["figure_flag"] = figure_flags(items.assign(candidate_group=items["confirmed_group_id"]))
    old_ids, problems = pilot_ids(coded, pilot)
    rows = []
    for bid, g in items.groupby("confirmed_group_id", sort=True):
        classes = g.loc[g["period_note"] != "", "period_note"].value_counts()
        notes = [n for n in dict.fromkeys(g["group_notes"]) if n != CONFIRMED_NOTE]
        outlets = sorted(g["outlet"].unique())
        rows.append({
            "briefing_id": bid, "year": bid[1:5], "first_date": g["date"].min(), "last_date": g["date"].max(),
            "period_class": classes.index[0] if len(classes) == 1 else "",
            "period_classes": "; ".join(f"{c} {n}" for c, n in classes.items()),
            "items": len(g), "outlets": len(outlets), "outlet_list": "; ".join(outlets),
            **{f"items_{d}": int((g["decided_by"] == d).sum()) for d in DECIDED_BY},
            "candidate_groups": ", ".join(sorted(g["candidate_group"].unique())),
            "pilot_group_id": old_ids.get(bid, ""), "figure_flag": g["figure_flag"].iloc[0],
            "merge_note": " | ".join(notes),
        })
    return pd.DataFrame(rows, columns=BRIEFING_COLUMNS), problems


def build(sheet_path=GROUP_SHEET, coded_path=GROUP_CODED, pilot_path=PILOT_REVIEW, out_path=BRIEFINGS):
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    coded = read(coded_path)
    stats = check_coded(read(sheet_path), coded)
    table, problems = briefings(coded, read(pilot_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_path, index=False)
    return stats, table, problems


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    try:
        stats, table, problems = build()
    except BriefingError as e:
        raise SystemExit(f"briefing build failed: {e}")
    print(stats)
    print(f"briefings: {len(table)}; with pilot_group_id: {int((table['pilot_group_id'] != '').sum())}; "
          f"pilot mapping problems: {problems or 'none'}")
    print(table.groupby("year").agg(briefings=("briefing_id", "size"), items=("items", "sum")).to_string())
    mixed = table[table["period_class"] == ""]
    print(f"\nbriefings without a single period class: {len(mixed)}")
    print(mixed[["briefing_id", "first_date", "period_classes"]].to_string(index=False))
    print(f"\nwith figure_flag: {int((table['figure_flag'] != '').sum())}; with merge_note: {int((table['merge_note'] != '').sum())}")


if __name__ == "__main__":
    main()
