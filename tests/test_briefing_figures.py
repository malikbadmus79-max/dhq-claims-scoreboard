import pandas as pd

import scoreboard.briefing_figures as bf

NM = bf.NATIONAL_RULE


def sheet(*rows):
    """Rows of (briefing_id, neutralised value, qualifier, rule); arrested and rescued are not reported."""
    out = []
    for i, (b, v, q, r) in enumerate(rows):
        row = {"briefing_id": b, "url": f"u{i}", "body_neutralised": v, "body_neutralised_qualifier": q,
               "body_neutralised_rule": r}
        for o in ("arrested", "rescued"):
            row |= {f"body_{o}": "", f"body_{o}_qualifier": "", f"body_{o}_rule": "not reported"}
        out.append(row)
    return pd.DataFrame(out)


def neutralised(table, briefing="B1"):
    return table.set_index(["briefing_id", "outcome"]).loc[(briefing, "neutralised")]


def test_agreed():
    r = neutralised(bf.briefing_figures(sheet(("B1", "43", "no fewer than", NM), ("B1", "43", "", NM))))
    assert (r["value"], r["copies_with_value"], r["copies_other"], r["status"]) == (43, 2, 0, "agreed")
    assert r["other_values"] == "" and r["qualifier"] == "no fewer than"
    r = neutralised(bf.briefing_figures(sheet(("B1", "43", "", NM), ("B1", "43", "over", NM), ("B1", "43", "over", NM))))
    assert r["qualifier"] == "over"


def test_majority_lists_other_values():
    r = neutralised(bf.briefing_figures(sheet(("B1", "43", "", NM), ("B1", "43", "", NM), ("B1", "1500", "", NM),
                                              ("B1", "40", "", NM), ("B1", "40", "", NM), ("B1", "43", "", NM))))
    assert (r["value"], r["copies_with_value"], r["copies_other"], r["status"]) == (43, 3, 3, "majority")
    assert r["other_values"] == "40 (2); 1,500 (1)"


def test_tie_is_a_conflict_with_no_value():
    r = neutralised(bf.briefing_figures(sheet(("B1", "43", "", NM), ("B1", "40", "", NM))))
    assert (r["value"], r["status"], r["copies_with_value"], r["copies_other"]) == ("", "conflict", 1, 1)
    assert r["other_values"] == "40 (1); 43 (1)"


def test_only_national_marker_values_count():
    t = bf.briefing_figures(sheet(("B1", "43", "", NM), ("B1", "99", "", "no region named"),
                                  ("B1", "", "scores", NM), ("B2", "12", "", "first mention")))
    r = neutralised(t)
    assert (r["value"], r["national_copies"], r["items"], r["status"]) == (43, 1, 3, "agreed")
    r2 = neutralised(t, "B2")
    assert (r2["value"], r2["national_copies"], r2["status"]) == ("", 0, "needs hand extraction")


def test_one_row_per_briefing_and_outcome(tmp_path):
    path = tmp_path / "sheet.csv"
    sheet(("B2", "5", "", NM), ("B1", "7", "", NM)).to_csv(path, index=False)
    table = bf.build(sheet_path=path, out_path=tmp_path / "out" / "figures.csv")
    assert list(table.columns) == bf.FIGURE_COLUMNS and len(table) == 6
    assert table["briefing_id"].tolist() == ["B1"] * 3 + ["B2"] * 3
    assert table.loc[table["outcome"] == "arrested", "status"].eq("needs hand extraction").all()
    assert (tmp_path / "out" / "figures.csv").exists()
