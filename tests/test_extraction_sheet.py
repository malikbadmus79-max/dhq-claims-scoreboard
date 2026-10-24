import pandas as pd
import pytest

import scoreboard.extraction_sheet as es

NATIONAL = ("Troops neutralised 43 terrorists in the North East on Monday. "
            "The Defence Headquarters said troops across the country neutralised no fewer than 98 terrorists "
            "and arrested 115 others in the past week.")
REGIONAL_ONLY = "Troops of Operation Hadin Kai rescued 39 kidnapped victims in Borno."
VAGUE = "The Defence Headquarters said troops neutralised scores of terrorists in the past week."


@pytest.mark.parametrize("title,expected", [
    ("Troops neutralise 43 terrorists, arrest 115 in one week", {"neutralised": (43, ""), "arrested": (115, "")}),
    ("Over 40 Terrorists Killed As Troops Arrest 115 Others", {"neutralised": (40, "over"), "arrested": (115, "")}),
    ("Military kills 2, 351 terrorists in three months", {"neutralised": (2351, "")}),
    ("Troops neutralise scores of terrorists, rescue 76 victims", {"rescued": (76, "")}),
])
def test_headline_figures(title, expected):
    row, _ = es.sheet_row({"confirmed_group_id": "B2024-001", "title": title, "url": "u"}, "")
    got = {o: (row[f"headline_{o}"], row[f"headline_{o}_qualifier"]) for o in es.OUTCOMES if row[f"headline_{o}"] is not None}
    assert got == expected


def test_body_prefers_the_national_sentence_with_its_qualifier():
    f = es.body_figure(NATIONAL, "neutralised")
    assert (f["value"], f["qualifier"], f["rule"]) == (98, "no fewer than", "national marker")
    assert "across the country" in f["evidence"]


def test_body_falls_back_to_the_first_mention():
    f = es.body_figure(REGIONAL_ONLY, "rescued")
    assert (f["value"], f["rule"]) == (39, "first mention")


def test_body_vague_term_is_a_qualifier_without_value():
    f = es.body_figure(VAGUE, "neutralised")
    assert (f["value"], f["qualifier"], f["rule"]) == (None, "scores", "vague only")


def test_body_not_reported_and_no_text():
    assert es.body_figure(NATIONAL, "rescued")["rule"] == "not reported"
    assert es.body_figure("", "rescued")["rule"] == "no text"


@pytest.mark.parametrize("title,check,reason", [
    ("Troops neutralise 98 terrorists, arrest 115", "", ""),
    ("Troops neutralise 100 terrorists, arrest 115", "differs", "neutralised: headline 100 not in body"),
    ("Troops neutralise 43 terrorists, arrest 115", "differs", "neutralised: headline 43 vs body 98"),
    ("Over 90 terrorists killed as troops arrest 115", "", "neutralised: headline 90 (over) not in body, rounded"),
])
def test_proposed_headline_body_check(title, check, reason):
    row, _ = es.sheet_row({"confirmed_group_id": "B2024-001", "title": title, "url": "u"}, NATIONAL)
    assert (row["proposed_headline_body_check"], row["proposed_reason"]) == (check, reason)


def test_no_proposal_without_text():
    row, snippets = es.sheet_row({"confirmed_group_id": "B2024-001", "title": "Troops neutralise 100 terrorists", "url": "u"}, "")
    assert row["proposed_headline_body_check"] == "" and row["body_neutralised_rule"] == "no text"
    assert snippets == [] and row["snippet_ref"] == ""


def test_snippets_go_to_private_rows_one_per_value():
    row, snippets = es.sheet_row({"confirmed_group_id": "B2024-001", "title": "t", "url": "u"}, NATIONAL)
    assert [s["outcome"] for s in snippets] == ["neutralised", "arrested"] and row["snippet_ref"] == "neutralised; arrested"
    assert all(s["briefing_id"] == "B2024-001" and s["url"] == "u" and "across the country" in s["snippet"]
               for s in snippets)
    assert not any("snippet" in k and k != "snippet_ref" for k in row)


@pytest.fixture
def coded(tmp_path):
    texts = {"https://x.ng/a/": NATIONAL, "https://x.ng/b/": REGIONAL_ONLY}
    for i, body in enumerate(texts.values()):
        (tmp_path / f"{i}.txt").write_text(body, encoding="utf-8")
    rows = [("B2024-002", "2024-01-11", "https://x.ng/a/"), ("B2024-001", "2024-01-06", "https://x.ng/c/"),
            ("B2024-001", "2024-01-05", "https://x.ng/b/")]
    df = pd.DataFrame([{"review_id": "", "decided_by": "hand", "outlet": "X", "date": d, "title": "Troops kill 98",
                        "url": u, "confirmed_group_id": b} for b, d, u in rows])
    path = tmp_path / "coded.csv"
    df.to_csv(path, index=False)
    lookup = {u: tmp_path / f"{i}.txt" for i, u in enumerate(texts)} | {"https://x.ng/c/": tmp_path / "missing.txt"}
    return path, lookup.__getitem__


def test_build_orders_rows_and_blanks_missing_text(coded, tmp_path):
    path, lookup = coded
    sheet, snippets = es.build(coded_path=path, sheet_path=tmp_path / "sheet.csv",
                               snippets_path=tmp_path / "private" / "snippets.csv", text_path=lookup)
    assert list(sheet.columns) == es.SHEET_COLUMNS and "body_snippet" not in sheet.columns
    public = (tmp_path / "sheet.csv").read_text(encoding="utf-8")
    assert "across the country" not in public and "Hadin Kai" not in public
    private = pd.read_csv(tmp_path / "private" / "snippets.csv", keep_default_na=False, dtype=str)
    assert list(private.columns) == es.SNIPPET_COLUMNS and private.equals(snippets)
    assert private[["url", "outcome"]].values.tolist() == [["https://x.ng/b/", "rescued"], ["https://x.ng/a/", "neutralised"],
                                                           ["https://x.ng/a/", "arrested"]]
    assert private.loc[0, "briefing_id"] == "B2024-001" and "Hadin Kai" in private.loc[0, "snippet"]
    assert sheet["url"].tolist() == ["https://x.ng/b/", "https://x.ng/c/", "https://x.ng/a/"]
    missing = sheet.set_index("url").loc["https://x.ng/c/"]
    assert missing["text_path"] == "" and missing["body_neutralised_rule"] == "no text"
    assert sheet["confirmed_headline_body_check"].eq("").all() and sheet["extraction_notes"].eq("").all()


def test_refuses_to_overwrite_hand_entries(coded, tmp_path):
    path, lookup = coded
    out = tmp_path / "sheet.csv"
    private = tmp_path / "snippets.csv"
    sheet, _ = es.build(coded_path=path, sheet_path=out, snippets_path=private, text_path=lookup)
    sheet.loc[0, "extraction_notes"] = "checked"
    sheet.to_csv(out, index=False)
    with pytest.raises(RuntimeError):
        es.build(coded_path=path, sheet_path=out, snippets_path=private, text_path=lookup)


@pytest.mark.parametrize("text,outcome,value", [
    ("Similarly, on June 24 troops arrested four suspected kidnappers. Troops arrested 37 suspects in the period.", "arrested", 37),
    ("In the North East, troops on September 11 arrested suspected collaborators across the theatre.", "arrested", None),
    ("He said troops between 17 November and 24 November neutralised nine terrorists. "
     "Troops equally neutralised 11 terrorist elements.", "neutralised", 11),
    ("On the 24th, troops arrested suspects. Troops arrested 52 suspects in the past week.", "arrested", 52),
    ("Troops of Operation Hadin Kai between 11-12 July killed six terrorists.", "neutralised", None),
])
def test_day_numbers_are_not_counts(text, outcome, value):
    assert es.body_figure(text, outcome)["value"] == value


@pytest.mark.parametrize("text,outcome,value,qualifier", [
    ("He said troops also arrested Four Thousand, Three Hundred and Seventy-Five (4,375) suspects nationwide.",
     "arrested", 4375, ""),
    ("Troops rescued over Eighty Two (82) kidnapped victims across the country.", "rescued", 82, "over"),
    ("He added that Two Thousand, Three Hundred and Thirty-Six (2,336) kidnapped hostages were successfully rescued.",
     "rescued", 2336, ""),
])
def test_numbers_in_words_take_bracketed_digits(text, outcome, value, qualifier):
    f = es.body_figure(text, outcome)
    assert (f["value"], f["qualifier"]) == (value, qualifier)
    assert "(" in f["evidence"]  # the snippet is the sentence as published


def test_normalise_keeps_years_and_counts():
    text = "In May 2024 troops arrested 1,051 suspects and neutralised 624 terrorists."
    assert es.normalise(text) == text


@pytest.mark.parametrize("sentence", [
    "Troops of Hadin Kai neutralised 20 terrorists.", "Fansan Yamma troops arrested 5 suspects.",
    "Troops of Operation Delta Safe arrested 12 oil thieves.", "Troops of Udo Ka arrested 9 suspects.",
    "Safe Haven troops rescued 4 victims.", "Whirl Stroke troops neutralised 3 bandits.",
    "In the North-East, troops neutralised 30 terrorists.", "Troops apprehended 18 terrorists across the theatre.",
    "OPHK troops neutralised 7 terrorists.",
])
def test_theatre_or_operation_is_regional(sentence):
    assert es.is_regional_v2(sentence)


@pytest.mark.parametrize("sentence", [
    "Troops across the theatres of operation neutralised 98 terrorists.",
    "The Defence Headquarters said troops neutralised 98 terrorists in the past week.",
])
def test_national_or_unnamed_sentence_is_not_regional(sentence):
    assert not es.is_regional_v2(sentence)


def test_theatre_sentence_does_not_count_as_no_region_named():
    text = ("The Defence Headquarters gave the results of operations on Thursday. "
            "He said troops also apprehended 18 terrorists across the theatre during the period.")
    f = es.body_figure(text, "arrested")
    assert (f["value"], f["rule"]) == (18, "first mention")
    only_theatre = "Troops of Hadin Kai arrested 18 terrorists."
    assert es.body_figure(only_theatre, "arrested")["rule"] == "first mention"


def test_check_coded_counts_and_failures():
    sheet = pd.DataFrame({"url": ["a", "b", "c", "d"]})
    coded = sheet.assign(confirmed_headline_body_check=["differs", "rounded", "not stated", ""],
                         extraction_notes=["n"] * 4)
    assert es.check_coded(sheet, coded).to_dict() == {"differs": 1, "rounded": 1, "not stated": 1, "(blank)": 1}
    with pytest.raises(ValueError, match="do not match"):
        es.check_coded(sheet, coded.iloc[:3])
    with pytest.raises(ValueError, match="do not match"):
        es.check_coded(sheet, coded.assign(url=["a", "b", "c", "e"]))
    with pytest.raises(ValueError, match="not in"):
        es.check_coded(sheet, coded.assign(confirmed_headline_body_check=["differs", "same", "", ""]))
    with pytest.raises(ValueError, match="empty extraction_notes"):
        es.check_coded(sheet, coded.assign(extraction_notes=["n", " ", "n", "n"]))


def test_sentence_inside_an_operation_section_is_not_no_region_named():
    """B2021-017: the theatre figure follows the sentence opening the Operation Hadarin Daji section."""
    text = ("The Defence Headquarters gave an update on military operations across the country on Thursday. "
            "Under Operation Hadarin Daji, the troops sustained land and air offensives. "
            "According to him, a total of 33 bandits were neutralised in the course of the operations.")
    f = es.body_figure(text, "neutralised")
    assert (f["value"], f["rule"]) == (33, "first mention")


def test_national_marker_ends_a_section():
    text = ("Under Operation Hadin Kai, troops carried out several operations. "
            "Across the theatres of operation, troops kept up the offensive. "
            "The DHQ said troops arrested 284 suspects during the month.")
    f = es.body_figure(text, "arrested")
    assert (f["value"], f["rule"]) == (284, "no region named")


def test_pilot_rule_without_sections_is_unchanged():
    from scoreboard.extract import national_total
    text = ("The Defence Headquarters gave an update on Thursday. Under Operation Hadarin Daji, troops attacked. "
            "A total of 33 bandits were neutralised.")
    assert national_total(text, "neutralised")["rule"] == "no region named"
    assert national_total(text, "neutralised", sections=True) is None
