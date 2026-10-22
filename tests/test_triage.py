import pandas as pd
import pytest

from scoreboard import triage
from scoreboard.triage import Item, Rule, combine, evaluate

WEEKLY = Item("Troops neutralise 120 terrorists, arrest 200 in one week - DHQ",
              "The Director, Defence Media Operations said troops across the country neutralised 120 terrorists "
              "in the last one week.")
DENIAL = Item("Military denies reprisal attack on community", "The Defence Headquarters said troops did not attack.")


def rule(name):
    return next(r for r in triage.RULES if r.name == name)


def test_accepted_yes_rules_fire_on_a_weekly_briefing():
    assert rule("title_period_number").apply(WEEKLY) == ("yes", rule("title_period_number").description)
    assert rule("title_number_body_period").apply(WEEKLY)[0] == "yes"
    assert rule("no_number_no_period").apply(WEEKLY)[0] is None


def test_no_rules_fire_on_a_statement_without_results():
    assert rule("no_number_no_period").apply(DENIAL)[0] == "no"
    assert rule("no_national_no_period").apply(DENIAL)[0] == "no"
    assert rule("title_period_number").apply(DENIAL)[0] is None


@pytest.mark.parametrize("text", ["neutralised 43 terrorists", "43 terrorists were neutralised", "arrested a total of 1,200"])
def test_outcome_number_in_either_order(text):
    assert triage.OUTCOME_NUMBER.search(text)


def test_buba_marwa_is_not_dhq_attribution():
    assert not triage.DHQ_ATTRIBUTION.search("Buba Marwa said the agency arrested 40")
    assert triage.DHQ_ATTRIBUTION.search("Maj.-Gen. Edward Buba said")


def test_evaluate_counts_precision_and_acceptance(monkeypatch):
    review = pd.DataFrame({"item_id": [f"P2024-r{i:03d}" for i in range(1, 26)],
                           "title": ["t"] * 25, "url": [f"u{i}" for i in range(25)],
                           "is_operational_briefing": ["yes"] * 24 + ["no"]})
    monkeypatch.setattr(triage, "load_item", lambda title, url: Item(title, url))
    always_yes = Rule("always_yes", "yes", "fires on all", lambda i: True)
    rare = Rule("rare", "no", "fires once", lambda i: i.body == "u24")
    table, decisions = evaluate(review, rules=[always_yes, rare])
    t = table.set_index("rule")
    assert (t.loc["always_yes", "fires"], t.loc["always_yes", "correct"]) == (25, 24)
    assert t.loc["always_yes", "wrong_item_ids"] == "P2024-r025" and not t.loc["always_yes", "accepted"]
    assert t.loc["rare", "precision"] == 1.0 and not t.loc["rare", "accepted"]  # fires on fewer than 20


def test_combine_decides_only_when_accepted_rules_agree():
    decisions = pd.DataFrame({"a": ["yes", "yes", None, None], "b": [None, "no", "no", None]}, index=list("wxyz"))
    assert combine(decisions, ["a", "b"]).tolist() == ["yes", "", "no", ""]
    assert combine(decisions, []).tolist() == ["", "", "", ""]


def test_carry_over_copies_pilot_labels_and_keeps_other_sources(tmp_path, monkeypatch):
    review = tmp_path / "pilot.csv"
    pd.DataFrame({"title": ["a", "b"], "url": ["u1", "u2"], "is_operational_briefing": ["yes", "no"]}).to_csv(review, index=False)
    monkeypatch.setattr(triage, "PILOT_REVIEW", review)
    pd.DataFrame({"outlet": ["X", "Y"], "url": ["u1", "u9"]}).to_csv(tmp_path / "full_inventory_2024.csv", index=False)
    labels = tmp_path / "labels.csv"
    pd.DataFrame([{"year": "2023", "outlet": "Z", "url": "u5", "is_operational_briefing": "no",
                   "label_source": "hand", "pilot_item_id": ""}]).to_csv(labels, index=False)
    out = triage.carry_over(tables_dir=tmp_path, labels_path=labels)
    assert out[["url", "is_operational_briefing", "pilot_item_id"]].values.tolist() == [["u1", "yes", "P2024-r001"]]
    saved = pd.read_csv(labels, dtype=str, keep_default_na=False)
    assert sorted(saved["label_source"]) == ["hand", "pilot"]


def test_guard_only_turns_no_into_hand_review():
    briefing = Item("Troops arrest 2 suspects", "Defence Media Operations said in its update between 6 and 20 October.")
    assert triage.guard(briefing, "no") == ""
    assert triage.guard(briefing, "yes") == "yes" and triage.guard(briefing, "") == ""
    assert triage.guard(Item("Troops arrest 2", "The Police said in a briefing."), "no") == "no"
    assert triage.guard(Item("DHQ: troops arrest 2", "DHQ said troops arrested two suspects."), "no") == "no"
