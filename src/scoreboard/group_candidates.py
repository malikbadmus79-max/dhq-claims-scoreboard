"""Candidate briefing groups for every item coded yes in data/review/full_classification.csv.

Usage: python -m scoreboard.group_candidates

Each item gets a period class and headline figures:
- period: from the notes where present (hand items: data/review/full_review_coded.csv; pilot items: the
  "Period:" note in data/review/pilot_review_2024.csv, or the recheck notes in
  data/review/pilot_recheck_coded.csv when the pilot note has none); otherwise from the title; otherwise
  from the first BODY_CHARS characters of the body text in data_raw/text/. period_source records which.
  The same rules apply to all three: each rule in PERIOD_RULES ("one week", "two weeks", "in May",
  "three months", "in 2024", "so far" and similar) and each stated date range ("11 to 25 November 2021",
  classed by its length in days) is searched, and the match that starts first in the text gives the class
  (weekly, biweekly, monthly, quarterly, year, cumulative).
- figures: the first number joined to an outcome word in the title, before or after it, for neutralised
  (neutralised, killed, eliminated), arrested (arrested, apprehended, nabbed, captured) and rescued.
  Year-like numbers followed by ":" or preceded by "in", "of" or "since" are ignored.

Grouping follows the pilot rule in docs/review_guide.md (same briefing date, same reporting period;
headline figures do not decide the group). Items are taken in date order. An item may join an open
candidate group, one whose earliest item is at most MAX_GAP_DAYS before it, when its period class differs
from no member's (an item without a period conflicts with none); otherwise it starts a new group. So no
group spans more than MAX_GAP_DAYS, even through a chain of matches. Figures never keep items apart: when
an item could join more than one open group they break the tie (the group where most members share a
headline figure with it, then the earliest-starting). Within each group, outcomes whose headline figures
differ are listed in figure_flag for the headline-body check.

Writes data/review/group_review_sheet.csv (candidate groups C0001 onward in date order, blank
confirmed_group_id and group_notes for hand review). It refuses to overwrite a sheet in which group
coding has begun. Also reports agreement with the 2024 pilot confirmed_group_id; the pilot files are only
read.
"""

import argparse
import re

import pandas as pd

from scoreboard.discover import TABLES_DIR
from scoreboard.review_merge import CLASSIFICATION, MERGED, RECHECK_CODED
from scoreboard.triage import PILOT_REVIEW
from scoreboard.triage_check import REVIEW_DIR, YEARS
from scoreboard.wirecheck import text_path

MAX_GAP_DAYS = 2
BODY_CHARS = 600
GROUP_SHEET = REVIEW_DIR / "group_review_sheet.csv"
OUTCOMES = ("neutralised", "arrested", "rescued")
SHEET_COLUMNS = ["review_id", "decided_by", "candidate_group", "date", "outlet", "title", "period_note",
                 "period_source", *OUTCOMES, "figure_flag", "url", "confirmed_group_id", "group_notes"]

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
PERIOD_RULES = [
    ("year", r"year to date|end-of-year|\bannual\b|\bone year\b|\blast year\b|\bthis year\b"
             r"|\bin (?:19|20)\d\d\b|^(?:19|20)\d\d\s*:"),
    ("cumulative", r"cumulative|\bsince\b|\bto date\b|\bso far\b"),
    ("quarterly", r"\bquarter|\bthree months\b|\b3 months\b"),
    ("monthly", rf"\bmonthly\b|\bmonth\b|\bin (?:the month of )?(?:{MONTHS})\b"),
    ("biweekly", r"\bbi-?weekly\b|\btwo[ -]weeks?\b|\b2 weeks\b|\bfortnight|\b14 days\b"),
    ("weekly", r"\bweekly\b|\bone[ -]week\b|\b1 week\b|\blast week\b|\ba week\b|\bseven days\b|\b7 days\b"),
]
DAY_RANGE = re.compile(rf"(\d{{1,2}})(?: ({MONTHS}))?(?: (\d{{4}}))? to (\d{{1,2}}) ({MONTHS}) (\d{{4}})")
MONTH_RANGE = re.compile(rf"({MONTHS}) (\d{{4}}) to ({MONTHS}) (\d{{4}})")
RANGE_CLASSES = [(9, "weekly"), (17, "biweekly"), (35, "monthly"), (100, "quarterly")]

NUMBER = r"(\d{1,3}(?:,\d{3})+|\d+)\b"
VERBS = {"neutralised": r"neutrali[sz]\w*|kill\w*|eliminat\w*",
         "arrested": r"arrest\w*|apprehend\w*|nab\w*|captur\w*",
         "rescued": r"rescu\w*"}
YEAR_LIKE = re.compile(r"(?:\b(?:in|of|since)\s+)(?:19|20)\d\d\b|\b(?:19|20)\d\d(?=\s*:)", re.I)


def range_class(m: re.Match) -> str:
    if m.re is DAY_RANGE:
        d1, m1, y1, d2, m2, y2 = m.groups()
        days = (pd.Timestamp(f"{d2} {m2} {y2}") - pd.Timestamp(f"{d1} {m1 or m2} {y1 or y2}")).days + 1
    else:
        m1, y1, m2, y2 = m.groups()
        days = (pd.Timestamp(f"1 {m2} {y2}") - pd.Timestamp(f"1 {m1} {y1}")).days + 31
    return next((name for limit, name in RANGE_CLASSES if days <= limit), "cumulative")


def period_of(text: str) -> str:
    """The period class of the match that starts first in text, or "" if none matches."""
    hits = [(m.start(), name) for name, pattern in PERIOD_RULES if (m := re.search(pattern, text, re.I | re.M))]
    hits += [(m.start(), range_class(m)) for r in (DAY_RANGE, MONTH_RANGE) if (m := r.search(text))]
    return min(hits)[1] if hits else ""


def period_with_source(note: str, title: str, body: str) -> tuple[str, str]:
    for source, text in (("notes", note), ("title", title), ("body", body[:BODY_CHARS])):
        if period := period_of(text):
            return period, source
    return "", "none"


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
    return not (a["period_note"] and b["period_note"] and a["period_note"] != b["period_note"])


def shares_figure(a: dict, b: dict) -> bool:
    return any(has(a[o]) and has(b[o]) and a[o] == b[o] for o in OUTCOMES)


def assign_groups(items: pd.DataFrame) -> pd.Series:
    """Candidate group number per row, items taken in date order; see the module docstring."""
    rows = items.assign(day=pd.to_datetime(items["date"])).sort_values(["day", "outlet", "url"])
    groups: list[list[dict]] = []
    label = {}
    for idx, row in zip(rows.index, rows.to_dict("records")):
        open_groups = [g for g in groups if (row["day"] - g[0]["day"]).days <= MAX_GAP_DAYS]
        fits = [g for g in open_groups if all(candidates(row, m) for m in g)]
        if fits:
            best = max(fits, key=lambda g: sum(shares_figure(row, m) for m in g))
        else:
            best = []
            groups.append(best)
        best.append(row)
        label[idx] = id(best)
    order = {id(g): n for n, g in enumerate(groups, start=1)}
    return pd.Series({i: f"C{order[g]:04d}" for i, g in label.items()})


def figure_flags(sheet: pd.DataFrame) -> pd.Series:
    """Per row, the outcomes on which its candidate group's headline figures differ, e.g.
    "arrested: 1,326 vs 1,903"; blank when they agree."""
    def flag(group):
        parts = []
        for o in OUTCOMES:
            values = sorted({int(v) for v in group[o] if has(v)})
            if len(values) > 1:
                parts.append(f"{o}: " + " vs ".join(f"{v:,}" for v in values))
        return "; ".join(parts)
    return sheet["candidate_group"].map(sheet.groupby("candidate_group")[list(OUTCOMES)].apply(flag))


def load_items(classification_path=CLASSIFICATION, merged_path=MERGED, pilot_path=PILOT_REVIEW,
               recheck_path=RECHECK_CODED, tables_dir=TABLES_DIR, text_path=text_path) -> pd.DataFrame:
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

    def body(url):
        path = text_path(url)
        return path.read_text(encoding="utf-8")[:BODY_CHARS] if path.exists() else ""

    periods = [period_with_source(n, t, body(u)) for n, t, u in zip(note, items["title"], items["url"])]
    items["period_note"] = [p for p, _ in periods]
    items["period_source"] = [s for _, s in periods]
    figs = items["title"].map(figures_of)
    for o in OUTCOMES:
        items[o] = figs.map(lambda f: f.get(o))
    return items.reset_index(drop=True)


def build_sheet(items: pd.DataFrame) -> pd.DataFrame:
    sheet = items.assign(candidate_group=assign_groups(items), confirmed_group_id="", group_notes="")
    sheet["figure_flag"] = figure_flags(sheet)
    for o in OUTCOMES:
        sheet[o] = sheet[o].map(lambda v: str(int(v)) if has(v) else "")
    return sheet.sort_values(["candidate_group", "date", "outlet", "url"], ignore_index=True)[SHEET_COLUMNS]


def pilot_agreement(sheet: pd.DataFrame, pilot_path=PILOT_REVIEW) -> dict:
    """Per pilot confirmed group: exact (one candidate group holding exactly its pilot-grouped items),
    split (spread over more than one candidate group), merged (its candidate group also holds items of
    another pilot group); a group can be both split and merged. Also pairs of pilot-grouped items: pilot
    pairs kept in one candidate group, and candidate pairs that cross two pilot groups."""
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
    pairs = lambda key: both.merge(both, on=key).query("url_x < url_y")
    same_pilot, same_candidate = pairs("confirmed_group_id"), pairs("candidate_group")
    counts["pilot pairs"] = len(same_pilot)
    counts["pilot pairs kept together"] = int((same_pilot["candidate_group_x"] == same_pilot["candidate_group_y"]).sum())
    counts["candidate pairs crossing pilot groups"] = int(
        (same_candidate["confirmed_group_id_x"] != same_candidate["confirmed_group_id_y"]).sum())
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
    sizes = sheet.groupby("candidate_group").agg(
        year=("year", "first"), first=("date", "min"), last=("date", "max"), items=("url", "size"),
        periods=("period_note", lambda p: ", ".join(sorted(set(p.replace("", "(none)"))))),
        flagged=("figure_flag", lambda f: (f != "").any()))
    print(f"items: {len(sheet)}; candidate groups: {len(sizes)}; groups with a figure_flag: {int(sizes['flagged'].sum())}")
    print(sizes.groupby("year").size().to_string())
    bands = pd.cut(sizes["items"], [0, 1, 5, float("inf")], labels=["singleton", "2-5", "6+"])
    print(bands.value_counts().sort_index().to_string())
    print(pilot_agreement(sheet))
    print("period source:", sheet["period_source"].value_counts().to_dict())
    print("period classes:", sheet["period_note"].replace("", "(none)").value_counts().to_dict())
    span = pd.to_datetime(sizes["last"]) - pd.to_datetime(sizes["first"])
    mixed = sizes[(sizes["periods"].str.contains(",")) | (span.dt.days > 1)]
    print(f"\ngroups with more than one period class or spanning more than one day: {len(mixed)}")
    print(mixed.drop(columns=["year", "flagged"]).to_string())


if __name__ == "__main__":
    main()
