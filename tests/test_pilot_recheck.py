import pandas as pd
import pytest

import scoreboard.pilot_recheck as pr


@pytest.fixture
def pilot(tmp_path):
    """Three pilot items with dates running backwards; only the second has stored text."""
    rows = [{"briefing_group_id": "", "outlet": "X", "publish_date": f"2024-0{3 - i}-01", "title": f"t{i}",
             "url": f"https://x.ng/p{i}/", "is_operational_briefing": code, "confirmed_group_id": "", "notes": note}
            for i, (code, note) in enumerate([("yes", "Period: weekly."), ("no", ""), ("yes", "n")])]
    path = tmp_path / "pilot.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    (tmp_path / "p1.txt").write_text("body", encoding="utf-8")
    return path


def fake_text_path(pilot):
    return lambda url: pilot.parent / f"{url.split('/')[-2]}.txt"


def test_sheet_layout_order_and_pilot_codes(pilot):
    before = pilot.read_bytes()
    items = pr.build(pilot_path=pilot, sheet=pilot.parent / "s.csv", text_path=fake_text_path(pilot))
    assert list(items.columns) == pr.RECHECK_COLUMNS
    assert items["review_id"].tolist() == ["P001", "P002", "P003"] and items["batch"].eq("P01").all()
    assert items["date"].tolist() == sorted(items["date"]) and items["year"].eq("2024").all()
    assert items["pilot_code"].tolist() == ["yes", "no", "yes"] and items["pilot_notes"].tolist() == ["n", "", "Period: weekly."]
    assert items["has_text"].tolist() == [False, True, False] and items.loc[1, "text_path"].endswith("p1.txt")
    assert items["is_operational_briefing"].eq("").all() and items["notes"].eq("").all()
    assert pilot.read_bytes() == before


def test_refuses_to_overwrite_a_coded_recheck_sheet(pilot):
    sheet = pilot.parent / "s.csv"
    items = pr.build(pilot_path=pilot, sheet=sheet, text_path=fake_text_path(pilot))
    items.loc[0, "is_operational_briefing"] = "yes"
    items.to_csv(sheet, index=False)
    with pytest.raises(RuntimeError):
        pr.build(pilot_path=pilot, sheet=sheet, text_path=fake_text_path(pilot))
