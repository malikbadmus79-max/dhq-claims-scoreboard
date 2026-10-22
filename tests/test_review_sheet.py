import pandas as pd
import pytest

import scoreboard.review_sheet as rs


@pytest.fixture
def tables(tmp_path):
    """Per year: one item of each decision; the "no text" item has no stored text. Dates run backwards
    through the inventory so the sheet must reorder them."""
    texts = tmp_path / "text"
    texts.mkdir()
    for year in rs.YEARS:
        rows = [{"url": f"https://x.ng/{year}/item{i}/", "outlet": "X" if d != "uncertain" else "A",
                 "date": f"{year}-0{9 - i}-01", "decision": d, "rules_fired": "no_number_no_period",
                 "reason": "r", "guard": "moved" if d == "uncertain" else ""}
                for i, d in enumerate(["yes", "no", "uncertain", "no text"])]
        pd.DataFrame(rows).to_csv(tmp_path / f"full_triage_{year}.csv", index=False)
        pd.DataFrame([{"url": r["url"], "title": f"title {i}"} for i, r in enumerate(rows)]).to_csv(
            tmp_path / f"full_inventory_{year}.csv", index=False)
        (texts / f"{year}-item2.txt").write_text("body", encoding="utf-8")
    return tmp_path


def fake_text_path(tables):
    return lambda url: tables / "text" / f"{url.split('/')[-3]}-{url.split('/')[-2]}.txt"


def test_sheet_holds_only_undecided_items_blind_and_in_date_order(tables):
    sheet, batches = tables / "sheet.csv", tables / "batches.csv"
    items, _ = rs.build(tables_dir=tables, sheet=sheet, batches=batches, text_path=fake_text_path(tables))
    assert len(items) == 2 * len(rs.YEARS) and list(items.columns) == rs.SHEET_COLUMNS
    assert items["date"].tolist() == sorted(items["date"]) and items["review_id"].iloc[0] == "R0001"
    assert items.loc[items["title"] == "title 3", "has_text"].eq(False).all()
    assert items.loc[~items["has_text"], "text_path"].eq("").all()
    assert items.loc[items["has_text"], "text_path"].str.endswith(".txt").all()
    blind = sheet.read_text(encoding="utf-8")
    assert "no_number_no_period" not in blind and "moved" not in blind and "uncertain" not in blind


def test_batches_split_by_size(tables, monkeypatch):
    monkeypatch.setattr(rs, "BATCH_SIZE", 5)
    items, table = rs.build(tables_dir=tables, sheet=tables / "s.csv", batches=tables / "b.csv",
                            text_path=fake_text_path(tables))
    assert table["items"].tolist() == [5, 5, 2] and table["first_review_id"].tolist() == ["R0001", "R0006", "R0011"]
    assert table.loc[2, "last_date"] == items["date"].iloc[-1]


def test_refuses_to_overwrite_a_coded_sheet(tables):
    sheet = tables / "sheet.csv"
    items, _ = rs.build(tables_dir=tables, sheet=sheet, batches=tables / "b.csv", text_path=fake_text_path(tables))
    items.loc[0, "notes"] = "x"
    items.to_csv(sheet, index=False)
    with pytest.raises(RuntimeError):
        rs.build(tables_dir=tables, sheet=sheet, batches=tables / "b.csv", text_path=fake_text_path(tables))
