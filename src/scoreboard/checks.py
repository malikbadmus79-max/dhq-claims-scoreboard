"""Arithmetic and plausibility checks on the pilot briefing and operation tables.

Usage: python -m scoreboard.checks --year 2024

Reads outputs/tables/pilot_briefings_<year>.csv and pilot_operations_<year>.csv and writes
outputs/tables/pilot_checks_<year>.csv and pilot_week_coverage_<year>.csv. The rules are set
out in docs/audit_rules.md.

  a. within_briefing: sum of operation figures against the stated national total.
  b. quarter_months, month_weeks, annual: a period total against the sum of the totals of
     the shorter periods inside it (period rule).
  b. implied_residual: with weeks missing, the total minus the known weeklies, per missing
     week, against the largest weekly figure of the same calendar year.
  b. coverage_variant: a monthly or quarterly total against the sum of the weekly briefings
     dated within its period.
  c. period_end: a total announced before the end of the period it names.

Parts (Deviations, 2026-10-24): weekly, biweekly and other short briefings (PART_TYPES) count as parts
under the period rule and the coverage variant. Monthly totals and other stated totals longer than a short
briefing (TOTAL_TYPES) are compared with the parts inside them. The implied-residual reference figure stays
the largest weekly figure. With missing_by="period" the coverage variant counts as missing the weeks whose
Thursday no part's period covers; the pilot default ("date") counts weeks with no weekly briefing dated in
them. Briefings with no period dates (unclear, cumulative) are never totals or parts.

Overlapping parts (Deviations, 2026-10-25; on with overlap_days=1, off in the pilot run): parts whose
periods share at most overlap_days days are summed as adjacent. A row that would sum parts overlapping by
more than that is "not testable" with reason "overlapping parts", unless a set of non-overlapping parts
alone exceeds the total (then the usual gap test applies to that set's sum).

Status:
  consistent           both sides complete and equal (a and b), the period had ended (c), or
                       the implied residual is within the largest weekly figure.
  gap                  both sides complete and different; or, with parts missing, the parts
                       present already exceed the total; or the total was announced before the
                       period ended (c).
  implausible residual the implied value per missing week exceeds the largest weekly figure.
  not testable         a side has no value, or parts are missing and the parts present do not
                       exceed the total.

Evidence grade (worst over every figure in the row): 1 = DHQ's own text; 2 = two or more
independent copies; 3 = one independent copy. Grade 3 rows are media-relay level.
"""

import argparse
import calendar
from itertools import combinations
from datetime import date, timedelta

import pandas as pd

from scoreboard.discover import TABLES_DIR
from scoreboard.extract import MINOR_SHARE, OPERATION_BRIEFINGS, OPERATION_OUTCOMES, OUTCOMES

MIN_COPIES = 2
DATE_COLUMNS = ["briefing_date", "period_start", "period_end", "stated_period_end"]
CHECK_COLUMNS = [
    "check_id",
    "check",
    "subject",
    "outcome",
    "side_a",
    "side_a_value",
    "side_b",
    "side_b_value",
    "difference",
    "side_a_2plus_copies",
    "side_b_2plus_copies",
    "both_sides_2plus_copies",
    "missing_parts",
    "incomplete_parts",
    "implied_per_missing_week",
    "largest_weekly_figure",
    "residual_ratio",
    "complete_set_stated",
    "status",
    "evidence_grade",
    "label",
    "note",
    "reason",
]
# MINOR_SHARE (imported from scoreboard.extract) sets the minor-difference threshold.
# Years whose data set the extraction rules and the same_wire threshold.
PART_TYPES = ("weekly", "biweekly", "short")
TOTAL_TYPES = ("monthly", "period")
DEVELOPMENT_YEARS = {2024}
DEVELOPMENT_LABEL = "development year"
WEEK_COLUMNS = ["iso_week", "week_start", "week_end", "weekly_found", "weekly_briefings", "other_briefings"]


def load_briefings(path) -> pd.DataFrame:
    df = pd.read_csv(path, keep_default_na=False)
    for col in DATE_COLUMNS:
        df[col] = df[col].map(lambda v: date.fromisoformat(v) if v else None)
    for outcome in OUTCOMES:
        df[outcome] = df[outcome].map(lambda v: None if v == "" else int(v))
    return df


def load_operations(path) -> pd.DataFrame:
    df = pd.read_csv(path, keep_default_na=False)
    for outcome in OPERATION_OUTCOMES:
        df[outcome] = df[outcome].map(lambda v: None if v == "" else int(v))
    return df


def effective_end(row) -> date | None:
    """The earlier of the stated (else inferred) period end and the briefing date; None without a period."""
    end = row.get("stated_period_end") or row["period_end"]
    return min(end, row["briefing_date"]) if end else None


def with_effective_end(briefings: pd.DataFrame) -> pd.DataFrame:
    """Briefings with period_end replaced by the effective end, for the arithmetic checks. The
    original end is kept as period_end_given."""
    df = briefings.copy()
    df["period_end_given"] = df["period_end"]
    df["period_end"] = [effective_end(r) for r in df.to_dict("records")]
    return df


def gap_or_minor(a: int, b: int) -> str:
    """"minor difference" when |a - b| is at most MINOR_SHARE of the larger side, else "gap"."""
    return "minor difference" if abs(a - b) <= MINOR_SHARE * max(abs(a), abs(b)) else "gap"


def _records(df: pd.DataFrame) -> list[dict]:
    """Rows as dicts with outcome values as int, or None when missing (NaN in a frame built in memory)."""
    rows = df.to_dict("records")
    for r in rows:
        for outcome in OUTCOMES:
            if outcome in r:
                r[outcome] = None if pd.isna(r[outcome]) else int(r[outcome])
    return rows


def _copies(row, outcome) -> int:
    return int(row[f"{outcome}_independent_copies_agreeing"] or 0)


def part_grade(row, outcome) -> int:
    """Evidence grade of one figure: 1 DHQ's own text, 2 two or more independent copies, 3 otherwise."""
    if row.get(f"{outcome}_dhq_text") is True:
        return 1
    return 2 if _copies(row, outcome) >= MIN_COPIES else 3


def grade(rows, outcome) -> int:
    """A row's grade is its weakest figure's grade. A row with no figures is grade 3."""
    return max((part_grade(r, outcome) for r in rows), default=3)


def _qualifiers(rows, outcome) -> list[str]:
    return [f"{r['confirmed_group_id'] if 'operation' not in r else r['operation']}: {r[f'{outcome}_qualifier']}"
            for r in rows if r.get(f"{outcome}_qualifier")]


def _listing(rows, outcome) -> str:
    return ", ".join(
        f"{r['confirmed_group_id']} {'no value' if r[outcome] is None else r[outcome]}" for r in rows
    ) or "none"


def compare(total: int | None, parts: list[int | None], complete: bool) -> tuple[int | None, int | None, str]:
    """Side B value (sum of the parts present), difference (A minus B) and status."""
    present = [p for p in parts if p is not None]
    side_b = sum(present) if present else None
    if total is None or side_b is None:
        return None, side_b, "not testable"
    diff = total - side_b
    if complete and len(present) == len(parts):
        return diff, side_b, "consistent" if diff == 0 else gap_or_minor(total, side_b)
    return diff, side_b, gap_or_minor(total, side_b) if side_b > total else "not testable"


def coverage(windows: list[tuple[date, date]], start: date, end: date) -> dict:
    """Days of [start, end] covered by the windows; windows reaching outside; missing full weeks
    and incomplete stretches among the uncovered runs of days."""
    covered = set()
    outside = 0
    for s, e in windows:
        if s < start or e > end:
            outside += 1
        d = max(s, start)
        while d <= min(e, end):
            covered.add(d)
            d += timedelta(days=1)
    runs, run = [], 0
    d = start
    while d <= end:
        if d in covered:
            if run:
                runs.append(run)
            run = 0
        else:
            run += 1
        d += timedelta(days=1)
    if run:
        runs.append(run)
    return {
        "days": (end - start).days + 1,
        "days_covered": len(covered),
        "outside": outside,
        "missing_weeks": sum(r // 7 for r in runs),
        "incomplete": outside + sum(1 for r in runs if r % 7),
    }


def _row(check_id, check, subject, outcome, side_a, a, side_b, b, diff, a_ok, b_ok, status, note="",
         missing="", incomplete="", evidence_grade=3, per_week="", largest="", ratio="", complete_set="",
         reason=""):
    return {
        "check_id": check_id,
        "check": check,
        "subject": subject,
        "outcome": outcome,
        "side_a": side_a,
        "side_a_value": a,
        "side_b": side_b,
        "side_b_value": b,
        "difference": diff,
        "side_a_2plus_copies": a_ok,
        "side_b_2plus_copies": b_ok,
        "both_sides_2plus_copies": bool(a_ok and b_ok),
        "missing_parts": missing,
        "incomplete_parts": incomplete,
        "implied_per_missing_week": per_week,
        "largest_weekly_figure": largest,
        "residual_ratio": ratio,
        "complete_set_stated": complete_set,
        "status": status,
        "evidence_grade": evidence_grade,
        "label": "",
        "note": note,
        "reason": reason,
    }


# Overlapping parts

OVERLAP_REASON = "overlapping parts"


def overlap_days_between(a: dict, b: dict) -> int:
    return (min(a["period_end"], b["period_end"]) - max(a["period_start"], b["period_start"])).days + 1


def overlapping_pairs(parts: list[dict], tolerance: int) -> list[tuple[str, str]]:
    """Pairs of parts whose periods share more than `tolerance` days."""
    return [(a["confirmed_group_id"], b["confirmed_group_id"]) for a, b in combinations(parts, 2)
            if overlap_days_between(a, b) > tolerance]


def best_disjoint_sum(parts: list[dict], outcome: str, tolerance: int) -> int:
    """Largest sum of `outcome` over a set of parts no two of which share more than `tolerance` days
    (weighted interval scheduling; parts without a value add nothing)."""
    ordered = sorted(parts, key=lambda p: p["period_end"])
    best = [0] * (len(ordered) + 1)
    for i, p in enumerate(ordered, 1):
        prev = max((j for j in range(i - 1) if overlap_days_between(ordered[j], p) <= tolerance), default=-1)
        best[i] = max(best[i - 1], best[prev + 1] + (p[outcome] or 0))
    return best[-1]


def apply_overlaps(row: dict, total: int | None, base_rows: list[dict], parts: list[dict], outcome: str,
                   tolerance: int | None) -> dict:
    """With overlap checking on, a row whose parts overlap by more than `tolerance` days becomes not
    testable (reason "overlapping parts") unless non-overlapping parts plus the base already exceed the
    total."""
    pairs = overlapping_pairs(parts, tolerance) if tolerance is not None else []
    if not pairs or total is None:
        return row
    listed = ", ".join(f"{a}/{b}" for a, b in pairs)
    disjoint = sum(b[outcome] or 0 for b in base_rows) + best_disjoint_sum(parts, outcome, tolerance)
    row = {**row, "implied_per_missing_week": "", "residual_ratio": ""}
    if disjoint > total:
        row |= {"status": gap_or_minor(total, disjoint), "side_b_value": disjoint, "difference": total - disjoint,
                "note": f"{row['note']} Parts overlap by more than {tolerance} day ({listed}); non-overlapping "
                        f"parts{' plus the base' if base_rows else ''} sum to {disjoint}, above the total."}
    else:
        row |= {"status": "not testable", "difference": None, "reason": OVERLAP_REASON,
                "note": f"{row['note']} Not testable: parts overlap by more than {tolerance} day ({listed})."}
    return row


# a. Within a briefing


def within_briefing_checks(briefings: pd.DataFrame, operations: pd.DataFrame, groups: list[str]) -> list[dict]:
    rows = []
    by_id = briefings.set_index("confirmed_group_id")
    for gid in groups:
        b = _records(by_id.loc[[gid]].reset_index())[0]
        ops = _records(operations[operations["confirmed_group_id"] == gid])
        for outcome in OPERATION_OUTCOMES:
            with_value = [o for o in ops if o[outcome] is not None]
            diff, side_b, status = compare(b[outcome], [o[outcome] for o in with_value], complete=True)
            if not with_value:
                status = "not testable"
            status = direction_status(status, b[outcome], side_b)
            complete_set = b.get("operations_complete_set_stated") or ""
            names = ", ".join(f"{o['operation']} {o[outcome]}" for o in with_value)
            without = [o["operation"] for o in ops if o[outcome] is None]
            notes = [f"Operations: {names}." if names else "No operation figures."]
            if complete_set:
                notes.append(f"Text states the listed operations are the complete set: {complete_set}.")
            if without:
                notes.append(f"No {outcome} figure for {', '.join(without)}.")
            quals = _qualifiers(with_value, outcome)
            if quals:
                notes.append(f"Qualifiers: {'; '.join(quals)}.")
            rows.append(_row(
                "", "a. within_briefing", f"{gid} ({b['period_label']})", outcome,
                f"{gid} national total", b[outcome],
                f"sum of {len(with_value)} operation figures", side_b, diff,
                _copies(b, outcome) >= MIN_COPIES,
                bool(with_value) and all(_copies(o, outcome) >= MIN_COPIES for o in with_value),
                status, " ".join(notes),
                evidence_grade=max(grade([b], outcome), grade(with_value, outcome)),
                complete_set=complete_set,
            ))
    return rows


PARTS_EXCEED = "gap (parts exceed total)"
SHORTFALL = "shortfall (listed operations may be incomplete)"


def direction_status(status: str, total: int | None, parts_sum: int | None) -> str:
    """Within-briefing direction: a gap becomes "gap (parts exceed total)" when the operation
    sum is larger, and a shortfall when the national total is larger."""
    if status != "gap":
        return status
    return PARTS_EXCEED if parts_sum > total else SHORTFALL


# b. Across briefings


def _month_key(d: date) -> tuple[int, int]:
    return d.year, d.month


def quarter_checks(briefings: pd.DataFrame) -> list[dict]:
    rows = []
    monthly: dict[tuple[int, int], list[dict]] = {}
    for r in _records(briefings[briefings["period_type"] == "monthly"]):
        monthly.setdefault(_month_key(r["period_start"]), []).append(r)
    for q in _records(briefings[briefings["period_type"] == "quarterly"]):
        months = [(q["period_start"].year, m) for m in range(q["period_start"].month, q["period_end"].month + 1)]
        # A month counts only when it lies wholly inside the quarter's effective period.
        inside = [calendar.monthrange(y, m)[1] <= q["period_end"].day or m < q["period_end"].month
                  for y, m in months]
        candidates = [monthly.get(m, []) if ok else [] for m, ok in zip(months, inside)]
        missing = [calendar.month_name[m] + ("" if ok else f" (effective period ends {q['period_end']})")
                   for (_, m), c, ok in zip(months, candidates, inside) if not c]
        present = [r for c in candidates for r in c]
        for outcome in OUTCOMES:
            values, disagree = [], []
            for (_, m), c in zip(months, candidates):
                distinct = {r[outcome] for r in c}
                values.append(distinct.pop() if len(distinct) == 1 else None)
                if len(distinct) > 1:
                    disagree.append(calendar.month_name[m])
            diff, side_b, status = compare(q[outcome], values, complete=not missing and not disagree)
            notes = [f"Monthly briefings: {_listing(present, outcome)}."]
            if missing:
                notes.append(f"No monthly briefing for {', '.join(missing)}.")
            if disagree:
                notes.append(f"Monthly briefings for {', '.join(disagree)} give different values; month not used.")
            if q["stated_period_end"] and q["stated_period_end"] > q["briefing_date"]:
                notes.append(f"Quarter total announced on {q['briefing_date']}, before the quarter ended.")
            quals = _qualifiers([q, *present], outcome)
            if quals:
                notes.append(f"Qualifiers: {'; '.join(quals)}.")
            rows.append(_row(
                "", "b. quarter_months", f"{q['confirmed_group_id']} ({q['period_label']})", outcome,
                f"{q['confirmed_group_id']} quarter total", q[outcome],
                f"sum of {len(present)} of {len(months)} monthly totals", side_b, diff,
                _copies(q, outcome) >= MIN_COPIES,
                bool(present) and all(_copies(p, outcome) >= MIN_COPIES for p in present),
                status, " ".join(notes), missing=len(missing), incomplete="",
                evidence_grade=max(grade([q], outcome), grade(present, outcome)),
            ))
    return rows


def _short_parts(briefings: pd.DataFrame, start: date, end: date) -> list[dict]:
    """Weekly, biweekly and other short briefings dated between start and end."""
    short = briefings[briefings["period_type"].isin(PART_TYPES)]
    inside = short[(short["briefing_date"] >= start) & (short["briefing_date"] <= end)]
    return _records(inside.sort_values("briefing_date"))


def _sum_against_weeklies(check, subject, total_row, total_label, base_rows, weeklies, start, end, outcome,
                          overlap_days=None):
    """Total against base totals (none for a month; the 11-month total for the year) plus the
    weekly totals dated between start and end."""
    cov = coverage([(w["period_start"], w["period_end"]) for w in weeklies], start, end)
    parts = [*base_rows, *weeklies]
    values = [p[outcome] for p in parts]
    complete = cov["missing_weeks"] == 0 and cov["incomplete"] == 0
    diff, side_b, status = compare(total_row[outcome], values, complete)
    notes = []
    if base_rows:
        notes.append(f"Base: {_listing(base_rows, outcome)}.")
    notes.append(f"Short briefings: {_listing(weeklies, outcome)}.")
    notes.append(
        f"Their periods (stated or inferred) cover {cov['days_covered']} of "
        f"{cov['days']} days from {start} to {end}; {cov['outside']} reach outside that window."
    )
    if not complete and total_row[outcome] is not None:
        # With weeks missing, only weeklies whose inferred period lies wholly inside the window
        # can show a gap: together with the base they cannot exceed the total.
        inner = [w for w in weeklies if w["period_start"] >= start and w["period_end"] <= end]
        inner_sum = sum(v for v in [*(p[outcome] for p in base_rows), *(w[outcome] for w in inner)] if v is not None)
        status = gap_or_minor(total_row[outcome], inner_sum) if inner_sum > total_row[outcome] else "not testable"
        notes.append(f"Base plus short briefings wholly inside the window: {inner_sum}." if base_rows
                     else f"Short briefings wholly inside the period: {inner_sum}.")
    if any(v is None for v in values):
        notes.append("A part has no value for this outcome.")
    quals = _qualifiers([total_row, *parts], outcome)
    if quals:
        notes.append(f"Qualifiers: {'; '.join(quals)}.")
    base_label = f"{base_rows[0]['confirmed_group_id']} total plus " if base_rows else ""
    row = _row(
        "", check, subject, outcome,
        total_label, total_row[outcome],
        f"{base_label}sum of {len(weeklies)} short-briefing totals", side_b, diff,
        _copies(total_row, outcome) >= MIN_COPIES,
        bool(parts) and all(_copies(p, outcome) >= MIN_COPIES for p in parts),
        status, " ".join(notes), missing=cov["missing_weeks"], incomplete=cov["incomplete"],
        evidence_grade=max(grade([total_row], outcome), grade(parts, outcome)),
    )
    return apply_overlaps(row, total_row[outcome], base_rows, weeklies, outcome, overlap_days)


# b. Implied residual (period rule, weeks missing)


def largest_weekly(briefings: pd.DataFrame, year: int, outcome: str) -> dict | None:
    """The weekly briefing with the largest figure for `outcome` dated in `year`."""
    weekly = [w for w in _records(briefings[briefings["period_type"] == "weekly"])
              if w["briefing_date"].year == year and w[outcome] is not None]
    return max(weekly, key=lambda w: w[outcome], default=None)


def implied_residual(check_subject, total_row, total_label, base_rows, weeklies, start, end, outcome, largest,
                     overlap_days=None):
    """Total minus the known parts (base plus weeklies wholly inside [start, end]), divided by the
    missing weeks (days of the window not covered by those weeklies, over 7). None when no day
    is missing."""
    inner = [w for w in weeklies if w["period_start"] >= start and w["period_end"] <= end]
    cov = coverage([(w["period_start"], w["period_end"]) for w in inner], start, end)
    uncovered = cov["days"] - cov["days_covered"]
    if uncovered == 0:
        return None
    missing_weeks = uncovered / 7
    known = [*base_rows, *inner]
    total = total_row[outcome]
    values = [k[outcome] for k in known]
    notes = [
        f"Known parts: {_listing(known, outcome)}.",
        f"{uncovered} of {cov['days']} days from {start} to {end} are not covered by the periods "
        f"of short briefings wholly inside the window ({missing_weeks:.2f} weeks).",
    ]
    per_week, ratio, side_b, diff = "", "", None, None
    largest_value = largest[outcome] if largest else ""
    if largest:
        notes.append(f"Largest weekly {outcome} figure in {largest['briefing_date'].year}: "
                     f"{largest['confirmed_group_id']} {largest[outcome]}.")
    if total is None or any(v is None for v in values) or not largest:
        status = "not testable"
        if any(v is None for v in values):
            notes.append("A known part has no value for this outcome.")
    else:
        side_b = sum(values)
        diff = total - side_b
        if diff < 0:
            status = gap_or_minor(total, side_b)
        else:
            per_week = round(diff / missing_weeks, 1)
            ratio = round(per_week / largest[outcome], 2)
            status = "implausible residual" if per_week > largest[outcome] else "consistent"
    return apply_overlaps(_row(
        "", "b. implied_residual", check_subject, outcome,
        total_label, total, f"sum of {len(known)} known parts", side_b, diff,
        _copies(total_row, outcome) >= MIN_COPIES,
        bool(known) and all(_copies(k, outcome) >= MIN_COPIES for k in known),
        status, " ".join(notes), missing=round(missing_weeks, 2), incomplete="",
        evidence_grade=max(grade([total_row], outcome), grade(known, outcome)),
        per_week=per_week, largest=largest_value, ratio=ratio,
    ), total, base_rows, inner, outcome, overlap_days)


def residual_checks(briefings: pd.DataFrame, overlap_days: int | None = None) -> list[dict]:
    rows = []
    windows = [(m, [], m["period_start"], m["period_end"], f"{m['confirmed_group_id']} {m['period_type']} total")
               for m in _records(briefings[briefings["period_type"].isin(TOTAL_TYPES)])]
    ytd = _records(briefings[briefings["period_type"] == "year to date"])
    for a in _records(briefings[briefings["period_type"] == "annual"]):
        base = [y for y in ytd if y["period_start"].year == a["period_start"].year]
        if base:
            windows.append((a, [base[-1]], base[-1]["period_end"] + timedelta(days=1), a["period_end"],
                            f"{a['confirmed_group_id']} annual total"))
    for total_row, base, start, end, label in windows:
        weeklies = _short_parts(briefings, start, end)
        for outcome in OUTCOMES:
            row = implied_residual(
                f"{total_row['confirmed_group_id']} ({total_row['period_label']})", total_row, label,
                base, weeklies, start, end, outcome, largest_weekly(briefings, end.year, outcome), overlap_days,
            )
            if row:
                rows.append(row)
    return rows


# b. Coverage-based variant


def iso_weeks(start: date, end: date) -> list[tuple[date, date]]:
    """Monday-to-Sunday weeks whose Thursday falls in [start, end]."""
    monday = start - timedelta(days=start.weekday())
    weeks = []
    while monday <= end:
        if start <= monday + timedelta(days=3) <= end:
            weeks.append((monday, monday + timedelta(days=6)))
        monday += timedelta(days=7)
    return weeks


def coverage_variant_checks(briefings: pd.DataFrame, missing_by: str = "date",
                            overlap_days: int | None = None) -> list[dict]:
    """A monthly or quarterly total taken as the sum of the short briefings dated within its period.
    Missing weeks are weeks (Thursday inside the period) with no such briefing dated in them
    (missing_by "date") or whose Thursday no such briefing's period covers (missing_by "period"); with
    weeks missing and the sum below the total, the row is not testable."""
    rows = []
    totals = _records(briefings[briefings["period_type"].isin(["monthly", "quarterly"])])
    for t in totals:
        start, end = t["period_start"], t["period_end"]
        weeklies = _short_parts(briefings, start, end)
        if missing_by == "period":
            missing = [w for w in iso_weeks(start, end)
                       if not any(x["period_start"] <= w[0] + timedelta(days=3) <= x["period_end"] for x in weeklies)]
        else:
            missing = [w for w in iso_weeks(start, end)
                       if not any(w[0] <= x["briefing_date"] <= w[1] for x in weeklies)]
        for outcome in OUTCOMES:
            values = [w[outcome] for w in weeklies]
            total = t[outcome]
            side_b = sum(v for v in values if v is not None) if weeklies else None
            diff = None
            if total is None or not weeklies or any(v is None for v in values):
                status = "not testable"
            else:
                diff = total - side_b
                if diff == 0:
                    status = "consistent"
                elif side_b > total or not missing:
                    status = gap_or_minor(total, side_b)
                else:
                    status = "not testable"
            notes = [f"Short briefings dated within the period: {_listing(weeklies, outcome)}."]
            if missing:
                notes.append("Weeks with no short briefing found: "
                             f"{', '.join(f'{m[0].isocalendar()[0]}-W{m[0].isocalendar()[1]:02d}' for m in missing)}.")
            if any(v is None for v in values):
                notes.append("A part has no value for this outcome.")
            rows.append(apply_overlaps(_row(
                "", "b. coverage_variant", f"{t['confirmed_group_id']} ({t['period_label']})", outcome,
                f"{t['confirmed_group_id']} {t['period_type']} total", total,
                f"sum of {len(weeklies)} short-briefing totals dated within the period", side_b, diff,
                _copies(t, outcome) >= MIN_COPIES,
                bool(weeklies) and all(_copies(w, outcome) >= MIN_COPIES for w in weeklies),
                status, " ".join(notes), missing=len(missing), incomplete="",
                evidence_grade=max(grade([t], outcome), grade(weeklies, outcome)),
            ), total, [], weeklies, outcome, overlap_days))
    return rows


def week_coverage(briefings: pd.DataFrame, year: int) -> pd.DataFrame:
    """One row per Monday-to-Sunday week overlapping `year`, with the briefings dated in it."""
    records = _records(briefings)
    monday = date(year, 1, 1) - timedelta(days=date(year, 1, 1).weekday())
    rows = []
    while monday <= date(year, 12, 31):
        sunday = monday + timedelta(days=6)
        inside = [r for r in records if monday <= r["briefing_date"] <= sunday]
        weekly = [r["confirmed_group_id"] for r in inside if r["period_type"] == "weekly"]
        other = [f"{r['confirmed_group_id']} ({r['period_type']})" for r in inside if r["period_type"] != "weekly"]
        iso = monday.isocalendar()
        rows.append({
            "iso_week": f"{iso[0]}-W{iso[1]:02d}",
            "week_start": monday,
            "week_end": sunday,
            "weekly_found": bool(weekly),
            "weekly_briefings": "; ".join(weekly),
            "other_briefings": "; ".join(other),
        })
        monday += timedelta(days=7)
    return pd.DataFrame(rows, columns=WEEK_COLUMNS)


def month_week_checks(briefings: pd.DataFrame, overlap_days: int | None = None) -> list[dict]:
    """A monthly total (check "b. month_weeks") or another stated total longer than a short briefing
    ("b. period_parts") against the short briefings dated inside it."""
    rows = []
    for m in _records(briefings[briefings["period_type"].isin(TOTAL_TYPES)]):
        start, end = m["period_start"], m["period_end"]
        weeklies = _short_parts(briefings, start, end)
        check = "b. month_weeks" if m["period_type"] == "monthly" else "b. period_parts"
        for outcome in OUTCOMES:
            rows.append(_sum_against_weeklies(
                check, f"{m['confirmed_group_id']} ({m['period_label']})", m,
                f"{m['confirmed_group_id']} {m['period_type']} total", [], weeklies, start, end, outcome,
                overlap_days,
            ))
    return rows


def annual_checks(briefings: pd.DataFrame, overlap_days: int | None = None) -> list[dict]:
    rows = []
    annual = _records(briefings[briefings["period_type"] == "annual"])
    ytd = _records(briefings[briefings["period_type"] == "year to date"])
    for a in annual:
        base = [y for y in ytd if y["period_start"].year == a["period_start"].year]
        if not base:
            continue
        base = base[-1]
        start = base["period_end"] + timedelta(days=1)
        end = a["period_end"]
        weeklies = _short_parts(briefings, start, end)
        for outcome in OUTCOMES:
            row = _sum_against_weeklies(
                "b. annual", f"{a['confirmed_group_id']} ({a['period_label']})", a,
                f"{a['confirmed_group_id']} annual total", [base], weeklies, start, end, outcome, overlap_days,
            )
            row["note"] += (
                f" {base['confirmed_group_id']} period taken as {base['period_start']} to {base['period_end']}"
                f" (effective end: earlier of the stated or inferred end and the briefing date)."
            )
            rows.append(row)
    return rows


# c. Period end after the briefing date


def period_checks(briefings: pd.DataFrame) -> list[dict]:
    rows = []
    for b in _records(briefings[briefings["stated_period_end"].notna()]):
        end = b["stated_period_end"]
        days = (end - b["briefing_date"]).days
        ok = int(b["independent_copies"]) >= MIN_COPIES
        evidence_grade = 1 if int(b.get("dhq_copies") or 0) > 0 else 2 if ok else 3
        rows.append(_row(
            "", "c. period_end", f"{b['confirmed_group_id']} ({b['period_label']})", "",
            "briefing date", str(b["briefing_date"]), "stated period end", str(end), days,
            ok, ok, "gap" if days > 0 else "consistent",
            f"Announced {days} day{'s' if days != 1 else ''} before the stated period ended." if days > 0 else "",
            evidence_grade=evidence_grade,
        ))
    return rows


def run_checks(briefings: pd.DataFrame, operations: pd.DataFrame, op_groups: list[str],
               missing_by: str = "date", overlap_days: int | None = None) -> pd.DataFrame:
    # Arithmetic checks use the effective end; the period_end check uses the period as stated.
    effective = with_effective_end(briefings)
    rows = [
        *within_briefing_checks(effective, operations, op_groups),
        *quarter_checks(effective),
        *month_week_checks(effective, overlap_days),
        *annual_checks(effective, overlap_days),
        *period_checks(briefings),
        # Appended after the original checks so their IDs stay stable.
        *residual_checks(effective, overlap_days),
        *coverage_variant_checks(effective, missing_by, overlap_days),
    ]
    # Object dtype keeps whole numbers as int next to blanks and dates.
    df = pd.DataFrame(rows, columns=CHECK_COLUMNS, dtype=object)
    df["check_id"] = [f"C{n:03d}" for n in range(1, len(df) + 1)]
    years = {r["confirmed_group_id"]: r["briefing_date"].year for r in briefings.to_dict("records")}
    df["label"] = [DEVELOPMENT_LABEL if years.get(s.split()[0]) in DEVELOPMENT_YEARS else "" for s in df["subject"]]
    for col in ["side_a_value", "side_b_value", "difference"]:
        df[col] = df[col].map(lambda v: "" if v is None else v)
    return df


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args(argv)
    briefings = load_briefings(TABLES_DIR / f"pilot_briefings_{args.year}.csv")
    operations = load_operations(TABLES_DIR / f"pilot_operations_{args.year}.csv")
    checks = run_checks(briefings, operations, OPERATION_BRIEFINGS.get(args.year, []))
    checks.to_csv(TABLES_DIR / f"pilot_checks_{args.year}.csv", index=False)
    week_coverage(briefings, args.year).to_csv(TABLES_DIR / f"pilot_week_coverage_{args.year}.csv", index=False)
    print(pd.crosstab(checks["status"], checks["evidence_grade"]).to_string())


if __name__ == "__main__":
    main()
