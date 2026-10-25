import pandas as pd
import pytest

import scoreboard.audit_v1_1 as v11

FINAL_COLUMNS = ["briefing_id", "briefing_date", "period_class", "outcome", "value", "qualifier", "final_status",
                 "source", "auto_value", "auto_status", "notes"]
CORRECTION_COLUMNS = ["briefing_id", "outcome", "auto_value", "auto_qualifier", "auto_status", "corrected_value",
                      "corrected_qualifier", "corrected_status", "reason"]


@pytest.fixture
def final():
    rows = [("B1", "2023-01-12", "short", "neutralised", "", "", "not reported", "correction", "50", "agreed", "n"),
            ("B1", "2023-01-12", "short", "arrested", "", "", "not reported", "hand", "", "needs hand extraction", "n"),
            ("B1", "2023-01-12", "short", "rescued", "47", "", "reported", "automatic", "47", "agreed", ""),
            ("B2", "2023-07-06", "weekly", "neutralised", "30", "", "reported", "automatic", "30", "agreed", ""),
            ("B2", "2023-07-06", "weekly", "arrested", "12", "", "reported", "hand", "", "majority", "m"),
            ("B2", "2023-07-06", "weekly", "rescued", "", "", "vague", "hand", "", "needs hand extraction", "v")]
    return pd.DataFrame(rows, columns=FINAL_COLUMNS)


@pytest.fixture
def corrections():
    return pd.DataFrame([("B1", "rescued", "47", "", "reported", "", "", "not reported", "North East section figure")],
                        columns=CORRECTION_COLUMNS)


def test_clean_corrections_pass_and_apply(final, corrections):
    assert v11.check_corrections(corrections, final) == []
    out = v11.apply_corrections(final, corrections).set_index(["briefing_id", "outcome"])
    r = out.loc[("B1", "rescued")]
    assert (r["value"], r["final_status"], r["source"], r["notes"]) == \
        ("", "not reported", "correction v1.1", "North East section figure")
    assert (r["auto_value"], r["auto_status"]) == ("47", "agreed")
    assert out.loc[("B2", "neutralised"), "source"] == "automatic" and len(out) == len(final)
    assert list(v11.apply_corrections(final, corrections).columns) == FINAL_COLUMNS


@pytest.mark.parametrize("change,message", [
    (lambda c: pd.concat([c, c]), "duplicate key"),
    (lambda c: c.assign(briefing_id="B9"), "B9 rescued: not in"),
    (lambda c: c.assign(auto_value="48"), "auto_value '48' but v1.0 value is '47'"),
    (lambda c: c.assign(auto_status="agreed"), "auto_status 'agreed' but v1.0 final_status is 'reported'"),
    (lambda c: c.assign(corrected_status="probable"), "corrected_status 'probable' not allowed"),
    (lambda c: c.assign(corrected_status="reported"), "is not a positive integer"),
    (lambda c: c.assign(corrected_value="40"), "corrected_value given with status 'not reported'"),
    (lambda c: c.assign(reason=" "), "empty reason"),
])
def test_each_correction_failure_is_reported(final, corrections, change, message):
    failures = v11.check_corrections(change(corrections).reset_index(drop=True), final)
    assert any(message in f for f in failures), failures


def test_flags_must_be_single_copy_reported_values_before_july_2023(final):
    grades = pd.DataFrame([("B1", "rescued", "1"), ("B2", "neutralised", "1"), ("B2", "arrested", "3")],
                          columns=["briefing_id", "outcome", "independent_copies_supporting"])
    flag = lambda b, o, v: pd.DataFrame([(b, o, v, "note")], columns=["briefing_id", "outcome", "value", "note"])
    assert v11.check_flags(flag("B1", "rescued", "47"), final, grades) == []
    assert "not reported with value" in v11.check_flags(flag("B1", "arrested", ""), final, grades)[0]
    assert "3 independent copies, not 1" in v11.check_flags(flag("B2", "arrested", "12"), final, grades)[0]
    assert "not before 2023-07-01" in v11.check_flags(flag("B2", "neutralised", "30"), final, grades)[0]


def test_check_table_applies_values_dhq_copies_and_exclusions(final, corrections):
    check = pd.DataFrame({"confirmed_group_id": ["B1", "B2"], "dhq_copies": ["0", "0"],
                          **{f"{o}{s}": ["x", "x"] for o in v11.OUTCOMES
                             for s in ("", "_qualifier", "_final_status", "_source")},
                          **{f"{o}_independent_copies_agreeing": ["2", "2"] for o in v11.OUTCOMES}})
    comparison = pd.DataFrame({"briefing_id": ["B1", "B9"], "verdict": ["v1.0 error (rescued)", "no match"]})
    t = v11.check_table(check, v11.apply_corrections(final, corrections), comparison).set_index("confirmed_group_id")
    assert (t.loc["B1", "rescued"], t.loc["B1", "rescued_final_status"], t.loc["B1", "rescued_source"]) == \
        ("", "not reported", "correction v1.1")
    assert t.loc["B1", "rescued_independent_copies_agreeing"] == "0"
    assert (t.loc["B2", "neutralised"], t.loc["B2", "neutralised_independent_copies_agreeing"]) == ("30", "2")
    assert t.loc["B2", "rescued"] == "" and t.loc["B2", "rescued_final_status"] == "vague"
    assert (t.loc["B1", "dhq_copies"], t.loc["B2", "dhq_copies"]) == ("1", "0")
    flags = pd.DataFrame([("B2", "neutralised", "30", "note")], columns=["briefing_id", "outcome", "value", "note"])
    ex = v11.check_table(check, final, comparison, flags).set_index("confirmed_group_id")
    assert (ex.loc["B2", "neutralised"], ex.loc["B2", "neutralised_independent_copies_agreeing"]) == ("", "0")
    assert ex.loc["B2", "arrested"] == "12"
