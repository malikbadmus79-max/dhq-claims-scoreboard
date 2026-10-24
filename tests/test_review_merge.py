import pandas as pd
import pytest

import scoreboard.review_merge as rm

N = 6
YEARS = [str(y) for y in rm.YEARS]


@pytest.fixture
def files(tmp_path):
    """Six review items in two batches of three, the last one without text; per year one auto-yes, one
    auto-no and one pilot-labelled item outside triage. The review items all sit in the first year's triage."""
    sheet = pd.DataFrame([{"review_id": f"R{i:04d}", "batch": f"B{(i - 1) // 3 + 1:02d}", "year": YEARS[0],
                           "outlet": "X", "date": f"{YEARS[0]}-01-0{i}", "title": f"t{i}",
                           "url": f"https://x.ng/r{i}/", "has_text": "False" if i == N else "True",
                           "text_path": "", "is_operational_briefing": "", "notes": ""} for i in range(1, N + 1)])
    sheet.to_csv(tmp_path / "sheet.csv", index=False)
    coded = sheet.drop(columns=["has_text", "text_path"]).assign(
        is_operational_briefing=["yes", "no", "yes", "no", "yes", "unsure"],
        notes=["n"] * (N - 1) + ["no text"])
    for b, part in coded.groupby("batch"):
        part.to_csv(rm.coded_path(tmp_path, b), index=False)
    labels = []
    for y in YEARS:
        triage = [{"url": f"https://x.ng/{y}/{d}/", "outlet": "X", "date": f"{y}-02-01", "decision": d}
                  for d in ("yes", "no")]
        if y == YEARS[0]:
            triage += [{"url": u, "outlet": "X", "date": "", "decision": "no text" if h == "False" else "uncertain"}
                       for u, h in zip(sheet["url"], sheet["has_text"])]
        pd.DataFrame(triage).to_csv(tmp_path / f"full_triage_{y}.csv", index=False)
        inv = [{"url": r["url"], "outlet": "X", "publish_date": r["date"]} for r in triage]
        inv.append({"url": f"https://x.ng/{y}/pilot/", "outlet": "X", "publish_date": f"{y}-03-01"})
        pd.DataFrame(inv).to_csv(tmp_path / f"full_inventory_{y}.csv", index=False)
        labels.append({"year": y, "outlet": "X", "url": f"https://x.ng/{y}/pilot/", "is_operational_briefing": "no",
                       "label_source": "pilot", "pilot_item_id": f"P{y}-r001"})
    pd.DataFrame(labels).to_csv(tmp_path / "labels.csv", index=False)
    recheck = pd.DataFrame([{"review_id": f"P{i:03d}", "url": l["url"], "pilot_code": "no",
                             "recheck_code": "yes" if i == 1 else "no", "changed": "yes" if i == 1 else "no",
                             "notes": "n"} for i, l in enumerate(labels, start=1)])
    recheck[["review_id", "url"]].to_csv(tmp_path / "recheck_sheet.csv", index=False)
    recheck.to_csv(tmp_path / "recheck_coded.csv", index=False)
    return tmp_path


def run(files):
    return rm.run(sheet_path=files / "sheet.csv", review_dir=files, tables_dir=files, labels_path=files / "labels.csv",
                  merged_path=files / "merged.csv", classification_path=files / "class.csv",
                  summary_path=files / "summary.csv", expected=N, recheck_sheet_path=files / "recheck_sheet.csv",
                  recheck_path=files / "recheck_coded.csv", recheck_expected=len(YEARS),
                  overrides_path=files / "overrides.csv")


def write_overrides(files, *rows):
    pd.DataFrame(rows, columns=rm.OVERRIDE_COLUMNS).to_csv(files / "overrides.csv", index=False)


def edit(files, batch_file, path=None, **changes):
    """Rewrites one coded batch file, or the file at path; each change maps a column to {row position: value}."""
    path = path or rm.coded_path(files, batch_file)
    df = pd.read_csv(path, keep_default_na=False, dtype=str)
    for col, values in changes.items():
        for pos, value in values.items():
            df.loc[pos, col] = value
    df.to_csv(path, index=False)
    return df


def test_clean_merge_and_classification(files):
    merged, classification, table, unclassified = run(files)
    assert list(merged.columns) == rm.MERGED_COLUMNS and merged["review_id"].tolist() == [f"R{i:04d}" for i in range(1, N + 1)]
    assert classification["decided_by"].value_counts().to_dict() == {"auto_yes": 6, "auto_no": 6, "hand": N, "pilot": 6}
    assert table["items"].sum() == len(classification) == 3 * len(YEARS) + N
    assert unclassified.empty
    pilot = classification[classification["decided_by"] == "pilot"]
    assert pilot["review_id"].str.startswith("P").all() and pilot["original_pilot_code"].eq("no").all()
    assert classification.loc[classification["decided_by"] != "pilot", "original_pilot_code"].eq("").all()
    assert (files / "merged.csv").exists() and (files / "class.csv").exists() and (files / "summary.csv").exists()


def test_missing_batch_file(files):
    rm.coded_path(files, "B02").unlink()
    with pytest.raises(rm.MergeError, match="missing: B02"):
        run(files)


def test_wrong_row_count(files):
    df = pd.read_csv(rm.coded_path(files, "B02"), keep_default_na=False, dtype=str)
    df.iloc[:-1].to_csv(rm.coded_path(files, "B02"), index=False)
    with pytest.raises(rm.MergeError, match="expected 6 coded rows, found 5"):
        run(files)


def test_duplicate_review_id(files):
    edit(files, "B02", review_id={0: "R0003"})
    with pytest.raises(rm.MergeError, match="duplicate review_id: R0003"):
        run(files)


def test_gap_in_review_id(files):
    edit(files, "B02", review_id={0: "R0007"})
    with pytest.raises(rm.MergeError, match="missing \\['R0004'\\]"):
        run(files)


@pytest.mark.parametrize("column,value", [("batch", "B01"), ("url", "https://x.ng/other/")])
def test_coded_row_differs_from_sheet(files, column, value):
    edit(files, "B02", **{column: {0: value}})
    with pytest.raises(rm.MergeError, match="differ from the sheet.*R0004"):
        run(files)


def test_invalid_code(files):
    edit(files, "B01", is_operational_briefing={1: "maybe"})
    with pytest.raises(rm.MergeError, match="not one of yes, no, unsure: R0002"):
        run(files)


def test_row_without_text_not_unsure(files):
    edit(files, "B02", is_operational_briefing={2: "no"})
    with pytest.raises(rm.MergeError, match="without text not coded unsure: R0006"):
        run(files)


def test_unsure_row_with_text(files):
    edit(files, "B01", is_operational_briefing={0: "unsure"})
    with pytest.raises(rm.MergeError, match="unsure rows that have text: R0001"):
        run(files)


def test_empty_notes(files):
    edit(files, "B01", notes={2: " "})
    with pytest.raises(rm.MergeError, match="empty notes: R0003"):
        run(files)


def test_item_both_auto_and_hand(files):
    path = files / f"full_triage_{YEARS[0]}.csv"
    triage = pd.read_csv(path, keep_default_na=False, dtype=str)
    triage.loc[triage["url"] == "https://x.ng/r1/", "decision"] = "yes"
    triage.to_csv(path, index=False)
    with pytest.raises(rm.MergeError, match="both auto-decided and hand-coded"):
        run(files)


def test_no_output_written_when_a_check_fails(files):
    edit(files, "B01", notes={0: ""})
    with pytest.raises(rm.MergeError):
        run(files)
    assert not (files / "merged.csv").exists() and not (files / "class.csv").exists()


def test_every_discovered_item_appears_exactly_once(files):
    _, classification, _, _ = run(files)
    inventory = rm.read_years(files, "full_inventory")
    assert not classification["url"].duplicated().any()
    assert sorted(classification["url"]) == sorted(inventory["url"])


def test_pilot_item_also_auto_decided(files):
    labels = pd.read_csv(files / "labels.csv", keep_default_na=False, dtype=str)
    labels.loc[0, "url"] = f"https://x.ng/{YEARS[1]}/yes/"
    labels.to_csv(files / "labels.csv", index=False)
    with pytest.raises(rm.MergeError, match="pilot-labelled items are also auto-decided"):
        run(files)


def recheck_edit(files, **changes):
    return edit(files, None, path=files / "recheck_coded.csv", **changes)


def test_pilot_rows_use_the_recheck_code(files):
    _, classification, table, _ = run(files)
    pilot = classification[classification["decided_by"] == "pilot"].set_index("url")
    first = f"https://x.ng/{YEARS[0]}/pilot/"
    assert pilot.loc[first, "is_operational_briefing"] == "yes" and pilot.loc[first, "original_pilot_code"] == "no"
    assert pilot.drop(first)["is_operational_briefing"].eq("no").all()
    assert table.loc[(table["decided_by"] == "pilot") & (table["is_operational_briefing"] == "yes"), "items"].sum() == 1


def test_recheck_wrong_row_count(files):
    pd.read_csv(files / "recheck_coded.csv", dtype=str).iloc[:-1].to_csv(files / "recheck_coded.csv", index=False)
    with pytest.raises(rm.MergeError, match="expected 6 pilot recheck rows, found 5"):
        run(files)


@pytest.mark.parametrize("value", ["P002", "P007"])
def test_recheck_review_id_duplicate_or_gap(files, value):
    recheck_edit(files, review_id={0: value})
    with pytest.raises(rm.MergeError, match="not P001 to P006"):
        run(files)


def test_recheck_url_differs_from_sheet(files):
    recheck_edit(files, url={2: "https://x.ng/other/"})
    with pytest.raises(rm.MergeError, match="urls differ from the sheet: P003"):
        run(files)


@pytest.mark.parametrize("value", ["unsure", ""])
def test_recheck_code_not_yes_or_no(files, value):
    recheck_edit(files, recheck_code={1: value})
    with pytest.raises(rm.MergeError, match="recheck_code not yes or no: P002"):
        run(files)


@pytest.mark.parametrize("row,value", [(0, "no"), (1, "yes")])
def test_recheck_changed_flag_wrong(files, row, value):
    recheck_edit(files, changed={row: value})
    with pytest.raises(rm.MergeError, match="changed does not match"):
        run(files)


def test_recheck_empty_notes(files):
    recheck_edit(files, notes={3: " "})
    with pytest.raises(rm.MergeError, match="empty notes: P004"):
        run(files)


def test_override_recodes_and_keeps_decided_by(files):
    url = f"https://x.ng/{YEARS[0]}/yes/"
    write_overrides(files, (url, "yes", "no", "Police statement, not DHQ"))
    _, classification, table, _ = run(files)
    row = classification.set_index("url").loc[url]
    assert row["is_operational_briefing"] == "no" and row["decided_by"] == "auto_yes" and row["overridden"] == "yes"
    assert classification["overridden"].eq("yes").sum() == 1
    assert table.loc[(table["decided_by"] == "auto_yes") & (table["is_operational_briefing"] == "no"), "items"].sum() == 1


def test_no_override_file_overrides_nothing(files):
    _, classification, _, _ = run(files)
    assert classification["overridden"].eq("no").all()


@pytest.mark.parametrize("row,message", [
    (("https://x.ng/none/", "yes", "no", "r"), "not classified"),
    ((f"https://x.ng/{YEARS[0]}/yes/", "no", "yes", "r"), "does not match"),
    ((f"https://x.ng/{YEARS[0]}/yes/", "yes", "maybe", "r"), "needs a to_code"),
    ((f"https://x.ng/{YEARS[0]}/yes/", "yes", "no", " "), "needs a to_code"),
])
def test_bad_override_stops_the_run(files, row, message):
    write_overrides(files, row)
    with pytest.raises(rm.MergeError, match=message):
        run(files)
