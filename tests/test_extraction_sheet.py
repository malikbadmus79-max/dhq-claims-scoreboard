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
