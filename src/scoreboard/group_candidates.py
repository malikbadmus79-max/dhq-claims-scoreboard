"""Candidate briefing groups for every item coded yes in data/review/full_classification.csv.

Usage: python -m scoreboard.group_candidates

Each item gets a period class from its notes and headline figures from its title:
- period: hand items take the notes in data/review/full_review_coded.csv; pilot items take the "Period:"
  note in data/review/pilot_review_2024.csv, or the recheck notes in data/review/pilot_recheck_coded.csv
  when the pilot note has none; auto-yes items have no notes and so no period. The first matching rule in
  PERIOD_RULES gives the class (cumulative, year, quarterly, monthly, biweekly, weekly); failing that, a
  stated date range ("11 to 25 November 2021") is classed by its length in days.
- figures: the first number joined to an outcome word in the title, before or after it, for neutralised
  (neutralised, killed, eliminated), arrested (arrested, apprehended, nabbed, captured) and rescued. Year-like numbers
  followed by ":" or preceded by "in", "of" or "since" are ignored.

Two items are candidates for the same briefing when their publication dates are at most MAX_GAP_DAYS
apart, they do not have different period classes (an item without a period conflicts with none), and
their headline figures differ on at most one outcome where both carry a figure. Items are taken in date
order and each joins an open candidate group in which it is a candidate with every member: the one where
most members share a figure or period with it, or the earliest-starting on a tie; otherwise it starts a
new group. Since every pair in a group must be within MAX_GAP_DAYS, no group spans more than that, even
through a chain of matches.

Writes data/review/group_review_sheet.csv (candidate groups C0001 onward in date order, blank
confirmed_group_id and group_notes for hand review). It refuses to overwrite a sheet in which group
coding has begun. Also reports agreement with the 2024 pilot confirmed_group_id; the pilot files are only
read.
"""

import argparse
import re

import pandas as pd

from scoreboard.review_merge import CLASSIFICATION, MERGED, RECHECK_CODED
from scoreboard.triage import PILOT_REVIEW
from scoreboard.triage_check import REVIEW_DIR, YEARS
from scoreboard.discover import TABLES_DIR

MAX_GAP_DAYS = 3
MAX_FIGURE_DISAGREEMENTS = 1
GROUP_SHEET = REVIEW_DIR / "group_review_sheet.csv"
OUTCOMES = ("neutralised", "arrested", "rescued")
SHEET_COLUMNS = ["review_id", "decided_by", "candidate_group", "date", "outlet", "title", "period_note",
                 *OUTCOMES, "url", "confirmed_group_id", "group_notes"]

PERIOD_RULES = [
    ("year", r"year to date|end-of-year|\bannual\b|\bone year\b|last year\b"),
    ("cumulative", r"cumulative|\bsince\b|\bto date\b|so far"),
    ("quarterly", r"quarter"),
    ("monthly", r"\bmonthly\b|\bmonth\b"),
    ("biweekly", r"bi-?weekly|two[ -]weeks?|2 weeks|fortnight"),
    ("weekly", r"\bweekly\b|one[ -]week|last week|a week\b"),
]
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DAY_RANGE = re.compile(rf"(\d{{1,2}})(?: ({MONTHS}))?(?: (\d{{4}}))? to (\d{{1,2}}) ({MONTHS}) (\d{{4}})")
MONTH_RANGE = re.compile(rf"({MONTHS}) (\d{{4}}) to ({MONTHS}) (\d{{4}})")
RANGE_CLASSES = [(9, "weekly"), (17, "biweekly"), (35, "monthly"), (100, "quarterly")]

NUMBER = r"(\d{1,3}(?:,\d{3})+|\d+)\b"
VERBS = {"neutralised": r"neutrali[sz]\w*|kill\w*|eliminat\w*",
         "arrested": r"arrest\w*|apprehend\w*|nab\w*|captur\w*",
         "rescued": r"rescu\w*"}
YEAR_LIKE = re.compile(r"(?:\b(?:in|of|since)\s+)(?:19|20)\d\d\b|\b(?:19|20)\d\d(?=\s*:)", re.I)


def period_of(note: str) -> str:
    for name, pattern in PERIOD_RULES:
        if re.search(pattern, note, re.I):
            return name
    if m := DAY_RANGE.search(note):
        d1, m1, y1, d2, m2, y2 = m.groups()
        end = pd.Timestamp(f"{d2} {m2} {y2}")
        start = pd.Timestamp(f"{d1} {m1 or m2} {y1 or y2}")
        days = (end - start).days + 1
    elif m := MONTH_RANGE.search(note):
        m1, y1, m2, y2 = m.groups()
        days = (pd.Timestamp(f"1 {m2} {y2}") - pd.Timestamp(f"1 {m1} {y1}")).days + 31
    else:
        return ""
    return next((name for limit, name in RANGE_CLASSES if days <= limit), "cumulative")


def figures_of(title: str) -> dict:
    text = YEAR_LIKE.sub(" ", title)
    out = {}
    for outcome, verb in VERBS.items():
        hits = [(m.start(), m.group(1)) for m in re.finditer(rf"(?:{verb})\s+(?:over\s+|about\s+)?{NUMBER}", text, re.I)]
        hits += [(m.start(), m.group(1)) for m in re.finditer(rf"{NUMBER}\s+(?:\w+\s+){{0,2}}(?:{verb})", text, re.I)]
        if hits:
            out[outcome] = int(min(hits)[1].replace(",", ""))
    return out


def has(value) -> bool:
    """A figure is present; a missing one may be None or NaN once held in a DataFrame."""
    return value is not None and not pd.isna(value)


def candidates(a: dict, b: dict) -> bool:
    if abs((a["day"] - b["day"]).days) > MAX_GAP_DAYS:
        return False
    if a["period_note"] and b["period_note"] and a["period_note"] != b["period_note"]:
        return False
    differ = sum(1 for o in OUTCOMES if has(a[o]) and has(b[o]) and a[o] != b[o])
    return differ <= MAX_FIGURE_DISAGREEMENTS


def affinity(a: dict, b: dict) -> int:
    shared = any(has(a[o]) and has(b[o]) and a[o] == b[o] for o in OUTCOMES)
    return int(shared) + int(bool(a["period_note"]) and a["period_note"] == b["period_note"])


def assign_groups(items: pd.DataFrame) -> pd.Series:
    """Candidate group number per row, items taken in date order; see the module docstring."""
    rows = items.assign(day=pd.to_datetime(items["date"])).sort_values(["day", "outlet", "url"])
    groups: list[list[dict]] = []
    label = {}
    for idx, row in zip(rows.index, rows.to_dict("records")):
        open_groups = [g for g in groups if (row["day"] - g[0]["day"]).days <= MAX_GAP_DAYS]
        fits = [g for g in open_groups if all(candidates(row, m) for m in g)]
        if fits:
            best = max(fits, key=lambda g: sum(affinity(row, m) for m in g))
        else:
            best = []
            groups.append(best)
        best.append(row)
        label[idx] = id(best)
    order = {id(g): n for n, g in enumerate(groups, start=1)}
    return pd.Series({i: f"C{order[g]:04d}" for i, g in label.items()})


def load_items(classification_path=CLASSIFICATION, merged_path=MERGED, pilot_path=PILOT_REVIEW,
               recheck_path=RECHECK_CODED, tables_dir=TABLES_DIR) -> pd.DataFrame:
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    items = read(classification_path)
    items = items[items["is_operational_briefing"] == "yes"].copy()
    titles = pd.concat([read(tables_dir / f"full_inventory_{y}.csv")[["url", "title"]] for y in YEARS])
    items["title"] = items["url"].map(titles.set_index("url")["title"]).fillna("")
    hand = read(merged_path).set_index("url")["notes"]
    pilot = read(pilot_path).set_index("url")["notes"]
    recheck = read(recheck_path).set_index("url")["notes"]
    pilot_period = pilot.str.extract(r"^(Period: [^.]*)", expand=False).dropna()
    note = items["url"].map(hand)
    note = note.fillna(items["url"].map(pilot_period)).fillna(items["url"].map(recheck)).fillna("")
    items["period_note"] = note.map(period_of)
    figs = items["title"].map(figures_of)
    for o in OUTCOMES:
        items[o] = figs.map(lambda f: f.get(o))
    return items.reset_index(drop=True)


def build_sheet(items: pd.DataFrame) -> pd.DataFrame:
    sheet = items.assign(candidate_group=assign_groups(items), confirmed_group_id="", group_notes="")
    for o in OUTCOMES:
        sheet[o] = sheet[o].map(lambda v: "" if v is None or pd.isna(v) else str(int(v)))
    return sheet.sort_values(["candidate_group", "date", "outlet", "url"], ignore_index=True)[SHEET_COLUMNS]


def pilot_agreement(sheet: pd.DataFrame, pilot_path=PILOT_REVIEW) -> dict:
    """Per pilot confirmed group: exact (one candidate group holding exactly its pilot-grouped items),
    split (spread over more than one candidate group), merged (its candidate group also holds items of
    another pilot group); a group can be both split and merged."""
    pilot = pd.read_csv(pilot_path, keep_default_na=False, dtype=str)
    pilot = pilot.loc[pilot["confirmed_group_id"] != "", ["url", "confirmed_group_id"]]
    both = pilot.merge(sheet[["url", "candidate_group"]], on="url", how="left")
    if both["candidate_group"].isna().any():
        raise RuntimeError(f"{both['candidate_group'].isna().sum()} pilot-grouped items are not in the group sheet")
    pilot_per_candidate = both.groupby("candidate_group")["confirmed_group_id"].nunique()
    counts = {"pilot groups": 0, "exact": 0, "split only": 0, "merged only": 0, "split and merged": 0}
    for _, g in both.groupby("confirmed_group_id"):
        cands = g["candidate_group"].unique()
        split, merged = len(cands) > 1, bool((pilot_per_candidate[cands] > 1).any())
        key = "exact" if not split and not merged else "split and merged" if split and merged else (
            "split only" if split else "merged only")
        counts["pilot groups"] += 1
        counts[key] += 1
    return counts


def build(sheet_path=GROUP_SHEET, **paths) -> pd.DataFrame:
    if sheet_path.exists():
        old = pd.read_csv(sheet_path, keep_default_na=False, dtype=str)
        if (old["confirmed_group_id"] != "").any() or (old["group_notes"] != "").any():
            raise RuntimeError(f"{sheet_path} has group coding in it; not overwritten")
    sheet = build_sheet(load_items(**paths))
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(sheet_path, index=False)
    return sheet


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    sheet = build()
    sheet["year"] = sheet["date"].str[:4]
    sizes = sheet.groupby("candidate_group").agg(year=("year", "first"), first=("date", "min"), last=("date", "max"),
                                                 items=("url", "size"))
    print(f"items: {len(sheet)}; candidate groups: {len(sizes)}")
    print(sizes.groupby("year").size().to_string())
    bands = pd.cut(sizes["items"], [0, 1, 5, float("inf")], labels=["singleton", "2-5", "6+"])
    print(bands.value_counts().sort_index().to_string())
    print(sizes.sort_values(["items", "first"], ascending=[False, True]).head(10).to_string())
    print(pilot_agreement(sheet))
    print("period classes:", sheet["period_note"].replace("", "(none)").value_counts().to_dict())


if __name__ == "__main__":
    main()
