"""Inputs for the v1.0 audits: briefing periods, evidence grades per value and the checks.py briefing table.

Usage: python -m scoreboard.audit_inputs --step periods|grades|briefings

periods: writes data/briefings/briefing_periods_sheet.csv, one row per briefing in
data/briefings/full_briefings.csv, with a proposed period for hand confirmation:
- weekly and biweekly: a single date range stated in the lead (the first LEAD_CHARS characters) of the
  copies' bodies, whose length fits the class, is a "stated range"; with no stated range the period is
  inferred as 7 (weekly) or 14 (biweekly) days ending on the briefing date;
- monthly: the one month named in the copies' titles ("named month"), through extract.parse_period;
- quarterly: the quarter named in a title ("named quarter"), when extract.parse_period can read one;
- year and cumulative: no dates are proposed;
- mixed classes (period_class blank, period_classes set) and briefings with no class: basis "none".
A month or quarter later than the briefing date is taken from the previous year. needs_reading is "no"
only for an inference with no range stated in any copy, a single class-consistent stated range, or a
single named month. For the 2024 briefings the pilot's parsed period (outputs/tables/
pilot_briefings_2024.csv, through pilot_group_id) is written to period_notes as a cross-check. The sheet
is not overwritten once any confirmed column is filled.

grades: writes data/briefings/value_grades.csv, one row per reported value in
data/briefings/briefing_figures_final.csv. One rule for every value, whatever its source (Deviations,
2026-10-25): the independent copies whose body value under the "national marker" or "no region named"
rule equals the final value, with same_wire pairs and the NAN merge as in scoreboard.briefing_figures.
Grade 2 needs two or more independent copies, else grade 3; a value with no matching copy is grade 3 and
needs_review "yes". Rows of the existing file with a review_note (reviewed by hand) are kept as they are.
Grade 1 is not available: no copy is DHQ-published.

briefings: builds the checks.py briefing table (the columns of outputs/tables/pilot_briefings_2024.csv
that the checks read) as data/briefings/check_briefings.csv. It refuses to run while any needs_reading
row of the periods sheet has no confirmed period, or while any value needs review.

Rules: docs/audit_rules.md, Deviations, 2026-10-24 and 2026-10-25.
"""

import argparse
import re
from datetime import date, timedelta

import pandas as pd

from scoreboard.briefings import BRIEFINGS
from scoreboard.discover import TABLES_DIR
from scoreboard.extract import (DHQ_OUTLETS, EVIDENCE_CHARS, MONTH_NUMBERS, OUTCOMES, count_independent,
                                parse_period, same_wire_pairs, split_sentences)
from scoreboard.extraction_sheet import EXTRACTION_SHEET
from scoreboard.final_figures import FINAL_FIGURES
from scoreboard.group_candidates import DAY_RANGE, RANGE_CLASSES
from scoreboard.wirecheck import has_nan_credit, load_bodies

PERIODS_SHEET = BRIEFINGS.parent / "briefing_periods_sheet.csv"
VALUE_GRADES = BRIEFINGS.parent / "value_grades.csv"
CHECK_BRIEFINGS = BRIEFINGS.parent / "check_briefings.csv"
PILOT_BRIEFINGS = TABLES_DIR / "pilot_briefings_2024.csv"
LEAD_CHARS = 1500
INFERRED_DAYS = {"weekly": 7, "biweekly": 14}
BASES = ("inferred weekly", "inferred biweekly", "stated range", "named month", "named quarter", "year",
         "cumulative", "none")
CONFIRMED_BASES = ("inferred weekly", "inferred biweekly", "stated range", "stated duration", "named month",
                   "named quarter", "year", "year to date", "cumulative", "unclear")
# Bases whose period is never a total or a part; a cumulative period with an end date still goes through
# the period-end check.
UNDATED_BASES = ("unclear", "cumulative")
SHORT_MAX_DAYS = 27
CONFIRMED_COLUMNS = ["confirmed_start", "confirmed_end", "confirmed_basis", "period_notes"]
PERIOD_COLUMNS = ["briefing_id", "briefing_date", "period_class", "proposed_start", "proposed_end",
                  "proposed_basis", "evidence_url", "evidence_sentence", "needs_reading", *CONFIRMED_COLUMNS]
GRADE_RULES = ("national marker", "no region named")
GRADE_COLUMNS = ["briefing_id", "outcome", "value", "source", "independent_copies_supporting", "grade",
                 "supporting_urls", "needs_review", "review_note"]
MIN_INDEPENDENT = 2
MONTH_WORD_RE = re.compile(r"\b(" + "|".join(m.capitalize() for m in MONTH_NUMBERS) + r")\b", re.I)


# Periods


def range_days(start: date, end: date) -> int:
    return (end - start).days + 1


def class_of_days(days: int) -> str:
    """Period class of a stated range by its length, as scoreboard.group_candidates classes ranges."""
    return next((name for limit, name in RANGE_CLASSES if days <= limit), "cumulative")


def stated_ranges(lead: str) -> list[tuple[date, date, str]]:
    """(start, end, sentence) for each day range in the text, as group_candidates.DAY_RANGE reads it."""
    found = []
    sentences = split_sentences(lead)
    for m in DAY_RANGE.finditer(lead):
        d1, m1, y1, d2, m2, y2 = m.groups()
        try:
            end = date(int(y2), MONTH_NUMBERS[m2.lower()], int(d2))
            start = date(int(y1 or y2), MONTH_NUMBERS[(m1 or m2).lower()], int(d1))
        except ValueError:
            continue
        if start > end:
            continue
        sentence = next((s for s in sentences if m.group(0) in s), m.group(0))
        found.append((start, end, sentence[:EVIDENCE_CHARS]))
    return found


def _before_briefing(start: date, end: date, briefing: date) -> tuple[date, date]:
    """A named month or quarter later than the briefing date belongs to the previous year."""
    if start > briefing:
        start, end = start.replace(year=start.year - 1), date(end.year - 1, end.month, end.day)
    return start, end


def propose_period(briefing: dict, copies: list[dict]) -> dict:
    """Proposed period for one briefing. copies: dicts with url, title and lead (body text start)."""
    bdate = date.fromisoformat(briefing["first_date"])
    cls = briefing["period_class"]
    out = {"briefing_id": briefing["briefing_id"], "briefing_date": briefing["first_date"],
           "period_class": cls or briefing["period_classes"], "proposed_start": "", "proposed_end": "",
           "proposed_basis": "none", "evidence_url": "", "evidence_sentence": "", "needs_reading": "yes",
           **{c: "" for c in CONFIRMED_COLUMNS}}
    if cls in INFERRED_DAYS:
        ranges = {}
        for c in copies:
            for start, end, sentence in stated_ranges(c["lead"]):
                ranges.setdefault((start, end), (c["url"], sentence))
        if not ranges:
            return out | {"proposed_start": str(bdate - timedelta(days=INFERRED_DAYS[cls] - 1)),
                          "proposed_end": str(bdate), "proposed_basis": f"inferred {cls}", "needs_reading": "no"}
        (start, end), (url, sentence) = next(iter(ranges.items()))
        single = len(ranges) == 1 and class_of_days(range_days(start, end)) == cls
        return out | {"proposed_start": str(start), "proposed_end": str(end), "proposed_basis": "stated range",
                      "evidence_url": url, "evidence_sentence": sentence, "needs_reading": "no" if single else "yes"}
    if cls == "monthly":
        named = {(m.lower(), c["url"], c["title"]) for c in copies for m in MONTH_WORD_RE.findall(c["title"])}
        months = {m for m, _, _ in named}
        if len(months) != 1:
            return out
        month, url, title = sorted(named)[0]
        p = parse_period(f"monthly {month}", bdate)
        start, end = _before_briefing(p["period_start"], p["period_end"], bdate)
        return out | {"proposed_start": str(start), "proposed_end": str(end), "proposed_basis": "named month",
                      "evidence_url": url, "evidence_sentence": title[:EVIDENCE_CHARS], "needs_reading": "no"}
    if cls == "quarterly":
        for c in copies:
            try:
                p = parse_period(f"quarterly {c['title']}", bdate)
            except (StopIteration, TypeError, ValueError):
                continue
            start, end = _before_briefing(p["period_start"], p["period_end"], bdate)
            return out | {"proposed_start": str(start), "proposed_end": str(end), "proposed_basis": "named quarter",
                          "evidence_url": c["url"], "evidence_sentence": c["title"][:EVIDENCE_CHARS]}
        return out | {"proposed_basis": "named quarter"}
    if cls in ("year", "cumulative"):
        return out | {"proposed_basis": cls}
    return out


def pilot_note(pilot_row: dict | None) -> str:
    if not pilot_row:
        return ""
    return (f"Pilot {pilot_row['confirmed_group_id']}: {pilot_row['period_type']} {pilot_row['period_start']} to "
            f"{pilot_row['period_end']} ({pilot_row['period_flag']}).")


def period_sheet(briefings: pd.DataFrame, copies: pd.DataFrame, bodies: pd.Series,
                 pilot: pd.DataFrame | None = None) -> pd.DataFrame:
    pilot_by_id = {} if pilot is None else {r["confirmed_group_id"]: r for r in pilot.to_dict("records")}
    rows = []
    for b in briefings.to_dict("records"):
        mine = copies[copies["briefing_id"] == b["briefing_id"]].sort_values(["date", "outlet", "url"])
        row = propose_period(b, [{"url": u, "title": t, "lead": (bodies.get(u) or "")[:LEAD_CHARS]}
                                 for u, t in zip(mine["url"], mine["title"])])
        row["period_notes"] = pilot_note(pilot_by_id.get(b.get("pilot_group_id", "")))
        rows.append(row)
    return pd.DataFrame(rows, columns=PERIOD_COLUMNS)


# Evidence grades


def grade_of(independent: int) -> int:
    return 2 if independent >= MIN_INDEPENDENT else 3


def supporting(copies: pd.DataFrame, outcome: str, value: str, rules) -> list[str]:
    hit = copies[(copies[f"body_{outcome}"] == value) & copies[f"body_{outcome}_rule"].isin(rules)]
    return list(hit["url"])


def value_grades(final: pd.DataFrame, copies: pd.DataFrame, bodies: pd.Series,
                 reviewed: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per reported value, graded by one rule for every source. Rows of `reviewed` with a
    review_note are kept unchanged."""
    kept = {} if reviewed is None or "review_note" not in reviewed else {
        (r["briefing_id"], r["outcome"]): r for r in reviewed[reviewed["review_note"] != ""].to_dict("records")}
    rows, context = [], {}
    for f in final[final["final_status"] == "reported"].itertuples():
        if (f.briefing_id, f.outcome) in kept:
            rows.append(kept[(f.briefing_id, f.outcome)])
            continue
        mine = copies[copies["briefing_id"] == f.briefing_id]
        if f.briefing_id not in context:
            all_urls = list(mine["url"])
            context[f.briefing_id] = (same_wire_pairs(all_urls, bodies),
                                      {u for u in all_urls if has_nan_credit(bodies.get(u) or "")})
        pairs, nan_urls = context[f.briefing_id]
        urls = supporting(mine, f.outcome, f.value, GRADE_RULES)
        independent = count_independent(urls, pairs, nan_urls) if urls else 0
        rows.append({"briefing_id": f.briefing_id, "outcome": f.outcome, "value": f.value, "source": f.source,
                     "independent_copies_supporting": independent, "grade": grade_of(independent),
                     "supporting_urls": "; ".join(urls), "needs_review": "no" if urls else "yes",
                     "review_note": ""})
    out = pd.DataFrame(rows, columns=GRADE_COLUMNS)
    return out.astype({"independent_copies_supporting": int, "grade": int})


# checks.py briefing table


def unconfirmed(periods: pd.DataFrame) -> list[str]:
    """Briefings whose period cannot yet be used, one line each; empty when every period is usable."""
    failures = []
    for p in periods.itertuples():
        basis = p.confirmed_basis
        if p.needs_reading == "yes" and not basis:
            failures.append(f"{p.briefing_id}: needs reading, no confirmed period")
            continue
        if basis and basis not in CONFIRMED_BASES:
            failures.append(f"{p.briefing_id}: confirmed_basis {basis!r} not one of {', '.join(CONFIRMED_BASES)}")
        if basis and basis not in UNDATED_BASES and not (p.confirmed_start and p.confirmed_end):
            failures.append(f"{p.briefing_id}: confirmed_basis {basis!r} without confirmed_start and confirmed_end")
    return failures


def type_of_dates(start: date, end: date) -> str:
    """checks.py period_type of a stated range or duration: a calendar month, quarter or year by its dates;
    otherwise weekly (up to 9 days), biweekly (up to 17), short (up to SHORT_MAX_DAYS) or period (longer)."""
    month_end = (end + timedelta(days=1)).day == 1
    if start.day == 1 and month_end:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        if months == 1:
            return "monthly"
        if months == 3 and start.month % 3 == 1:
            return "quarterly"
        if months == 12 and start.month == 1:
            return "annual"
    days = range_days(start, end)
    return "weekly" if days <= 9 else "biweekly" if days <= 17 else "short" if days <= SHORT_MAX_DAYS else "period"


def period_fields(p: dict) -> dict:
    """period_type, dates, flag and stated end for checks.py from a usable periods-sheet row. Confirmed
    dates are used where present, otherwise the proposed dates. A stated end is the end of a named month,
    quarter or year, of a stated range, or of a cumulative period; inferred and stated-duration periods
    have none."""
    basis = p["confirmed_basis"] or p["proposed_basis"]
    start = p["confirmed_start"] or p["proposed_start"]
    end = p["confirmed_end"] or p["proposed_end"]
    if basis in UNDATED_BASES:
        period_type = basis
    elif not (start and end):
        period_type = "unclear"
    else:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
        period_type = {"inferred weekly": "weekly", "inferred biweekly": "biweekly", "named month": "monthly",
                       "named quarter": "quarterly", "year to date": "year to date"}.get(basis) or type_of_dates(s, e)
    stated = basis in ("stated range", "named month", "named quarter", "year", "cumulative") and bool(end)
    return {"period_type": period_type, "period_start": start, "period_end": end,
            "period_flag": f"{'stated' if stated else 'inferred'}: {basis}",
            "stated_period_end": end if stated else "",
            "period_label": f"{period_type} {start} to {end}" if start else period_type}


def not_ready(periods: pd.DataFrame, grades: pd.DataFrame) -> list[str]:
    """Unconfirmed periods and values needing review, one line each; empty when the inputs are ready."""
    return unconfirmed(periods) + [f"{g.briefing_id} {g.outcome}: value needs review" for g in grades.itertuples()
                                   if g.needs_review == "yes"]


def check_briefings(final: pd.DataFrame, periods: pd.DataFrame, grades: pd.DataFrame, briefings: pd.DataFrame,
                    independent_copies: dict[str, int]) -> pd.DataFrame:
    """One row per briefing in the checks.py schema. Raises ValueError while any period is unconfirmed or
    any value needs review."""
    failures = not_ready(periods, grades)
    if failures:
        raise ValueError(f"{len(failures)} inputs not ready:\n" + "\n".join(failures))
    info = briefings.set_index("briefing_id")
    values = final.set_index(["briefing_id", "outcome"])
    graded = grades.set_index(["briefing_id", "outcome"])
    rows = []
    for p in periods.to_dict("records"):
        bid = p["briefing_id"]
        row = {"confirmed_group_id": bid, "briefing_date": p["briefing_date"], **period_fields(p),
               "copies": int(info.at[bid, "items"]), "independent_copies": independent_copies[bid], "dhq_copies": 0}
        for o in OUTCOMES:
            v = values.loc[(bid, o)]
            reported = v["final_status"] == "reported"
            row |= {o: v["value"] if reported else "", f"{o}_qualifier": v["qualifier"],
                    f"{o}_final_status": v["final_status"], f"{o}_source": v["source"],
                    f"{o}_independent_copies_agreeing": int(graded.at[(bid, o), "independent_copies_supporting"])
                    if reported else 0,
                    f"{o}_dhq_text": False}
        rows.append(row)
    return pd.DataFrame(rows)


def briefing_independent_copies(copies: pd.DataFrame, bodies: pd.Series) -> dict[str, int]:
    out = {}
    for bid, g in copies.groupby("briefing_id"):
        urls = list(g["url"])
        out[bid] = count_independent(urls, same_wire_pairs(urls, bodies),
                                     {u for u in urls if has_nan_credit(bodies.get(u) or "")})
    return out


def _read(p):
    return pd.read_csv(p, keep_default_na=False, dtype=str)


def build_periods(out=PERIODS_SHEET):
    if out.exists() and (_read(out)[CONFIRMED_COLUMNS[:3]] != "").any().any():
        raise RuntimeError(f"{out} has confirmed periods in it; not overwritten")
    copies = _read(EXTRACTION_SHEET)
    if copies["outlet"].isin(DHQ_OUTLETS).any():
        raise RuntimeError("DHQ-published copies found; grade 1 rules need adding first")
    sheet = period_sheet(_read(BRIEFINGS), copies, load_bodies(copies["url"]), _read(PILOT_BRIEFINGS))
    sheet.to_csv(out, index=False)
    return sheet


def build_grades(out=VALUE_GRADES):
    copies = _read(EXTRACTION_SHEET)
    reviewed = _read(out) if out.exists() else None
    grades = value_grades(_read(FINAL_FIGURES), copies, load_bodies(copies["url"]), reviewed)
    grades.to_csv(out, index=False)
    return grades


def build_check_briefings(out=CHECK_BRIEFINGS):
    periods, grades = _read(PERIODS_SHEET), _read(VALUE_GRADES)
    # Refuse before the slow same_wire pass over every briefing.
    failures = not_ready(periods, grades)
    if failures:
        raise ValueError(f"{len(failures)} inputs not ready:\n" + "\n".join(failures))
    copies = _read(EXTRACTION_SHEET)
    table = check_briefings(_read(FINAL_FIGURES), periods, grades, _read(BRIEFINGS),
                            briefing_independent_copies(copies, load_bodies(copies["url"])))
    table.to_csv(out, index=False)
    return table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", choices=("periods", "grades", "briefings"), required=True)
    step = parser.parse_args(argv).step
    if step == "periods":
        sheet = build_periods()
        print(sheet["proposed_basis"].value_counts().to_string())
        print(f"needs_reading yes: {(sheet['needs_reading'] == 'yes').sum()} of {len(sheet)}")
    elif step == "grades":
        grades = build_grades()
        print(pd.crosstab(grades["source"], grades["grade"], margins=True).to_string())
        print(grades.loc[grades["needs_review"] == "yes", ["briefing_id", "outcome", "value", "source"]]
              .to_string(index=False))
    else:
        table = build_check_briefings()
        print(f"{len(table)} briefings written to {CHECK_BRIEFINGS}")


if __name__ == "__main__":
    main()
