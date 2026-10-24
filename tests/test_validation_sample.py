import pandas as pd
import pytest

import scoreboard.validation_sample as vs

YEAR_COUNTS = {"2021": 18, "2022": 26, "2023": 38, "2024": 57, "2025": 46, "2026": 35}


@pytest.fixture
def briefings():
    return pd.DataFrame([{"briefing_id": f"B{y}-{i:03d}", "year": y} for y, n in YEAR_COUNTS.items()
                         for i in range(1, n + 1)])


@pytest.fixture
def classification():
    rows = [{"url": f"https://x.ng/{i:03d}/", "outlet": "X", "decided_by": d}
            for i, d in enumerate(["auto_no"] * 313 + ["auto_yes"] * 40 + ["hand"] * 50)]
    return pd.DataFrame(rows)


def test_allocation_is_proportional_and_sums_to_the_share():
    sizes = vs.allocate(pd.Series(YEAR_COUNTS))
    assert sizes.to_dict() == {"2021": 3, "2022": 4, "2023": 6, "2024": 8, "2025": 7, "2026": 5}
    assert sizes.sum() == 33


def test_briefing_draw_is_reproducible_and_stratified(briefings):
    a, b = vs.draw_briefings(briefings), vs.draw_briefings(briefings)
    assert a["briefing_id"].tolist() == b["briefing_id"].tolist()
    assert len(a) == 33 and not a["briefing_id"].duplicated().any()
    assert a.groupby("year").size().to_dict() == vs.allocate(pd.Series(YEAR_COUNTS)).to_dict()
    assert vs.draw_briefings(briefings, seed=1)["briefing_id"].tolist() != a["briefing_id"].tolist()


def test_draw_does_not_depend_on_input_row_order(briefings, classification):
    shuffled = briefings.sample(frac=1, random_state=3)
    assert vs.draw_briefings(shuffled)["briefing_id"].tolist() == vs.draw_briefings(briefings)["briefing_id"].tolist()
    assert (vs.draw_auto_no(classification.sample(frac=1, random_state=3))["url"].tolist()
            == vs.draw_auto_no(classification)["url"].tolist())


def test_auto_no_draw_is_reproducible_and_only_auto_no(classification):
    a, b = vs.draw_auto_no(classification), vs.draw_auto_no(classification)
    assert a["url"].tolist() == b["url"].tolist()
    assert len(a) == 47 and a["decided_by"].eq("auto_no").all() and not a["url"].duplicated().any()


def test_sheets_carry_no_figures_dates_or_decision(briefings, classification):
    sample = vs.draw_briefings(briefings).head(2)
    coded = pd.DataFrame([{"confirmed_group_id": b, "date": "2024-01-0" + str(k), "outlet": f"O{k}",
                           "url": f"{b}/{k}", "neutralised": "43", "title": "Troops kill 43"}
                          for b in sample["briefing_id"] for k in (2, 1)])
    sheet = vs.briefing_sheet(sample, coded)
    assert list(sheet.columns) == vs.BRIEFING_COLUMNS
    assert sheet[vs.BRIEFING_CODE_COLUMNS].eq("").all().all()
    assert sheet.loc[0, "copy_outlets"] == "O1; O2"
    assert "43" not in sheet.to_csv(index=False).replace(sample["briefing_id"].iloc[0], "")
    items = vs.draw_auto_no(classification)
    auto = vs.auto_no_sheet(items, pd.Series({items["url"].iloc[0]: "headline"}))
    assert list(auto.columns) == vs.AUTO_NO_COLUMNS and "decided_by" not in auto.columns
    assert auto["item_id"].iloc[0] == "V001" and auto[["code", "notes"]].eq("").all().all()


def test_coded_sheet_is_not_overwritten(tmp_path):
    path = tmp_path / "s.csv"
    pd.DataFrame({"item_id": ["V001"], "code": ["no"], "notes": [""]}).to_csv(path, index=False)
    with pytest.raises(RuntimeError):
        vs.write_blank(pd.DataFrame({"item_id": ["V001"], "code": [""], "notes": [""]}), path, ["code", "notes"])


def test_round2_draw_excludes_round1_and_is_reproducible(briefings):
    round1 = vs.draw_briefings(briefings)["briefing_id"]
    a = vs.draw_briefings(briefings, seed=vs.ROUND2_SEED, exclude=round1)
    b = vs.draw_briefings(briefings, seed=vs.ROUND2_SEED, exclude=round1)
    assert a["briefing_id"].tolist() == b["briefing_id"].tolist()
    assert not a["briefing_id"].isin(round1).any() and len(a) == 33 and not a["briefing_id"].duplicated().any()
    assert a.groupby("year").size().to_dict() == vs.allocate(pd.Series(YEAR_COUNTS)).to_dict()


def test_round2_sheet_has_the_round1_format(briefings, tmp_path):
    briefings.to_csv(tmp_path / "b.csv", index=False)
    round1 = vs.draw_briefings(briefings)
    round1.to_csv(tmp_path / "r1.csv", index=False)
    coded = pd.DataFrame([{"confirmed_group_id": b, "date": "2024-01-01", "outlet": "O", "url": f"{b}/1"}
                          for b in briefings["briefing_id"]])
    coded.to_csv(tmp_path / "c.csv", index=False)
    drawn = vs.build_round2(tmp_path / "b.csv", tmp_path / "c.csv", tmp_path / "r1.csv", tmp_path / "r2.csv")
    sheet = pd.read_csv(tmp_path / "r2.csv", keep_default_na=False, dtype=str)
    assert list(sheet.columns) == vs.BRIEFING_COLUMNS and sheet[vs.BRIEFING_CODE_COLUMNS].eq("").all().all()
    assert sheet["briefing_id"].tolist() == drawn["briefing_id"].tolist()
    assert not sheet["briefing_id"].isin(round1["briefing_id"]).any()
