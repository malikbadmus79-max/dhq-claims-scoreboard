import pandas as pd
import pytest

import scoreboard.briefings as br

# (candidate_group, date, outlet, decided_by, period_note, neutralised, arrested, confirmed_group_id, group_notes)
ROWS = [
    ("C0001", "2024-01-05", "A", "hand", "weekly", "43", "115", "B2024-001", br.CONFIRMED_NOTE),
    ("C0001", "2024-01-05", "B", "pilot", "weekly", "43", "", "B2024-001", br.CONFIRMED_NOTE),
    ("C0002", "2024-01-06", "B", "auto_yes", "biweekly", "40", "115", "B2024-001", "Outlet gives one week as two weeks"),
    ("C0003", "2024-01-11", "A", "pilot", "", "", "", "B2024-002", br.CONFIRMED_NOTE),
    ("C0004", "2025-01-02", "C", "hand", "monthly", "", "", "B2025-001", br.CONFIRMED_NOTE),
]


@pytest.fixture
def frames():
    coded = pd.DataFrame([{"review_id": "", "decided_by": d, "candidate_group": c, "date": dt, "outlet": o,
                           "title": f"t{i}", "period_note": p, "period_source": "notes", "neutralised": n,
                           "arrested": a, "rescued": "", "figure_flag": "", "url": f"https://x.ng/{i}/",
                           "confirmed_group_id": b, "group_notes": note}
                          for i, (c, dt, o, d, p, n, a, b, note) in enumerate(ROWS)])
    sheet = coded.assign(confirmed_group_id="", group_notes="")
    pilot = pd.DataFrame({"url": ["https://x.ng/1/", "https://x.ng/3/", "https://x.ng/9/"],
                          "confirmed_group_id": ["B2024-007", "B2024-008", ""]})
    return sheet, coded, pilot


def test_clean_coding_passes_and_counts_merges(frames):
    sheet, coded, _ = frames
    assert br.check_coded(sheet, coded) == {"groups": 3, "candidate groups": 4, "merges": 1, "candidate groups split": 0}


def test_split_candidate_group_is_counted(frames):
    sheet, coded, _ = frames
    coded.loc[3, "candidate_group"] = sheet.loc[3, "candidate_group"] = "C0002"
    assert br.check_coded(sheet, coded)["candidate groups split"] == 1


@pytest.mark.parametrize("change,message", [
    (lambda c: c.drop(index=4), "do not match"),
    (lambda c: c.assign(url=c["url"].where(c.index != 0, "https://x.ng/other/")), "do not match"),
    (lambda c: c.assign(title=c["title"].where(c.index != 0, "changed")), "columns changed from the sheet: title"),
    (lambda c: c.assign(confirmed_group_id=c["confirmed_group_id"].where(c.index != 0, "G1")), "form B<year>-<NNN>"),
    (lambda c: c.assign(confirmed_group_id=c["confirmed_group_id"].where(c.index != 0, "")), "form B<year>-<NNN>"),
    (lambda c: c.assign(group_notes=c["group_notes"].where(c.index != 1, " ")), "empty group_notes"),
    (lambda c: c.assign(confirmed_group_id=c["confirmed_group_id"].replace("B2025-001", "B2024-003")), "ID year differs"),
    (lambda c: c.assign(confirmed_group_id=c["confirmed_group_id"].replace("B2024-002", "B2024-003")), "without gaps"),
    (lambda c: c.assign(confirmed_group_id=c["confirmed_group_id"].replace(
        {"B2024-001": "B2024-002", "B2024-002": "B2024-001"})), "date order"),
])
def test_bad_coding_stops(frames, change, message):
    sheet, coded, _ = frames
    with pytest.raises(br.BriefingError, match=message):
        br.check_coded(sheet, change(coded))


def test_briefing_rows(frames):
    _, coded, pilot = frames
    table, problems = br.briefings(coded, pilot)
    assert problems == [] and list(table.columns) == br.BRIEFING_COLUMNS
    first = table.set_index("briefing_id").loc["B2024-001"]
    assert (first["first_date"], first["last_date"], first["items"], first["outlets"]) == ("2024-01-05", "2024-01-06", 3, 2)
    assert (first["items_hand"], first["items_pilot"], first["items_auto_yes"]) == (1, 1, 1)
    assert first["period_class"] == "" and first["period_classes"] == "weekly 2; biweekly 1"
    assert first["figure_flag"] == "neutralised: 40 vs 43" and first["candidate_groups"] == "C0001, C0002"
    assert first["merge_note"] == "Outlet gives one week as two weeks" and first["pilot_group_id"] == "B2024-007"
    rest = table.set_index("briefing_id")
    assert rest.loc["B2024-002", "period_class"] == "" and rest.loc["B2024-002", "period_classes"] == ""
    assert rest.loc["B2025-001", "period_class"] == "monthly" and rest.loc["B2025-001", "pilot_group_id"] == ""
    assert rest.loc["B2025-001", "figure_flag"] == "" and rest.loc["B2025-001", "merge_note"] == ""


def test_pilot_group_spread_over_two_briefings_is_reported(frames):
    _, coded, pilot = frames
    pilot.loc[1, "confirmed_group_id"] = "B2024-007"
    _, problems = br.briefings(coded, pilot)
    assert problems == ["pilot group B2024-007: B2024-001, B2024-002"]


def test_briefing_holding_two_pilot_groups_is_reported(frames):
    _, coded, pilot = frames
    pilot.loc[1, "url"] = "https://x.ng/0/"
    _, problems = br.briefings(coded, pilot)
    assert problems == ["briefing B2024-001: holds pilot groups B2024-007, B2024-008"]


def test_build_writes_the_table(frames, tmp_path):
    sheet, coded, pilot = frames
    for name, df in (("sheet", sheet), ("coded", coded), ("pilot", pilot)):
        df.to_csv(tmp_path / f"{name}.csv", index=False)
    out = tmp_path / "briefings" / "b.csv"
    stats, table, _ = br.build(tmp_path / "sheet.csv", tmp_path / "coded.csv", tmp_path / "pilot.csv", out)
    assert out.exists() and len(pd.read_csv(out)) == stats["groups"] == 3
