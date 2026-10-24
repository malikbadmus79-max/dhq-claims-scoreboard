import pandas as pd
import pytest

import scoreboard.group_candidates as gc


def items(*rows):
    """Rows of (date, period_note, neutralised, arrested); outlet and url follow the row order."""
    return pd.DataFrame([{"review_id": f"R{i:04d}", "decided_by": "hand", "date": d, "outlet": f"O{i}",
                          "title": f"t{i}", "url": f"https://x.ng/{i}/", "period_note": p,
                          "neutralised": n, "arrested": a, "rescued": None}
                         for i, (d, p, n, a) in enumerate(rows)])


def groups(df):
    sheet = gc.build_sheet(df).set_index("url")
    return [sheet.loc[f"https://x.ng/{i}/", "candidate_group"] for i in range(len(df))]


def test_items_within_the_gap_share_a_group():
    assert len(set(groups(items(("2024-01-05", "weekly", 43, 115), ("2024-01-08", "weekly", 43, 115))))) == 1


def test_items_beyond_the_gap_are_split():
    g = groups(items(("2024-01-05", "weekly", 43, 115), ("2024-01-09", "weekly", 43, 115)))
    assert g[0] != g[1]


def test_no_chain_across_the_gap():
    """Day 0 and day 2 match, day 2 and day 4 match, but day 0 and day 4 are 4 days apart."""
    g = groups(items(("2024-01-01", "", None, None), ("2024-01-03", "", None, None), ("2024-01-05", "", None, None)))
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


def test_figures_may_differ_on_one_outcome_but_not_two():
    one = groups(items(("2024-01-05", "weekly", 40, 115), ("2024-01-05", "weekly", 43, 115)))
    two = groups(items(("2024-01-05", "weekly", 40, 110), ("2024-01-05", "weekly", 43, 115)))
    assert one[0] == one[1] and two[0] != two[1]


def test_missing_figures_held_as_nan_do_not_disagree():
    df = items(("2024-01-05", "weekly", 43, 115), ("2024-01-05", "weekly", None, None))
    df[["neutralised", "arrested"]] = df[["neutralised", "arrested"]].astype(float)
    assert len(set(groups(df))) == 1


def test_groups_numbered_in_date_order():
    sheet = gc.build_sheet(items(("2024-02-01", "", None, None), ("2024-01-01", "", None, None)))
    assert sheet["candidate_group"].tolist() == ["C0001", "C0002"] and sheet["date"].tolist() == ["2024-01-01", "2024-02-01"]


@pytest.mark.parametrize("note,period", [
    ("Period: weekly.", "weekly"),
    ("DHQ bi-weekly briefing (Onyeuko), last two weeks", "biweekly"),
    ("DHQ briefing (Kangye) of 8 May 2025, month of April", "monthly"),
    ("Period: quarterly: January to March", "quarterly"),
    ("Period: year to date: 11 months", "year"),
    ("DHQ statement (Kangye) of 3 October 2025, May 2023 to date; cumulative period", "cumulative"),
    ("DHQ update (Onyeuko), 11 to 25 November 2021", "biweekly"),
    ("DHQ briefing (Danmadami), 20 April to 4 May 2023", "biweekly"),
    ("DHQ review (Onyeuko), 20 May 2021 to 6 January 2022", "cumulative"),
    ("Denial", ""),
])
def test_period_of(note, period):
    assert gc.period_of(note) == period


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
