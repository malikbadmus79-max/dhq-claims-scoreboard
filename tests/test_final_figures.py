import pandas as pd
import pytest

import scoreboard.final_figures as ff


@pytest.fixture
def frames():
    auto = pd.DataFrame([
        ("B1", "neutralised", "43", "no fewer than", "agreed"),
        ("B1", "arrested", "115", "", "majority"),
        ("B1", "rescued", "", "", "needs hand extraction"),
        ("B2", "neutralised", "", "", "conflict"),
        ("B2", "arrested", "20", "", "agreed"),
        ("B2", "rescued", "", "", "needs hand extraction"),
    ], columns=["briefing_id", "outcome", "value", "qualifier", "status"])
    hand = pd.DataFrame([
        ("B1", "arrested", "118", "", "reported", "Two of three independent copies give 118"),
        ("B1", "rescued", "", "scores", "vague", "National claim without a number"),
        ("B2", "neutralised", "", "", "unresolved", "40 and 43 on one independent copy each"),
        ("B2", "rescued", "", "", "not reported", "Only a North East figure"),
    ], columns=["briefing_id", "outcome", "confirmed_value", "confirmed_qualifier", "confirmed_status", "figure_notes"])
    briefings = pd.DataFrame({"briefing_id": ["B1", "B2"], "first_date": ["2024-01-05", "2025-02-06"],
                              "period_class": ["weekly", ""], "period_classes": ["weekly 3", "weekly 2; biweekly 1"]})
    return auto, hand, briefings


def check(hand, auto):
    return ff.check_hand(hand, auto, expected=4)


def test_clean_hand_file_passes(frames):
    auto, hand, _ = frames
    assert check(hand, auto) == []
    assert ff.check_hand(hand, auto) == ["row count 4, expected 357"]
    assert check(hand.iloc[:3], auto)[0] == "row count 3, expected 4"


@pytest.mark.parametrize("change,message", [
    (lambda h: pd.concat([h, h.iloc[[0]]]), "B1 arrested: duplicate key"),
    (lambda h: h.iloc[1:], "B1 arrested: missing from the hand file"),
    (lambda h: h.assign(outcome=h["outcome"].replace("arrested", "neutralised")), "B1 neutralised: not a conflict"),
    (lambda h: h.assign(confirmed_status=h["confirmed_status"].replace("vague", "probable")), "not one of"),
    (lambda h: h.assign(confirmed_value=h["confirmed_value"].replace("118", "")), "not a positive integer"),
    (lambda h: h.assign(confirmed_value=h["confirmed_value"].replace("118", "0")), "not a positive integer"),
    (lambda h: h.assign(confirmed_value=h["confirmed_value"].replace("118", "1,180")), "not a positive integer"),
    (lambda h: h.assign(confirmed_value=["118", "5", "", ""]), "given with status 'vague'"),
    (lambda h: h.assign(confirmed_qualifier=["about", "scores", "", ""]), "'about' not allowed"),
    (lambda h: h.assign(confirmed_qualifier=["plus 5 named", "scores", "", ""]), "'plus 5 named' not allowed"),
    (lambda h: h.assign(confirmed_qualifier=["scores", "scores", "", ""]), "vague term 'scores' with status 'reported'"),
    (lambda h: h.assign(figure_notes=["n", " ", "n", "n"]), "B1 rescued: empty figure_notes"),
])
def test_each_failure_is_reported(frames, change, message):
    auto, hand, _ = frames
    failures = check(change(hand).reset_index(drop=True), auto)
    assert any(message in f for f in failures), failures


def test_allowed_qualifiers_pass(frames):
    auto, hand, _ = frames
    for q in ("over", "no fewer than", "at least", "summed categories", "plus 2"):
        assert check(hand.assign(confirmed_qualifier=[q, "", "", ""]), auto) == []


def test_merge_gives_one_row_per_key_with_hand_overriding(frames):
    auto, hand, briefings = frames
    t = ff.final_table(auto, hand, briefings)
    assert list(t.columns) == ff.FINAL_COLUMNS and len(t) == len(auto)
    assert not t.duplicated(["briefing_id", "outcome"]).any()
    r = t.set_index(["briefing_id", "outcome"])
    hand_row = r.loc[("B1", "arrested")]
    assert (hand_row["value"], hand_row["final_status"], hand_row["source"]) == ("118", "reported", "hand")
    assert (hand_row["auto_value"], hand_row["auto_status"]) == ("115", "majority")
    assert hand_row["notes"] == "Two of three independent copies give 118"
    assert (r.loc[("B2", "neutralised"), "final_status"], r.loc[("B2", "neutralised"), "value"]) == ("unresolved", "")
    assert r.loc[("B1", "rescued"), "qualifier"] == "scores"


def test_agreed_rows_are_unchanged(frames):
    auto, hand, briefings = frames
    r = ff.final_table(auto, hand, briefings).set_index(["briefing_id", "outcome"])
    agreed = r.loc[("B1", "neutralised")]
    assert (agreed["value"], agreed["qualifier"], agreed["final_status"], agreed["source"], agreed["notes"]) == \
        ("43", "no fewer than", "reported", "automatic", "")
    assert (agreed["auto_value"], agreed["auto_status"]) == ("43", "agreed")
    assert (r.loc[("B2", "arrested"), "value"], r.loc[("B2", "arrested"), "source"]) == ("20", "automatic")


def test_briefing_date_and_period(frames):
    auto, hand, briefings = frames
    r = ff.final_table(auto, hand, briefings).set_index(["briefing_id", "outcome"])
    assert (r.loc[("B1", "arrested"), "briefing_date"], r.loc[("B1", "arrested"), "period_class"]) == ("2024-01-05", "weekly")
    assert r.loc[("B2", "rescued"), "period_class"] == "weekly 2; biweekly 1"


def test_non_agreed_row_without_hand_row_stops_the_merge(frames):
    auto, hand, briefings = frames
    with pytest.raises(ValueError, match="B1 arrested"):
        ff.final_table(auto, hand.iloc[1:], briefings)


def test_failing_hand_file_writes_nothing(frames, tmp_path):
    auto, hand, briefings = frames
    for name, df in (("auto", auto), ("hand", hand), ("briefings", briefings)):
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    out = tmp_path / "final.csv"
    table, failures = ff.build(tmp_path / "hand.csv", tmp_path / "auto.csv", tmp_path / "briefings.csv", out)
    assert table is None and failures == ["row count 4, expected 357"] and not out.exists()
