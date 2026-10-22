import pandas as pd
import pytest

import scoreboard.review_merge as rm

N = 6
YEARS = [str(y) for y in rm.YEARS]


@pytest.fixture
def files(tmp_path):
    """Six review items in two batches of three, the last one without text; per year one auto-yes, one
    auto-no and one "label" item outside triage. The review items all sit in the first year's triage."""
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
        inv = [{"url": r["url"], "outlet": "X"} for r in triage] + [{"url": f"https://x.ng/{y}/pilot/", "outlet": "X"}]
        pd.DataFrame(inv).to_csv(tmp_path / f"full_inventory_{y}.csv", index=False)
        labels.append({"url": f"https://x.ng/{y}/pilot/", "label_source": "pilot"})
    pd.DataFrame(labels).to_csv(tmp_path / "labels.csv", index=False)
    return tmp_path


def run(files):
    return rm.run(sheet_path=files / "sheet.csv", review_dir=files, tables_dir=files, labels_path=files / "labels.csv",
                  merged_path=files / "merged.csv", classification_path=files / "class.csv",
                  summary_path=files / "summary.csv", expected=N)


def edit(files, batch_file, **changes):
    """Rewrites one coded batch file; each change maps a column to {row position: value}."""
    path = rm.coded_path(files, batch_file)
    df = pd.read_csv(path, keep_default_na=False, dtype=str)
    for col, values in changes.items():
        for pos, value in values.items():
            df.loc[pos, col] = value
    df.to_csv(path, index=False)
    return df


def test_clean_merge_and_classification(files):
    merged, classification, table, unclassified = run(files)
    assert list(merged.columns) == rm.MERGED_COLUMNS and merged["review_id"].tolist() == [f"R{i:04d}" for i in range(1, N + 1)]
    assert classification["decided_by"].value_counts().to_dict() == {"auto_yes": 6, "auto_no": 6, "hand": N}
    assert table["items"].sum() == len(classification) == 2 * len(YEARS) + N
    assert unclassified["items"].sum() == len(YEARS)
    assert unclassified["reason"].eq("not triaged; labelled from pilot review").all()
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
