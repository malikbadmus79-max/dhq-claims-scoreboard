from datetime import date, timedelta

import pandas as pd

from scoreboard.checks import (
    annual_checks,
    compare,
    coverage,
    month_week_checks,
    period_checks,
    quarter_checks,
    within_briefing_checks,
)
from scoreboard.extract import OUTCOMES


def briefing(gid, briefing_date, period_type, start, end, values, copies=2, stated_end=None, label=""):
    row = {
        "confirmed_group_id": gid,
        "briefing_date": briefing_date,
        "period_type": period_type,
        "period_label": label or period_type,
        "period_start": start,
        "period_end": end,
        "period_flag": "",
        "stated_period_end": stated_end,
        "independent_copies": copies,
    }
    for outcome in OUTCOMES:
        row[outcome] = values.get(outcome)
        row[f"{outcome}_qualifier"] = ""
        row[f"{outcome}_independent_copies_agreeing"] = copies if values.get(outcome) is not None else 0
    return row


def weekly(gid, d, n, copies=2):
    return briefing(gid, d, "weekly", d - timedelta(days=6), d, {"neutralised": n, "arrested": n, "rescued": n}, copies)


def frame(rows):
    return pd.DataFrame(rows)


def only(rows, outcome="neutralised"):
    return next(r for r in rows if r["outcome"] == outcome)


def test_compare_statuses():
    assert compare(10, [4, 6], complete=True) == (0, 10, "consistent")
    assert compare(10, [4, 5], complete=True) == (1, 9, "gap")
    assert compare(10, [4, None], complete=True) == (6, 4, "not testable")
    assert compare(10, [12], complete=False) == (-2, 12, "gap")
    assert compare(None, [4], complete=True) == (None, 4, "not testable")


def test_coverage_marks_missing_and_incomplete_weeks():
    start, end = date(2024, 2, 1), date(2024, 2, 29)
    windows = [(date(2024, 1, 27), date(2024, 2, 2)), (date(2024, 2, 16), date(2024, 2, 22))]
    cov = coverage(windows, start, end)
    # Feb 3-15 uncovered (13 days: 1 full week and a 6-day stretch); Feb 23-29 uncovered (1 full week).
    assert (cov["days_covered"], cov["outside"], cov["missing_weeks"], cov["incomplete"]) == (9, 1, 2, 2)


def test_within_briefing_gap_and_copies():
    b = frame([briefing("B1", date(2024, 8, 29), "monthly", date(2024, 8, 1), date(2024, 8, 31),
                        {"neutralised": 100, "arrested": 50}, copies=3)])
    ops = pd.DataFrame([
        {"confirmed_group_id": "B1", "operation": "Hadin Kai", "neutralised": 60, "arrested": 20,
         "neutralised_qualifier": "", "arrested_qualifier": "",
         "neutralised_independent_copies_agreeing": 1, "arrested_independent_copies_agreeing": 1},
        {"confirmed_group_id": "B1", "operation": "Delta Safe", "neutralised": None, "arrested": 30,
         "neutralised_qualifier": "", "arrested_qualifier": "",
         "neutralised_independent_copies_agreeing": 0, "arrested_independent_copies_agreeing": 1},
    ])
    rows = within_briefing_checks(b, ops, ["B1"])
    n, a = only(rows, "neutralised"), only(rows, "arrested")
    assert (n["side_a_value"], n["side_b_value"], n["difference"], n["status"]) == (100, 60, 40, "gap")
    assert "No neutralised figure for Delta Safe" in n["note"]
    assert (a["side_b_value"], a["difference"], a["status"]) == (50, 0, "consistent")
    assert a["side_a_2plus_copies"] and not a["side_b_2plus_copies"] and not a["both_sides_2plus_copies"]


def test_quarter_missing_month_not_testable_unless_parts_exceed():
    rows = [
        briefing("Q1", date(2024, 4, 4), "quarterly", date(2024, 1, 1), date(2024, 3, 31),
                 {"neutralised": 300, "arrested": 100, "rescued": 50}),
        briefing("M1", date(2024, 2, 8), "monthly", date(2024, 1, 1), date(2024, 1, 31),
                 {"neutralised": 100, "arrested": 80, "rescued": 10}),
        briefing("M2", date(2024, 3, 1), "monthly", date(2024, 2, 1), date(2024, 2, 29),
                 {"neutralised": 150, "arrested": 70, "rescued": 10}),
    ]
    out = quarter_checks(frame(rows))
    n, a = only(out, "neutralised"), only(out, "arrested")
    assert (n["side_b_value"], n["missing_parts"], n["status"]) == (250, 1, "not testable")
    assert "No monthly briefing for March" in n["note"]
    assert (a["side_b_value"], a["difference"], a["status"]) == (150, -50, "gap")


def test_quarter_complete_consistent():
    rows = [briefing("Q", date(2024, 4, 4), "quarterly", date(2024, 1, 1), date(2024, 3, 31), {"neutralised": 6})]
    rows += [briefing(f"M{m}", date(2024, m + 1, 2), "monthly", date(2024, m, 1),
                      date(2024, m + 1, 1) - timedelta(days=1), {"neutralised": 2}) for m in (1, 2, 3)]
    n = only(quarter_checks(frame(rows)))
    assert (n["side_b_value"], n["difference"], n["status"]) == (6, 0, "consistent")


def test_month_weeks_complete_and_incomplete():
    # A 28-day month tiled exactly by four weekly periods.
    feb = [briefing("M", date(2021, 3, 5), "monthly", date(2021, 2, 1), date(2021, 2, 28), {"neutralised": 40})]
    feb += [weekly(f"W{i}", date(2021, 2, 7 * i), 10) for i in (1, 2, 3, 4)]
    n = only(month_week_checks(frame(feb)))
    assert (n["side_b_value"], n["missing_parts"], n["incomplete_parts"], n["status"]) == (40, 0, 0, "consistent")

    # Drop one week: missing week, not testable.
    n = only(month_week_checks(frame(feb[:-1])))
    assert (n["side_b_value"], n["missing_parts"], n["status"]) == (30, 1, "not testable")

    # Weeklies wholly inside the month already exceed the monthly total: gap.
    over = [dict(feb[0], neutralised=25), *feb[1:4]]
    n = only(month_week_checks(frame(over)))
    assert (n["side_b_value"], n["status"]) == (30, "gap")


def test_annual_against_year_to_date_plus_december_weeklies():
    rows = [
        briefing("A", date(2024, 12, 31), "annual", date(2024, 1, 1), date(2024, 12, 31), {"neutralised": 1000}),
        briefing("Y", date(2024, 12, 5), "year to date", date(2024, 1, 1), date(2024, 11, 30), {"neutralised": 900}),
        weekly("W1", date(2024, 12, 20), 50),
        weekly("W2", date(2024, 12, 28), 70),
    ]
    n = only(annual_checks(frame(rows)))
    assert (n["side_a_value"], n["side_b_value"], n["difference"], n["status"]) == (1000, 1020, -20, "gap")
    assert n["missing_parts"] >= 1


def test_period_end_after_briefing_date_is_gap():
    rows = [
        briefing("Q3", date(2024, 9, 26), "quarterly", date(2024, 7, 1), date(2024, 9, 30), {}, stated_end=date(2024, 9, 30)),
        briefing("A", date(2024, 12, 31), "annual", date(2024, 1, 1), date(2024, 12, 31), {}, stated_end=date(2024, 12, 31)),
        weekly("W", date(2024, 1, 5), 1),
    ]
    out = period_checks(frame(rows))
    assert [(r["subject"].split()[0], r["difference"], r["status"]) for r in out] == [("Q3", 4, "gap"), ("A", 0, "consistent")]
