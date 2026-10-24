import pandas as pd

import scoreboard.briefing_figures as bf

NM = bf.NATIONAL_RULE
WIRE = "The Defence Headquarters said troops across the country recorded results in the week under review."


def own(i):
    """A body that shares no wording with any other (similarity ignores digits, so letters differ)."""
    tag = "".join(chr(ord("a") + int(d)) for d in str(i))
    return " ".join(f"{tag}q{'z' * k}" for k in range(40))


def sheet(*rows):
    """Rows of (briefing_id, neutralised value, qualifier, rule, body); arrested and rescued not reported."""
    out, bodies = [], {}
    for i, (b, v, q, r, body) in enumerate(rows):
        url = f"u{i}"
        row = {"briefing_id": b, "url": url, "body_neutralised": v, "body_neutralised_qualifier": q,
               "body_neutralised_rule": r}
        for o in ("arrested", "rescued"):
            row |= {f"body_{o}": "", f"body_{o}_qualifier": "", f"body_{o}_rule": "not reported"}
        out.append(row)
        bodies[url] = own(i) if body is None else body
    return pd.DataFrame(out), pd.Series(bodies)


def neutralised(rows, briefing="B1"):
    table = bf.briefing_figures(*sheet(*rows))
    return table.set_index(["briefing_id", "outcome"]).loc[(briefing, "neutralised")]


def test_agreed():
    r = neutralised([("B1", "43", "no fewer than", NM, None), ("B1", "43", "", NM, None)])
    assert (r["value"], r["copies_with_value"], r["independent_copies_with_value"], r["status"]) == (43, 2, 2, "agreed")
    assert r["other_values"] == "" and r["qualifier"] == "no fewer than" and r["independent_copies_other"] == 0


def test_majority_on_independent_copies_lists_other_values():
    r = neutralised([("B1", "43", "", NM, None), ("B1", "43", "", NM, None), ("B1", "1500", "", NM, None),
                     ("B1", "40", "", NM, None)])
    assert (r["value"], r["copies_with_value"], r["independent_copies_with_value"]) == (43, 2, 2)
    assert (r["copies_other"], r["independent_copies_other"], r["status"]) == (2, 2, "majority")
    assert r["other_values"] == "40 (1, 1); 1,500 (1, 1)"


def test_same_wire_copies_count_once_and_can_turn_a_majority_into_a_conflict():
    """Two copies of one wire story give 43; one independent copy gives 40: 1 against 1 independent."""
    r = neutralised([("B1", "43", "", NM, WIRE), ("B1", "43", "", NM, WIRE), ("B1", "40", "", NM, None)])
    assert (r["value"], r["status"]) == ("", "conflict")
    assert (r["copies_with_value"], r["independent_copies_with_value"], r["copies_other"], r["independent_copies_other"]) \
        == (2, 1, 1, 1)
    assert r["other_values"] == "43 (2, 1); 40 (1, 1)"


def test_nan_credited_copies_count_once():
    nan_a, nan_b = own(7) + " (NAN)", own(8) + " News Agency of Nigeria"
    r = neutralised([("B1", "43", "", NM, nan_a), ("B1", "43", "", NM, nan_b), ("B1", "40", "", NM, None)])
    assert (r["independent_copies_with_value"], r["status"]) == (1, "conflict")


def test_independent_majority_wins():
    r = neutralised([("B1", "43", "", NM, None), ("B1", "43", "", NM, None), ("B1", "40", "", NM, WIRE),
                     ("B1", "40", "", NM, WIRE), ("B1", "40", "", NM, WIRE)])
    assert (r["value"], r["status"], r["independent_copies_with_value"], r["independent_copies_other"]) == \
        (43, "majority", 2, 1)


def test_only_national_marker_values_count():
    t = bf.briefing_figures(*sheet(("B1", "43", "", NM, None), ("B1", "99", "", "no region named", None),
                                   ("B1", "", "scores", NM, None), ("B2", "12", "", "first mention", None)))
    t = t.set_index(["briefing_id", "outcome"])
    r = t.loc[("B1", "neutralised")]
    assert (r["value"], r["national_copies"], r["items"], r["status"]) == (43, 1, 3, "agreed")
    r2 = t.loc[("B2", "neutralised")]
    assert (r2["value"], r2["national_copies"], r2["status"]) == ("", 0, "needs hand extraction")


def test_one_row_per_briefing_and_outcome(tmp_path):
    df, bodies = sheet(("B2", "5", "", NM, None), ("B1", "7", "", NM, None))
    path = tmp_path / "sheet.csv"
    df.to_csv(path, index=False)
    table = bf.build(sheet_path=path, out_path=tmp_path / "out" / "figures.csv", load_bodies=lambda urls: bodies)
    assert list(table.columns) == bf.FIGURE_COLUMNS and len(table) == 6
    assert table["briefing_id"].tolist() == ["B1"] * 3 + ["B2"] * 3
    assert table.loc[table["outcome"] == "arrested", "status"].eq("needs hand extraction").all()
    assert (tmp_path / "out" / "figures.csv").exists()
