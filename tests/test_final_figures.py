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
    assert check(hand.assign(confirmed_qualifier=["", "thousands", "", ""]), auto) == []


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


def write_frames(tmp_path, **frames):
    for name, df in frames.items():
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    return [tmp_path / f"{n}.csv" for n in ("hand", "auto", "briefings")] + [tmp_path / "final.csv"]


def test_failing_hand_file_writes_nothing(frames, corrections, tmp_path):
    auto, hand, briefings = frames
    paths = write_frames(tmp_path, auto=auto, hand=hand, briefings=briefings, corrections=corrections)
    table, failures = ff.build(*paths, corrections_path=tmp_path / "corrections.csv")
    assert table is None and failures == ["row count 4, expected 357"] and not paths[-1].exists()


@pytest.fixture
def corrections():
    return pd.DataFrame([
        ("B1", "neutralised", "43", "no fewer than", "agreed", "", "", "not reported",
         "Multi-theatre figure for the North-West and North-Central theatres"),
        ("B2", "arrested", "20", "", "agreed", "", "several", "vague", "National claim without a number"),
    ], columns=["briefing_id", "outcome", "auto_value", "auto_qualifier", "auto_status", "corrected_value",
                "corrected_qualifier", "corrected_status", "reason"])


def test_clean_corrections_file_passes(frames, corrections):
    auto, _, _ = frames
    assert ff.check_corrections(corrections, auto) == []
    reported = corrections.assign(corrected_value=["40", ""], corrected_status=["reported", "vague"])
    assert ff.check_corrections(reported, auto) == []
    unresolved = corrections.assign(corrected_status=["unresolved", "vague"])
    assert ff.check_corrections(unresolved, auto) == []
    qualified = corrections.assign(corrected_value=["40", ""], corrected_qualifier=["summed categories", "thousands"],
                                   corrected_status=["reported", "vague"])
    assert ff.check_corrections(qualified, auto) == []


@pytest.mark.parametrize("change,message", [
    (lambda c: pd.concat([c, c.iloc[[0]]]), "B1 neutralised: duplicate key"),
    (lambda c: c.assign(briefing_id=["B9", "B2"]), "B9 neutralised: not in briefing_figures.csv"),
    (lambda c: c.assign(outcome=["arrested", "arrested"], auto_value=["115", "20"]),
     "B1 arrested: status 'majority' in briefing_figures.csv, not agreed"),
    (lambda c: c.assign(auto_value=["42", "20"]), "B1 neutralised: auto_value '42' but briefing_figures.csv has '43'"),
    (lambda c: c.assign(corrected_status=["probable", "vague"]), "corrected_status 'probable' not one of"),
    (lambda c: c.assign(corrected_value=["40", ""], corrected_status=["unresolved", "vague"]),
     "corrected_value '40' given with status 'unresolved'"),
    (lambda c: c.assign(corrected_qualifier=["about", "several"]), "corrected_qualifier 'about' not allowed"),
    (lambda c: c.assign(corrected_qualifier=["thousands", "several"]), "vague term 'thousands' with status 'not reported'"),
    (lambda c: c.assign(corrected_status=["reported", "vague"]), "reported but corrected_value '' is not a positive"),
    (lambda c: c.assign(corrected_value=["43", ""]), "corrected_value '43' given with status 'not reported'"),
    (lambda c: c.assign(reason=["r", "  "]), "B2 arrested: empty reason"),
])
def test_each_corrections_failure_is_reported(frames, corrections, change, message):
    auto, _, _ = frames
    failures = ff.check_corrections(change(corrections).reset_index(drop=True), auto)
    assert any(message in f for f in failures), failures


def test_corrections_override_automatic_rows(frames, corrections):
    auto, hand, briefings = frames
    r = ff.final_table(auto, hand, briefings, corrections).set_index(["briefing_id", "outcome"])
    c = r.loc[("B1", "neutralised")]
    assert (c["value"], c["qualifier"], c["final_status"], c["source"]) == ("", "", "not reported", "correction")
    assert (c["auto_value"], c["auto_status"]) == ("43", "agreed")
    assert c["notes"] == "Multi-theatre figure for the North-West and North-Central theatres"
    v = r.loc[("B2", "arrested")]
    assert (v["value"], v["qualifier"], v["final_status"], v["source"]) == ("", "several", "vague", "correction")
    assert r.loc[("B1", "arrested"), "source"] == "hand" and len(r) == len(auto)
    assert ff.final_table(auto, hand, briefings).set_index(["briefing_id", "outcome"]).loc[
        ("B1", "neutralised"), "source"] == "automatic"


def test_failing_corrections_file_writes_nothing(frames, corrections, tmp_path, monkeypatch):
    auto, hand, briefings = frames
    monkeypatch.setattr(ff, "HAND_ROWS", 4)
    monkeypatch.setattr(ff.check_hand, "__defaults__", (4,))
    paths = write_frames(tmp_path, auto=auto, hand=hand, briefings=briefings,
                         corrections=corrections.assign(auto_value=["42", "20"]))
    table, failures = ff.build(*paths, corrections_path=tmp_path / "corrections.csv")
    assert table is None and not paths[-1].exists()
    assert failures == ["corrections.csv: B1 neutralised: auto_value '42' but briefing_figures.csv has '43'"]
    write_frames(tmp_path, corrections=corrections)
    table, failures = ff.build(*paths, corrections_path=tmp_path / "corrections.csv")
    assert failures == [] and paths[-1].exists() and (table["source"] == "correction").sum() == 2


def test_conflict_review_keys_match_tagged_corrections(corrections):
    review = pd.DataFrame([("B1", "neutralised", "Corrected: multi-theatre figure"), ("B2", "arrested", "Kept: national")],
                          columns=["briefing_id", "outcome", "decision"])
    tagged = corrections.assign(reason=["Found in the round-2 conflict review.", "Found in validation round 2."])
    assert ff.check_conflict_review(review, tagged) == []
    assert ff.check_conflict_review(review, corrections) == [
        "B1 neutralised: corrected in the conflict review but no tagged correction"]
    both = corrections.assign(reason="Found in the round-2 conflict review.")
    assert ff.check_conflict_review(review, both) == [
        "B2 arrested: tagged correction not marked corrected in the conflict review"]


def test_project_conflict_review_matches_follow_up_corrections():
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    review, corrections = read(ff.CONFLICT_REVIEW), read(ff.CORRECTIONS)
    assert ff.check_conflict_review(review, corrections) == []
    assert review["decision"].str.startswith("Corrected").sum() == 9
