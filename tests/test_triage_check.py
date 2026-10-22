import pandas as pd
import pytest

import scoreboard.triage_check as tc
from scoreboard.triage import Item


@pytest.fixture
def tables(tmp_path, monkeypatch):
    """Six years of inventory; items whose title holds 'weekly' get a briefing body, 'denial' a
    statement body, 'empty' no text. Only the two no-rules and title_period_number are accepted."""
    pd.DataFrame({"rule": ["title_period_number", "no_number_no_period", "briefing_format"],
                  "accepted": ["True", "True", "False"]}).to_csv(tmp_path / "triage_pilot_evaluation.csv", index=False)
    bodies = {"weekly": "Defence Headquarters said troops neutralised 40 terrorists in one week.",
              "denial": "The Defence Headquarters said troops did not attack the community.", "empty": ""}
    titles = {"weekly": "Troops neutralise 40 terrorists in one week", "denial": "Military denies attack", "empty": "x"}
    monkeypatch.setattr(tc, "load_item", lambda title, url: Item(title, bodies[url.split("/")[-2]]))
    for year in tc.YEARS:
        rows = [{"outlet": "X", "url": f"https://x.ng/{year}-{k}-{i}/{kind}/", "title": titles[kind],
                 "publish_date": f"{year}-05-01"}
                for kind in ("weekly", "denial") for i in range(40) for k in [kind]]
        rows.append({"outlet": "X", "url": f"https://x.ng/{year}-empty/empty/", "title": "x", "publish_date": f"{year}-05-01"})
        pd.DataFrame(rows).to_csv(tmp_path / f"full_inventory_{year}.csv", index=False)
    return tmp_path


def test_apply_uses_only_accepted_rules_and_skips_pilot_labels(tables):
    labels = tables / "labels.csv"
    pilot_url = "https://x.ng/2024-weekly-0/weekly/"
    pd.DataFrame([{"url": pilot_url, "label_source": "pilot"}]).to_csv(labels, index=False)
    counts = tc.apply_all(tables_dir=tables, labels_path=labels).set_index("year")
    assert counts.loc[2021, ["auto_yes", "auto_no", "uncertain", "no_text"]].tolist() == [40, 40, 0, 1]
    assert counts.loc[2024, "pilot_labelled"] == 1 and counts.loc[2024, "auto_yes"] == 39
    out = pd.read_csv(tables / "full_triage_2021.csv", keep_default_na=False)
    assert list(out.columns) == tc.TRIAGE_COLUMNS
    assert "briefing_format" not in " ".join(out["rules_fired"])


def test_sample_is_blind_balanced_seeded_and_excludes_2024(tables):
    tc.apply_all(tables_dir=tables, labels_path=tables / "none.csv")
    sheet, key = tables / "sheet.csv", tables / "key.csv"
    s1, k1 = tc.draw_sample(tables_dir=tables, sheet=sheet, key=key)
    assert list(s1.columns) == tc.SHEET_COLUMNS
    assert k1["decision"].value_counts().to_dict() == {"yes": 30, "no": 30}
    assert 2024 not in set(k1["year"]) and (k1["seed"] == tc.SEED).all()
    blind = sheet.read_text(encoding="utf-8")
    assert "title_period_number" not in blind and ",yes," not in blind and ",no," not in blind
    s2, _ = tc.draw_sample(tables_dir=tables, sheet=tables / "sheet2.csv", key=tables / "key2.csv")
    assert s1["url"].tolist() == s2["url"].tolist()  # same seed, same sample and order


def test_sample_refuses_to_overwrite_a_coded_sheet(tables):
    tc.apply_all(tables_dir=tables, labels_path=tables / "none.csv")
    sheet, key = tables / "sheet.csv", tables / "key.csv"
    s, _ = tc.draw_sample(tables_dir=tables, sheet=sheet, key=key)
    s.loc[0, "is_operational_briefing"] = "yes"
    s.to_csv(sheet, index=False)
    with pytest.raises(RuntimeError):
        tc.draw_sample(tables_dir=tables, sheet=sheet, key=key)


def test_score_counts_groups_and_names_rules(tmp_path):
    key = pd.DataFrame({"check_id": ["TC-001", "TC-002", "TC-003", "TC-004", "TC-005"],
                        "decision": ["yes", "yes", "no", "no", "no"],
                        "rules_fired": ["title_period_number", "title_period_number", "no_number_no_period",
                                        "no_national_no_period", "no_number_no_period; no_national_no_period"]})
    coded = pd.DataFrame({"check_id": ["TC-005", "TC-004", "TC-003", "TC-002", "TC-001"],
                          "is_operational_briefing": ["no", "yes", "yes", "unsure", "yes"], "notes": [""] * 5})
    key.to_csv(tmp_path / "key.csv", index=False)
    coded.to_csv(tmp_path / "coded.csv", index=False)
    result = tc.score(tc.compare(coded=tmp_path / "coded.csv", key=tmp_path / "key.csv")).set_index("group")
    assert result.loc["auto-yes", ["items", "agreements", "disagreements", "unsure", "result"]].tolist() == [2, 1, 0, 1, "pass"]
    assert result.loc["auto-no", ["items", "agreements", "disagreements", "result"]].tolist() == [3, 1, 2, "fail"]
    assert result.loc["auto-no", "rules_in_disagreements"] == "no_national_no_period; no_number_no_period"


def test_guard_moves_dhq_briefing_no_to_uncertain(tables, monkeypatch):
    bodies = {"weekly": "Defence Headquarters said troops neutralised 40 terrorists in one week.",
              "denial": "DHQ said in its latest update that troops did not attack the community.", "empty": ""}
    monkeypatch.setattr(tc, "load_item", lambda title, url: Item(title, bodies[url.split("/")[-2]]))
    counts = tc.apply_all(tables_dir=tables, labels_path=tables / "none.csv").set_index("year")
    assert counts.loc[2021, ["auto_yes", "auto_no", "uncertain", "guard_moved"]].tolist() == [40, 0, 40, 40]


def test_second_sample_is_auto_no_only_and_excludes_first(tables):
    tc.apply_all(tables_dir=tables, labels_path=tables / "none.csv")
    _, k1 = tc.draw_sample(tables_dir=tables, sheet=tables / "s1.csv", key=tables / "k1.csv")
    _, k2 = tc.draw_sample(tables_dir=tables, sheet=tables / "s2.csv", key=tables / "k2.csv", seed=tc.SEED2,
                           decisions=("no",), exclude=set(k1["url"]), prefix="TC2")
    assert len(k2) == 30 and set(k2["decision"]) == {"no"} and 2024 not in set(k2["year"])
    assert not k2["url"].isin(k1["url"]).any() and k2["check_id"].iloc[0] == "TC2-001"


def test_score_labels_a_single_group():
    merged = pd.DataFrame({"check_id": ["TC2-001", "TC2-002"], "decision": ["no", "no"],
                           "rules_fired": ["no_number_no_period"] * 2, "outcome": ["agree", "unsure"]})
    result = tc.score(merged, groups=(("no", "auto-no after guard"),))
    assert result["group"].tolist() == ["auto-no after guard"]
    assert result.loc[0, ["items", "agreements", "unsure", "result"]].tolist() == [2, 1, 1, "pass"]
