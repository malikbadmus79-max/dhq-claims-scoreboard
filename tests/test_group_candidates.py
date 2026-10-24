import pandas as pd
import pytest

import scoreboard.group_candidates as gc


def items(*rows):
    """Rows of (date, period_note, neutralised, arrested); outlet and url follow the row order."""
    return pd.DataFrame([{"review_id": f"R{i:04d}", "decided_by": "hand", "date": d, "outlet": f"O{i}",
                          "title": f"t{i}", "url": f"https://x.ng/{i}/", "period_note": p, "period_source": "notes",
                          "neutralised": n, "arrested": a, "rescued": None}
                         for i, (d, p, n, a) in enumerate(rows)])


def groups(df):
    sheet = gc.build_sheet(df).set_index("url")
    return [sheet.loc[f"https://x.ng/{i}/", "candidate_group"] for i in range(len(df))]


def test_items_within_the_gap_share_a_group():
    assert len(set(groups(items(("2024-01-05", "weekly", 43, 115), ("2024-01-07", "weekly", 43, 115))))) == 1


def test_items_beyond_the_gap_are_split():
    g = groups(items(("2024-01-05", "weekly", 43, 115), ("2024-01-08", "weekly", 43, 115)))
    assert g[0] != g[1]


def test_gap_counts_from_the_earliest_item_not_through_a_chain():
    """Day 0, 2 and 3: day 3 is within 2 days of day 2 but 3 days after the group's earliest item."""
    g = groups(items(("2024-01-01", "", None, None), ("2024-01-03", "", None, None), ("2024-01-04", "", None, None)))
    assert g[0] == g[1] and g[2] != g[0]
    sheet = gc.build_sheet(items(*[(f"2024-01-{d:02d}", "", None, None) for d in range(1, 15)]))
    spans = sheet.groupby("candidate_group")["date"].agg(lambda d: (pd.to_datetime(d).max() - pd.to_datetime(d).min()).days)
    assert spans.max() <= gc.MAX_GAP_DAYS


def test_different_periods_are_split():
    g = groups(items(("2024-08-29", "weekly", None, None), ("2024-08-29", "monthly", None, None)))
    assert g[0] != g[1]


def test_missing_period_conflicts_with_none():
    g = groups(items(("2024-08-29", "weekly", None, None), ("2024-08-29", "", None, None)))
    assert g[0] == g[1]


def test_figures_never_keep_items_apart_and_are_flagged():
    df = items(("2024-01-05", "weekly", 40, 1326), ("2024-01-05", "weekly", 43, 1903), ("2024-01-05", "weekly", 43, None))
    sheet = gc.build_sheet(df)
    assert sheet["candidate_group"].nunique() == 1
    assert sheet["figure_flag"].eq("neutralised: 40 vs 43; arrested: 1,326 vs 1,903").all()


def test_agreeing_figures_leave_no_flag():
    sheet = gc.build_sheet(items(("2024-01-05", "weekly", 43, 115), ("2024-01-05", "weekly", 43, None)))
    assert sheet["figure_flag"].eq("").all()


def test_figures_break_a_tie_between_open_groups():
    """A weekly and a monthly group are both open; an item without a period could join either and goes
    to the group whose figures it shares."""
    g = groups(items(("2024-01-05", "weekly", 43, 115), ("2024-01-05", "monthly", 500, 900),
                     ("2024-01-06", "", 500, None)))
    assert g[0] != g[1] and g[2] == g[1]


def test_missing_figures_held_as_nan_do_not_count():
    df = items(("2024-01-05", "weekly", 43, 115), ("2024-01-05", "weekly", None, None))
    df[["neutralised", "arrested"]] = df[["neutralised", "arrested"]].astype(float)
    sheet = gc.build_sheet(df)
    assert sheet["candidate_group"].nunique() == 1 and sheet["figure_flag"].eq("").all()


def test_groups_numbered_in_date_order():
    sheet = gc.build_sheet(items(("2024-02-01", "", None, None), ("2024-01-01", "", None, None)))
    assert sheet["candidate_group"].tolist() == ["C0001", "C0002"] and sheet["date"].tolist() == ["2024-01-01", "2024-02-01"]


@pytest.mark.parametrize("text,period", [
    ("Period: weekly.", "weekly"),
    ("Troops kill 84 terrorists, arrest 38 in 2 weeks", "biweekly"),
    ("DHQ bi-weekly briefing (Onyeuko), last two weeks", "biweekly"),
    ("Troops killed 102 terrorists, rescued 393 kidnap victims in July: DHQ", "monthly"),
    ("Military kills 2,351 terrorists in three months", "quarterly"),
    ("Military Says It Eliminated 10, 937 Terrorists In 2024", "year"),
    ("2025: Military destroys 503 illegal refineries, arrests 778 suspects", "year"),
    ("Troops have neutralised 300 terrorists so far", "cumulative"),
    ("DHQ update (Onyeuko), 11 to 25 November 2021", "biweekly"),
    ("DHQ review (Onyeuko), 20 May 2021 to 6 January 2022", "cumulative"),
    ("DHQ update (Onyeuko), 10 to 24 March 2022; also cumulative surrenders since September 2021", "biweekly"),
    ("The Defence Headquarters says troops killed 50 terrorists within one week.", "weekly"),
    ("Denial", ""),
])
def test_period_of(text, period):
    assert gc.period_of(text) == period


def test_period_source_order():
    assert gc.period_with_source("Period: weekly.", "in May", "two weeks") == ("weekly", "notes")
    assert gc.period_with_source("", "in May", "two weeks") == ("monthly", "title")
    assert gc.period_with_source("", "Troops kill 50", "in the last two weeks") == ("biweekly", "body")
    assert gc.period_with_source("", "Troops kill 50", "x" * gc.BODY_CHARS + " one week") == ("", "none")


@pytest.mark.parametrize("title,figures", [
    ("Troops Kill 37 Terrorists, Arrest 95, Rescue 53 Victims", {"neutralised": 37, "arrested": 95, "rescued": 53}),
    ("Military kills 1,166 terrorists, arrests 1,096 others", {"neutralised": 1166, "arrested": 1096}),
    ("2025: Military destroys 503 illegal refineries, arrests 778 suspects", {"arrested": 778}),
    ("Troops neutralised 6,886 terrorists, nabbed 6,970 suspects in 2023", {"neutralised": 6886, "arrested": 6970}),
])
def test_figures_of(title, figures):
    assert gc.figures_of(title) == figures


def test_refuses_to_overwrite_a_coded_group_sheet(tmp_path):
    path = tmp_path / "g.csv"
    sheet = gc.build_sheet(items(("2024-01-05", "", None, None)))
    sheet.loc[0, "confirmed_group_id"] = "B2024-001"
    sheet.to_csv(path, index=False)
    with pytest.raises(RuntimeError):
        gc.build(sheet_path=path)
