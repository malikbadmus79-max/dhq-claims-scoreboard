from datetime import date

import pandas as pd
import pytest

import scoreboard.audit_inputs as ai


def briefing(cls, first_date="2021-10-28", classes=""):
    return {"briefing_id": "B1", "first_date": first_date, "period_class": cls, "period_classes": classes}


def copy(lead="", title="", url="u1"):
    return {"url": url, "title": title, "lead": lead}


# Periods


def test_stated_ranges_read_one_and_two_month_ranges():
    found = ai.stated_ranges("Troops acted between 14 to 28 October 2021. Also 28 September to 12 October 2021.")
    assert [(s, e) for s, e, _ in found] == [(date(2021, 10, 14), date(2021, 10, 28)),
                                             (date(2021, 9, 28), date(2021, 10, 12))]
    assert found[0][2].startswith("Troops acted")
    assert ai.stated_ranges("from 30 to 31 February 2021") == []
    assert ai.stated_ranges("from 28 October to 14 October 2021") == []


@pytest.mark.parametrize("cls,days,basis", [("weekly", 7, "inferred weekly"), ("biweekly", 14, "inferred biweekly")])
def test_inferred_periods_end_on_the_briefing_date(cls, days, basis):
    p = ai.propose_period(briefing(cls), [copy("No dates here.")])
    assert (p["proposed_basis"], p["proposed_end"], p["needs_reading"]) == (basis, "2021-10-28", "no")
    assert (date(2021, 10, 28) - date.fromisoformat(p["proposed_start"])).days == days - 1


def test_single_class_consistent_range_is_stated():
    p = ai.propose_period(briefing("biweekly"), [copy("Between 14 to 28 October 2021, troops acted.", url="a"),
                                                 copy("Between 14 to 28 October 2021, troops acted.", url="b")])
    assert (p["proposed_start"], p["proposed_end"], p["proposed_basis"]) == ("2021-10-14", "2021-10-28", "stated range")
    assert p["needs_reading"] == "no" and p["evidence_url"] == "a" and p["evidence_sentence"]


@pytest.mark.parametrize("leads", [
    ["Between 14 to 28 October 2021.", "Between 15 to 28 October 2021."],  # two ranges
    ["Between 1 to 28 October 2021."],                                      # length does not fit biweekly
])
def test_ambiguous_or_misfitting_range_needs_reading(leads):
    p = ai.propose_period(briefing("biweekly"), [copy(l, url=f"u{i}") for i, l in enumerate(leads)])
    assert p["proposed_basis"] == "stated range" and p["needs_reading"] == "yes"


def test_named_month_and_previous_year():
    p = ai.propose_period(briefing("monthly", "2024-05-30"), [copy(title="Troops neutralised 624 in May")])
    assert (p["proposed_start"], p["proposed_end"], p["proposed_basis"], p["needs_reading"]) == \
        ("2024-05-01", "2024-05-31", "named month", "no")
    dec = ai.propose_period(briefing("monthly", "2025-01-06"), [copy(title="Operations in December")])
    assert (dec["proposed_start"], dec["proposed_end"]) == ("2024-12-01", "2024-12-31")


def test_monthly_with_no_or_two_months_needs_reading():
    for titles in (["Troops neutralise 50"], ["Figures for April", "Figures for May"]):
        p = ai.propose_period(briefing("monthly", "2024-05-30"), [copy(title=t, url=t) for t in titles])
        assert (p["proposed_basis"], p["needs_reading"], p["proposed_start"]) == ("none", "yes", "")


def test_quarter_year_cumulative_mixed_and_blank_need_reading():
    q = ai.propose_period(briefing("quarterly", "2024-04-04"), [copy(title="Results of the first quarter")])
    assert (q["proposed_start"], q["proposed_end"], q["proposed_basis"], q["needs_reading"]) == \
        ("2024-01-01", "2024-03-31", "named quarter", "yes")
    assert ai.propose_period(briefing("quarterly"), [copy(title="No quarter named")])["proposed_start"] == ""
    for cls, classes, basis in (("year", "", "year"), ("cumulative", "", "cumulative"),
                                ("", "weekly 5; biweekly 1", "none"), ("", "", "none")):
        p = ai.propose_period(briefing(cls, classes=classes), [copy()])
        assert (p["proposed_basis"], p["needs_reading"]) == (basis, "yes")
    assert ai.propose_period(briefing("", classes="weekly 5; biweekly 1"), [copy()])["period_class"] == \
        "weekly 5; biweekly 1"


def test_period_sheet_adds_pilot_cross_check():
    briefings = pd.DataFrame([{**briefing("weekly", "2024-02-16"), "pilot_group_id": "B2024-007"}])
    copies = pd.DataFrame([{"briefing_id": "B1", "date": "2024-02-16", "outlet": "O", "url": "u1", "title": "t"}])
    pilot = pd.DataFrame([{"confirmed_group_id": "B2024-007", "period_type": "weekly", "period_start": "2024-02-10",
                           "period_end": "2024-02-16", "period_flag": "inferred: 7 days ending on the briefing date"}])
    sheet = ai.period_sheet(briefings, copies, pd.Series({"u1": ""}), pilot)
    assert list(sheet.columns) == ai.PERIOD_COLUMNS
    assert sheet.loc[0, "period_notes"] == ("Pilot B2024-007: weekly 2024-02-10 to 2024-02-16 "
                                            "(inferred: 7 days ending on the briefing date).")
    assert (sheet.loc[0, ["confirmed_start", "confirmed_end", "confirmed_basis"]] == "").all()


# Grades


@pytest.fixture
def grade_frames(monkeypatch):
    copies = pd.DataFrame([
        ("B1", "a", "118", "national marker"), ("B1", "b", "118", "no region named"),
        ("B1", "c", "118", "first mention"), ("B1", "d", "120", "national marker"),
        ("B2", "e", "43", "national marker"), ("B2", "f", "43", "national marker"),
    ], columns=["briefing_id", "url", "body_arrested", "body_arrested_rule"])
    final = pd.DataFrame([
        ("B1", "arrested", "118", "reported", "hand"), ("B2", "arrested", "43", "reported", "automatic"),
        ("B1", "rescued", "", "vague", "hand"), ("B3", "arrested", "9", "reported", "correction"),
    ], columns=["briefing_id", "outcome", "value", "final_status", "source"])
    monkeypatch.setattr(ai, "has_nan_credit", lambda body: False)
    return final, copies


def test_grades_count_independent_matching_copies(grade_frames, monkeypatch):
    final, copies = grade_frames
    monkeypatch.setattr(ai, "same_wire_pairs", lambda urls, bodies: [])
    g = ai.value_grades(final, copies, pd.Series(dtype=str)).set_index(["briefing_id", "outcome"])
    assert list(g.reset_index().columns) == ai.GRADE_COLUMNS and len(g) == 3
    hand = g.loc[("B1", "arrested")]
    assert (hand["independent_copies_supporting"], hand["grade"], hand["supporting_urls"], hand["needs_review"]) == \
        (2, 2, "a; b", "no")
    # Automatic values follow the same rule as hand values (Deviations, 2026-10-25).
    automatic = g.loc[("B2", "arrested")]
    assert (automatic["independent_copies_supporting"], automatic["grade"], automatic["supporting_urls"]) == (2, 2, "e; f")
    missing = g.loc[("B3", "arrested")]
    assert (missing["independent_copies_supporting"], missing["grade"], missing["needs_review"]) == (0, 3, "yes")


def test_same_wire_copies_count_once(grade_frames, monkeypatch):
    final, copies = grade_frames
    monkeypatch.setattr(ai, "same_wire_pairs", lambda urls, bodies: [("a", "b")])
    g = ai.value_grades(final, copies, pd.Series(dtype=str)).set_index(["briefing_id", "outcome"])
    assert (g.loc[("B1", "arrested"), "independent_copies_supporting"], g.loc[("B1", "arrested"), "grade"]) == (1, 3)
    monkeypatch.setattr(ai, "same_wire_pairs", lambda urls, bodies: [])
    monkeypatch.setattr(ai, "has_nan_credit", lambda body: True)
    bodies = pd.Series({u: "NAN" for u in copies["url"]})
    g = ai.value_grades(final, copies, bodies).set_index(["briefing_id", "outcome"])
    assert g.loc[("B1", "arrested"), "independent_copies_supporting"] == 1


def test_hand_reviewed_rows_are_kept(grade_frames, monkeypatch):
    final, copies = grade_frames
    monkeypatch.setattr(ai, "same_wire_pairs", lambda urls, bodies: [])
    reviewed = pd.DataFrame([("B3", "arrested", "9", "correction", "2", "2", "x; y", "no", "Checked by hand"),
                             ("B1", "arrested", "118", "hand", "9", "2", "z", "no", "")], columns=ai.GRADE_COLUMNS)
    g = ai.value_grades(final, copies, pd.Series(dtype=str), reviewed).set_index(["briefing_id", "outcome"])
    kept = g.loc[("B3", "arrested")]
    assert (kept["independent_copies_supporting"], kept["supporting_urls"], kept["review_note"]) == \
        (2, "x; y", "Checked by hand")
    assert g.loc[("B1", "arrested"), "independent_copies_supporting"] == 2  # no review note: recounted


# Adapter


@pytest.fixture
def adapter_frames():
    periods = pd.DataFrame([
        {"briefing_id": "B1", "briefing_date": "2024-05-30", "period_class": "monthly", "proposed_start": "2024-05-01",
         "proposed_end": "2024-05-31", "proposed_basis": "named month", "evidence_url": "", "evidence_sentence": "",
         "needs_reading": "no", "confirmed_start": "", "confirmed_end": "", "confirmed_basis": "", "period_notes": ""},
        {"briefing_id": "B2", "briefing_date": "2024-05-24", "period_class": "", "proposed_start": "",
         "proposed_end": "", "proposed_basis": "none", "evidence_url": "", "evidence_sentence": "",
         "needs_reading": "yes", "confirmed_start": "", "confirmed_end": "", "confirmed_basis": "", "period_notes": ""},
    ])
    final = pd.DataFrame([(b, o, "10" if o == "arrested" else "", "", "reported" if o == "arrested" else "vague", "hand")
                          for b in ("B1", "B2") for o in ai.OUTCOMES],
                         columns=["briefing_id", "outcome", "value", "qualifier", "final_status", "source"])
    grades = pd.DataFrame([(b, "arrested", "10", "hand", "2", "2", "a; b", "no", "") for b in ("B1", "B2")],
                          columns=ai.GRADE_COLUMNS)
    briefings = pd.DataFrame({"briefing_id": ["B1", "B2"], "items": ["3", "2"]})
    return final, periods, grades, briefings, {"B1": 2, "B2": 1}


def test_adapter_refuses_unconfirmed_periods(adapter_frames):
    final, periods, grades, briefings, ind = adapter_frames
    with pytest.raises(ValueError, match="B2: needs reading, no confirmed period"):
        ai.check_briefings(final, periods, grades, briefings, ind)
    half = periods.assign(confirmed_basis=["", "stated range"])
    with pytest.raises(ValueError, match="without confirmed_start and confirmed_end"):
        ai.check_briefings(final, half, grades, briefings, ind)
    with pytest.raises(ValueError, match="not one of"):
        ai.check_briefings(final, periods.assign(confirmed_basis=["", "fortnight"]), grades, briefings, ind)


def test_adapter_refuses_values_needing_review(adapter_frames):
    final, periods, grades, briefings, ind = adapter_frames
    confirmed = periods.assign(confirmed_basis=["", "unclear"])
    with pytest.raises(ValueError, match="B1 arrested: value needs review"):
        ai.check_briefings(final, confirmed, grades.assign(needs_review=["yes", "no"]), briefings, ind)


def test_adapter_builds_the_checks_schema_once_confirmed(adapter_frames):
    final, periods, grades, briefings, ind = adapter_frames
    confirmed = periods.assign(confirmed_start=["", "2024-05-11"], confirmed_end=["", "2024-05-24"],
                               confirmed_basis=["", "stated range"])
    t = ai.check_briefings(final, confirmed, grades, briefings, ind).set_index("confirmed_group_id")
    b1, b2 = t.loc["B1"], t.loc["B2"]
    assert (b1["period_type"], b1["period_start"], b1["stated_period_end"], b1["period_flag"]) == \
        ("monthly", "2024-05-01", "2024-05-31", "stated: named month")
    assert (b2["period_type"], b2["period_end"], b2["independent_copies"], b2["dhq_copies"]) == \
        ("biweekly", "2024-05-24", 1, 0)
    assert (b2["stated_period_end"], b2["period_flag"]) == ("2024-05-24", "stated: stated range")
    assert (b1["arrested"], b1["arrested_independent_copies_agreeing"], b1["neutralised"], b1["neutralised_final_status"]) \
        == ("10", 2, "", "vague")
    assert not b1["arrested_dhq_text"]


@pytest.mark.parametrize("start,end,expected", [
    ("2024-05-01", "2024-05-31", "monthly"), ("2024-04-01", "2024-06-30", "quarterly"),
    ("2023-06-01", "2023-08-31", "period"), ("2024-01-01", "2024-12-31", "annual"),
    ("2024-05-10", "2024-05-16", "weekly"), ("2023-05-04", "2023-05-18", "biweekly"),
    ("2022-04-29", "2022-05-19", "short"), ("2021-09-02", "2021-09-30", "period"),
])
def test_type_of_dates(start, end, expected):
    assert ai.type_of_dates(date.fromisoformat(start), date.fromisoformat(end)) == expected


def test_period_fields_for_confirmed_bases():
    def row(basis, start="", end=""):
        return {"confirmed_basis": basis, "confirmed_start": start, "confirmed_end": end,
                "proposed_basis": "none", "proposed_start": "", "proposed_end": ""}
    assert ai.period_fields(row("unclear"))["period_type"] == "unclear"
    cum = ai.period_fields(row("cumulative", "2023-05-29", "2025-10-03"))
    assert (cum["period_type"], cum["stated_period_end"]) == ("cumulative", "2025-10-03")
    assert ai.period_fields(row("cumulative"))["stated_period_end"] == ""
    year = ai.period_fields(row("year", "2024-01-01", "2024-12-31"))
    assert (year["period_type"], year["stated_period_end"]) == ("annual", "2024-12-31")
    ytd = ai.period_fields(row("year to date", "2024-01-01", "2024-12-05"))
    assert (ytd["period_type"], ytd["stated_period_end"]) == ("year to date", "")
    dur = ai.period_fields(row("stated duration", "2022-04-29", "2022-05-19"))
    assert (dur["period_type"], dur["stated_period_end"], dur["period_flag"]) == \
        ("short", "", "inferred: stated duration")
    proposed = ai.period_fields({"confirmed_basis": "", "confirmed_start": "", "confirmed_end": "",
                                 "proposed_basis": "inferred weekly", "proposed_start": "2024-02-10",
                                 "proposed_end": "2024-02-16"})
    assert (proposed["period_type"], proposed["period_start"], proposed["stated_period_end"]) == \
        ("weekly", "2024-02-10", "")
