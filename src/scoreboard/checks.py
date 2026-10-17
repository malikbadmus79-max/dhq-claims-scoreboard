"""Three arithmetic checks on the pilot briefing and operation tables.

Usage: python -m scoreboard.checks --year 2024

Reads outputs/tables/pilot_briefings_<year>.csv and pilot_operations_<year>.csv and writes
outputs/tables/pilot_checks_<year>.csv.

  a. within_briefing: sum of operation figures against the stated national total.
  b. quarter_months, month_weeks, annual: a period total against the sum of the totals of
     the shorter periods inside it.
  c. period_end: a total announced before the end of the period it names.

Status:
  consistent   both sides complete and equal (a and b), or the period had ended (c).
  gap          both sides complete and different; or, with parts missing, the parts present
               already exceed the total; or the total was announced before the period ended (c).
  not testable a side has no value, or parts are missing and the parts present do not exceed
               the total.
A gap on a side resting on one independent copy is a media-relay difference until a second
independent copy or DHQ's own text confirms the figure (both_sides_2plus_copies).
"""

import argparse
import calendar
from datetime import date, timedelta

import pandas as pd

from scoreboard.discover import TABLES_DIR
from scoreboard.extract import OPERATION_BRIEFINGS, OPERATION_OUTCOMES, OUTCOMES

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
    "status",
    "note",
]


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
        return diff, side_b, "consistent" if diff == 0 else "gap"
    return diff, side_b, "gap" if side_b > total else "not testable"


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
         missing="", incomplete=""):
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
        "status": status,
        "note": note,
    }


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
            names = ", ".join(f"{o['operation']} {o[outcome]}" for o in with_value)
            without = [o["operation"] for o in ops if o[outcome] is None]
            notes = [f"Operations: {names}." if names else "No operation figures."]
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
            ))
    return rows


# b. Across briefings


def _month_key(d: date) -> tuple[int, int]:
    return d.year, d.month


def quarter_checks(briefings: pd.DataFrame) -> list[dict]:
    rows = []
    monthly = {_month_key(r["period_start"]): r for r in _records(briefings[briefings["period_type"] == "monthly"])}
    for q in _records(briefings[briefings["period_type"] == "quarterly"]):
        months = [(q["period_start"].year, m) for m in range(q["period_start"].month, q["period_end"].month + 1)]
        parts = [monthly.get(m) for m in months]
        missing = [calendar.month_name[m] for (_, m), p in zip(months, parts) if p is None]
        present = [p for p in parts if p is not None]
        for outcome in OUTCOMES:
            values = [p[outcome] if p else None for p in parts]
            diff, side_b, status = compare(q[outcome], values, complete=not missing)
            notes = [f"Monthly briefings: {_listing(present, outcome)}."]
            if missing:
                notes.append(f"No monthly briefing for {', '.join(missing)}.")
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
            ))
    return rows


def _weekly_parts(briefings: pd.DataFrame, start: date, end: date) -> list[dict]:
    weekly = briefings[briefings["period_type"] == "weekly"]
    inside = weekly[(weekly["briefing_date"] >= start) & (weekly["briefing_date"] <= end)]
    return _records(inside.sort_values("briefing_date"))


def _sum_against_weeklies(check, subject, total_row, total_label, base_rows, weeklies, start, end, outcome):
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
    notes.append(f"Weekly briefings: {_listing(weeklies, outcome)}.")
    notes.append(
        f"Weekly periods (inferred, 7 days ending on the briefing date) cover {cov['days_covered']} of "
        f"{cov['days']} days from {start} to {end}; {cov['outside']} reach outside that window."
    )
    if not complete and total_row[outcome] is not None:
        # With weeks missing, only weeklies whose inferred period lies wholly inside the window
        # can show a gap: together with the base they cannot exceed the total.
        inner = [w for w in weeklies if w["period_start"] >= start and w["period_end"] <= end]
        inner_sum = sum(v for v in [*(p[outcome] for p in base_rows), *(w[outcome] for w in inner)] if v is not None)
        status = "gap" if inner_sum > total_row[outcome] else "not testable"
        notes.append(f"Base plus weeklies wholly inside the window: {inner_sum}." if base_rows
                     else f"Weeklies wholly inside the month: {inner_sum}.")
    if any(v is None for v in values):
        notes.append("A part has no value for this outcome.")
    quals = _qualifiers([total_row, *parts], outcome)
    if quals:
        notes.append(f"Qualifiers: {'; '.join(quals)}.")
    base_label = f"{base_rows[0]['confirmed_group_id']} total plus " if base_rows else ""
    return _row(
        "", check, subject, outcome,
        total_label, total_row[outcome],
        f"{base_label}sum of {len(weeklies)} weekly totals", side_b, diff,
        _copies(total_row, outcome) >= MIN_COPIES,
        bool(parts) and all(_copies(p, outcome) >= MIN_COPIES for p in parts),
        status, " ".join(notes), missing=cov["missing_weeks"], incomplete=cov["incomplete"],
    )


def month_week_checks(briefings: pd.DataFrame) -> list[dict]:
    rows = []
    for m in _records(briefings[briefings["period_type"] == "monthly"]):
        start, end = m["period_start"], m["period_end"]
        weeklies = _weekly_parts(briefings, start, end)
        for outcome in OUTCOMES:
            rows.append(_sum_against_weeklies(
                "b. month_weeks", f"{m['confirmed_group_id']} ({m['period_label']})", m,
                f"{m['confirmed_group_id']} monthly total", [], weeklies, start, end, outcome,
            ))
    return rows


def annual_checks(briefings: pd.DataFrame) -> list[dict]:
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
        weeklies = _weekly_parts(briefings, start, end)
        for outcome in OUTCOMES:
            row = _sum_against_weeklies(
                "b. annual", f"{a['confirmed_group_id']} ({a['period_label']})", a,
                f"{a['confirmed_group_id']} annual total", [base], weeklies, start, end, outcome,
            )
            row["note"] += f" {base['confirmed_group_id']} period taken as {base['period_start']} to {base['period_end']} ({base['period_flag']})."
            rows.append(row)
    return rows


# c. Period end after the briefing date


def period_checks(briefings: pd.DataFrame) -> list[dict]:
    rows = []
    for b in _records(briefings[briefings["stated_period_end"].notna()]):
        end = b["stated_period_end"]
        days = (end - b["briefing_date"]).days
        ok = int(b["independent_copies"]) >= MIN_COPIES
        rows.append(_row(
            "", "c. period_end", f"{b['confirmed_group_id']} ({b['period_label']})", "",
            "briefing date", str(b["briefing_date"]), "stated period end", str(end), days,
            ok, ok, "gap" if days > 0 else "consistent",
            f"Announced {days} day{'s' if days != 1 else ''} before the stated period ended." if days > 0 else "",
        ))
    return rows


def run_checks(briefings: pd.DataFrame, operations: pd.DataFrame, op_groups: list[str]) -> pd.DataFrame:
    rows = [
        *within_briefing_checks(briefings, operations, op_groups),
        *quarter_checks(briefings),
        *month_week_checks(briefings),
        *annual_checks(briefings),
        *period_checks(briefings),
    ]
    # Object dtype keeps whole numbers as int next to blanks and dates.
    df = pd.DataFrame(rows, columns=CHECK_COLUMNS, dtype=object)
    df["check_id"] = [f"C{n:03d}" for n in range(1, len(df) + 1)]
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
    print(checks["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
