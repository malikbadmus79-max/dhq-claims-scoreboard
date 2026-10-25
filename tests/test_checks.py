from datetime import date, timedelta

import pandas as pd

from scoreboard.checks import (
    annual_checks,
    compare,
    coverage,
    PARTS_EXCEED,
    SHORTFALL,
    coverage_variant_checks,
    direction_status,
    effective_end,
    gap_or_minor,
    grade,
    iso_weeks,
    largest_weekly,
    month_week_checks,
    part_grade,
    period_checks,
    quarter_checks,
    residual_checks,
    run_checks,
    week_coverage,
    within_briefing_checks,
)
from scoreboard.checks import OVERLAP_REASON, best_disjoint_sum, overlapping_pairs
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
    assert (n["side_a_value"], n["side_b_value"], n["difference"]) == (100, 60, 40)
    assert n["status"] == "shortfall (listed operations may be incomplete)"
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


# Evidence grades


def test_part_grade_and_row_grade():
    dhq = {"neutralised_dhq_text": True, "neutralised_independent_copies_agreeing": 1}
    two = {"neutralised_independent_copies_agreeing": 2}
    one = {"neutralised_independent_copies_agreeing": 1}
    assert [part_grade(r, "neutralised") for r in (dhq, two, one)] == [1, 2, 3]
    assert grade([dhq, two], "neutralised") == 2
    assert grade([two, one], "neutralised") == 3
    assert grade([], "neutralised") == 3


def test_every_check_row_has_a_grade():
    rows = [
        briefing("M", date(2024, 2, 8), "monthly", date(2024, 1, 1), date(2024, 1, 31), {"neutralised": 30}),
        weekly("W1", date(2024, 1, 12), 10),
        weekly("W2", date(2024, 1, 19), 10, copies=1),
    ]
    out = run_checks(frame(rows), pd.DataFrame(columns=["confirmed_group_id"]), [])
    assert out["evidence_grade"].isin([1, 2, 3]).all()
    month = out[(out["check"] == "b. month_weeks") & (out["outcome"] == "neutralised")].iloc[0]
    assert month["evidence_grade"] == 3


# Implied residual


def test_largest_weekly_same_year_only():
    rows = frame([weekly("W1", date(2024, 1, 12), 10), weekly("W2", date(2024, 3, 8), 40),
                  weekly("W3", date(2023, 12, 29), 99)])
    assert largest_weekly(rows, 2024, "neutralised")["confirmed_group_id"] == "W2"


def _month_with_weeklies(total, weekly_values):
    # Weeklies on Feb 7, 14, 21 cover Feb 1-21; Feb 22-28 (7 days, 1 week) is missing.
    rows = [briefing("M", date(2021, 3, 5), "monthly", date(2021, 2, 1), date(2021, 2, 28), {"neutralised": total})]
    rows += [weekly(f"W{i}", date(2021, 2, 7 * i), v) for i, v in enumerate(weekly_values, start=1)]
    return frame(rows)


def test_implied_residual_implausible_and_ratio():
    out = [r for r in residual_checks(_month_with_weeklies(100, [10, 20, 15])) if r["outcome"] == "neutralised"]
    r = out[0]
    # (100 - 45) / 1 week = 55 against a largest weekly figure of 20.
    assert (r["side_b_value"], r["difference"], r["missing_parts"]) == (45, 55, 1.0)
    assert (r["implied_per_missing_week"], r["largest_weekly_figure"], r["residual_ratio"]) == (55.0, 20, 2.75)
    assert r["status"] == "implausible residual"


def test_implied_residual_consistent_and_gap():
    r = only(residual_checks(_month_with_weeklies(60, [10, 20, 15])))
    assert (r["implied_per_missing_week"], r["status"]) == (15.0, "consistent")
    r = only(residual_checks(_month_with_weeklies(40, [10, 20, 15])))
    assert (r["difference"], r["implied_per_missing_week"], r["status"]) == (-5, "", "gap")


def test_implied_residual_not_produced_without_missing_days():
    df = _month_with_weeklies(60, [10, 20, 15, 15])
    assert [r for r in residual_checks(df) if r["outcome"] == "neutralised"] == []


def test_implied_residual_not_testable_when_part_has_no_value():
    df = _month_with_weeklies(60, [10, 20, 15])
    df.loc[df["confirmed_group_id"] == "W2", "neutralised"] = None
    assert only(residual_checks(df))["status"] == "not testable"


# Coverage-based variant


def test_iso_weeks_by_thursday():
    weeks = iso_weeks(date(2024, 2, 1), date(2024, 2, 29))
    assert [w[0] for w in weeks] == [date(2024, 1, 29), date(2024, 2, 5), date(2024, 2, 12), date(2024, 2, 19),
                                     date(2024, 2, 26)]


def test_coverage_variant_statuses():
    base = [briefing("M", date(2024, 2, 8), "monthly", date(2024, 1, 1), date(2024, 1, 31), {"neutralised": 40})]
    full = [weekly(f"W{i}", d, 10) for i, d in enumerate(
        [date(2024, 1, 5), date(2024, 1, 12), date(2024, 1, 19), date(2024, 1, 26)], start=1)]
    # January 2024 has four weeks by Thursday (Jan 4, 11, 18, 25); all have a briefing.
    assert only(coverage_variant_checks(frame(base + full)))["status"] == "consistent"
    assert only(coverage_variant_checks(frame([dict(base[0], neutralised=45)] + full)))["status"] == "gap"
    # One week missing and the sum below the total: not testable.
    r = only(coverage_variant_checks(frame(base + full[:3])))
    assert (r["side_b_value"], r["missing_parts"], r["status"]) == (30, 1, "not testable")
    assert "2024-W04" in r["note"]
    # One week missing but the sum already above the total: gap.
    r = only(coverage_variant_checks(frame([dict(base[0], neutralised=25)] + full[:3])))
    assert r["status"] == "gap"


def test_week_coverage_table():
    rows = frame([
        weekly("W1", date(2024, 1, 5), 10),
        briefing("M", date(2024, 1, 10), "monthly", date(2023, 12, 1), date(2023, 12, 31), {}),
    ])
    table = week_coverage(rows, 2024)
    assert table.iloc[0]["iso_week"] == "2024-W01" and table.iloc[0]["weekly_found"]
    second = table.iloc[1]
    assert (second["weekly_found"], second["other_briefings"]) == (False, "M (monthly)")
    assert table.iloc[-1]["week_start"] == date(2024, 12, 30)


# Effective period end


NO_OPS = pd.DataFrame(columns=["confirmed_group_id"])


def test_effective_end_is_earlier_of_stated_end_and_briefing_date():
    ytd = briefing("Y", date(2024, 12, 5), "year to date", date(2024, 1, 1), date(2024, 11, 30), {},
                   stated_end=date(2024, 12, 31))
    assert effective_end(ytd) == date(2024, 12, 5)
    q3 = briefing("Q3", date(2024, 9, 26), "quarterly", date(2024, 7, 1), date(2024, 9, 30), {},
                  stated_end=date(2024, 9, 30))
    assert effective_end(q3) == date(2024, 9, 26)
    jan = briefing("M", date(2024, 2, 8), "monthly", date(2024, 1, 1), date(2024, 1, 31), {},
                   stated_end=date(2024, 1, 31))
    assert effective_end(jan) == date(2024, 1, 31)
    assert effective_end(weekly("W", date(2024, 1, 5), 1)) == date(2024, 1, 5)


def test_annual_window_starts_after_effective_end_of_year_to_date():
    rows = [
        briefing("A", date(2024, 12, 31), "annual", date(2024, 1, 1), date(2024, 12, 31), {"neutralised": 1000},
                 stated_end=date(2024, 12, 31)),
        briefing("Y", date(2024, 12, 5), "year to date", date(2024, 1, 1), date(2024, 11, 30), {"neutralised": 900},
                 stated_end=date(2024, 12, 31)),
        weekly("W1", date(2024, 12, 20), 50),
    ]
    out = run_checks(frame(rows), NO_OPS, [])
    r = out[(out["check"] == "b. implied_residual") & (out["outcome"] == "neutralised")].iloc[0]
    # Window Dec 6-31 (26 days); W1 covers Dec 14-20 (7 days): 19 days missing, 2.71 weeks.
    assert r["missing_parts"] == 2.71
    assert r["implied_per_missing_week"] == round(50 / (19 / 7), 1)
    # The period_end check still compares the stated end with the briefing date.
    p = out[(out["check"] == "c. period_end") & out["subject"].str.startswith("Y")].iloc[0]
    assert (p["side_b_value"], p["difference"], p["status"]) == ("2024-12-31", 26, "gap")


def test_quarter_month_cut_by_effective_end_counts_as_missing():
    rows = [
        briefing("Q3", date(2024, 9, 26), "quarterly", date(2024, 7, 1), date(2024, 9, 30), {"neutralised": 300},
                 stated_end=date(2024, 9, 30)),
        *[briefing(f"M{m}", date(2024, m + 1, 2), "monthly", date(2024, m, 1),
                   date(2024, m + 1, 1) - timedelta(days=1), {"neutralised": 100}) for m in (7, 8, 9)],
    ]
    out = run_checks(frame(rows), NO_OPS, [])
    q = out[(out["check"] == "b. quarter_months") & (out["outcome"] == "neutralised")].iloc[0]
    assert (q["side_b_value"], q["missing_parts"], q["status"]) == (200, 1, "not testable")
    assert "September (effective period ends 2024-09-26)" in q["note"]


# Direction labels and minor differences


def test_direction_labels():
    assert direction_status("gap", 100, 120) == PARTS_EXCEED
    assert direction_status("gap", 120, 100) == SHORTFALL
    assert direction_status("consistent", 100, 100) == "consistent"
    assert direction_status("minor difference", 100, 101) == "minor difference"


def test_within_briefing_parts_exceed_total():
    b = frame([briefing("B1", date(2024, 8, 29), "monthly", date(2024, 8, 1), date(2024, 8, 31),
                        {"neutralised": 100}, copies=2)])
    ops = pd.DataFrame([{"confirmed_group_id": "B1", "operation": "Hadin Kai", "neutralised": 150, "arrested": None,
                         "neutralised_qualifier": "", "arrested_qualifier": "",
                         "neutralised_independent_copies_agreeing": 2, "arrested_independent_copies_agreeing": 0}])
    assert only(within_briefing_checks(b, ops, ["B1"]))["status"] == PARTS_EXCEED


def test_minor_difference_threshold_is_one_percent_of_larger_side():
    assert gap_or_minor(1000, 990) == "minor difference"   # 10 of 1000
    assert gap_or_minor(990, 1000) == "minor difference"
    assert gap_or_minor(1000, 989) == "gap"                # 11 of 1000
    assert gap_or_minor(100, 99) == "minor difference"
    assert gap_or_minor(100, 98) == "gap"
    assert compare(1000, [995], complete=True) == (5, 995, "minor difference")
    assert compare(1000, [1005], complete=False) == (-5, 1005, "minor difference")


def test_within_briefing_minor_difference_takes_precedence_over_direction():
    b = frame([briefing("B1", date(2024, 8, 29), "monthly", date(2024, 8, 1), date(2024, 8, 31),
                        {"neutralised": 1000}, copies=2)])
    ops = pd.DataFrame([{"confirmed_group_id": "B1", "operation": "Hadin Kai", "neutralised": 995, "arrested": None,
                         "neutralised_qualifier": "", "arrested_qualifier": "",
                         "neutralised_independent_copies_agreeing": 2, "arrested_independent_copies_agreeing": 0}])
    assert only(within_briefing_checks(b, ops, ["B1"]))["status"] == "minor difference"


def test_rows_labelled_development_year():
    rows = [weekly("W1", date(2024, 1, 12), 10),
            briefing("M", date(2024, 2, 8), "monthly", date(2024, 1, 1), date(2024, 1, 31), {"neutralised": 30})]
    out = run_checks(frame(rows), NO_OPS, [])
    assert (out["label"] == "development year").all()


# Overlapping parts (Deviations, 2026-10-25)


def part(gid, start, end, n):
    return briefing(gid, end, "biweekly", start, end, {"neutralised": n, "arrested": n, "rescued": n})


def test_overlap_of_one_day_is_adjacent():
    a, b = part("A", date(2024, 1, 1), date(2024, 1, 14), 5), part("B", date(2024, 1, 14), date(2024, 1, 27), 5)
    c = part("C", date(2024, 1, 12), date(2024, 1, 25), 9)
    assert overlapping_pairs([a, b], 1) == []
    assert overlapping_pairs([a, b, c], 1) == [("A", "C"), ("B", "C")]
    assert best_disjoint_sum([a, b, c], "neutralised", 1) == 10
    assert best_disjoint_sum([a, part("D", date(2024, 1, 10), date(2024, 1, 20), 12)], "neutralised", 1) == 12


def month_with(parts, total):
    m = briefing("M", date(2024, 1, 31), "monthly", date(2024, 1, 1), date(2024, 1, 31),
                 {"neutralised": total, "arrested": total, "rescued": total}, stated_end=date(2024, 1, 31))
    return frame([m, *parts])


def test_overlapping_parts_not_testable_unless_disjoint_parts_exceed():
    parts = [part("A", date(2024, 1, 1), date(2024, 1, 14), 50), part("B", date(2024, 1, 10), date(2024, 1, 23), 50),
             part("C", date(2024, 1, 18), date(2024, 1, 31), 50)]
    for total, status in ((150, "not testable"), (90, "gap")):
        rows = month_week_checks(month_with(parts, total), overlap_days=1)
        r = only(rows)
        assert r["status"] == status
        if status == "not testable":
            assert r["reason"] == OVERLAP_REASON and "A/B" in r["note"] and "B/C" in r["note"]
        else:
            assert r["side_b_value"] == 100 and r["reason"] == ""
    # Pilot behaviour (no overlap rule): the parts are summed.
    assert only(month_week_checks(month_with(parts, 150)))["status"] == "consistent"


def test_adjacent_parts_sum_normally():
    parts = [part("A", date(2024, 1, 1), date(2024, 1, 14), 50), part("B", date(2024, 1, 14), date(2024, 1, 27), 50),
             part("C", date(2024, 1, 28), date(2024, 1, 31), 50)]
    r = only(month_week_checks(month_with(parts, 150), overlap_days=1))
    assert (r["status"], r["reason"]) == ("consistent", "")


def test_overlap_rule_in_coverage_variant_and_residual():
    parts = [part("A", date(2024, 1, 1), date(2024, 1, 14), 50), part("B", date(2024, 1, 10), date(2024, 1, 23), 50)]
    df = month_with(parts, 500)
    cov = only(coverage_variant_checks(df, "period", overlap_days=1))
    assert (cov["status"], cov["reason"]) == ("not testable", OVERLAP_REASON)
    df = pd.concat([df, frame([weekly("W", date(2024, 3, 7), 40)])], ignore_index=True)
    res = only(residual_checks(df, overlap_days=1))
    assert (res["status"], res["reason"], res["implied_per_missing_week"]) == ("not testable", OVERLAP_REASON, "")


def test_coverage_variant_missing_weeks_by_period():
    parts = [part("A", date(2024, 1, 1), date(2024, 1, 14), 50), part("B", date(2024, 1, 15), date(2024, 1, 28), 50)]
    by_date = only(coverage_variant_checks(month_with(parts, 100), "date"))
    by_period = only(coverage_variant_checks(month_with(parts, 100), "period"))
    # Weeks of January 2024 by Thursday: 4, 11, 18, 25. The briefings are dated in the weeks of the 11th
    # and 25th; their periods cover all four Thursdays.
    assert by_date["missing_parts"] == 2 and by_period["missing_parts"] == 0
    assert by_period["status"] == "consistent"
