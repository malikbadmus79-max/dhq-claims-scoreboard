from datetime import date

import pandas as pd
import pytest

from scoreboard.extract import (
    find_figure,
    majority,
    national_total,
    operation_figures,
    parse_period,
    period_note,
    split_sentences,
    spell_out_digits,
)

WEEKLY = (
    "The Defence Headquarters says troops of Operation Hadin Kai neutralised 12 terrorists in Borno. "
    "The Director, Defence Media Operations, Maj.-Gen. Edward Buba, said this on Thursday in Abuja. "
    "He said troops neutralised no fewer than 140 terrorists and arrested 210 others across the country in the last one week. "
    "Troops also rescued 96 kidnapped hostages."
)


@pytest.mark.parametrize(
    "sentence,outcome,value,qualifier",
    [
        ("Troops neutralised 43 terrorists and arrested 115 others.", "neutralised", 43, ""),
        ("Troops neutralised 43 terrorists and arrested 115 others.", "arrested", 115, ""),
        ("These actions resulted in 43 terrorists being neutralised and 115 arrested.", "neutralised", 43, ""),
        ("These actions resulted in 43 terrorists being neutralised and 115 arrested.", "arrested", 115, ""),
        ("No fewer than 86 terrorists had been eliminated and apprehended 101 others.", "neutralised", 86, "no fewer than"),
        ("Troops eliminated a total of 792 terrorists.", "neutralised", 792, ""),
        ("Troops killed over 1,166 terrorists in 29 days.", "neutralised", 1166, "over"),
        ("Troops apprehended103 others.", "arrested", 103, ""),
        ("Troops neutralised over 500 terrorists' leaders, 8,034 foot soldiers and arrested 11,623.", "neutralised", 8034, ""),
        ("Troops neutralized over 1,000 terrorist commanders and killed 10,937 fighters.", "neutralised", 10937, ""),
        ("Troops apprehended a terrorist commander, Musa Ali, and 182 others.", "arrested", 182, "plus 1 named"),
        ("Nine thousand three hundred three have been killed, 6,998 arrested.", "neutralised", 9303, ""),
        ("Nine thousand three hundred three have been killed, 6,998 arrested.", "arrested", 6998, ""),
        ("Troops eliminated 101 terrorists and apprehended several suspects.", "arrested", None, "several"),
        ("Troops rescued 21 kidnapped persons in 7 days.", "rescued", 21, ""),
    ],
)
def test_find_figure(sentence, outcome, value, qualifier):
    f = find_figure(sentence, outcome)
    assert f == {"value": value, "qualifier": qualifier}


@pytest.mark.parametrize(
    "sentence,outcome",
    [
        ("Troops recovered 391 weapons and 15,234 ammunitions.", "neutralised"),
        ("Terrorists killed 9 soldiers in an ambush.", "neutralised"),
        ("Troops neutralised over 65 notable terrorist leaders.", "neutralised"),
        ("The operation lasted 29 days before troops killed the leader.", "neutralised"),
    ],
)
def test_find_figure_skips_non_totals(sentence, outcome):
    f = find_figure(sentence, outcome)
    assert f is None or f["value"] is None


def test_split_sentences_keeps_titles_and_closing_quotes():
    text = "Maj.-Gen. Edward Buba spoke. He said, “Troops held.” Then troops moved."
    assert split_sentences(text) == ["Maj.-Gen. Edward Buba spoke.", "He said, “Troops held.”", "Then troops moved."]


def test_spell_out_digits_leaves_small_counts():
    assert spell_out_digits("Nine thousand three hundred three were killed in one week") == "9303 were killed in one week"
    assert spell_out_digits("nine soldiers") == "nine soldiers"


def test_national_total_prefers_national_marker_over_earlier_regional_sentence():
    f = national_total(WEEKLY, "neutralised")
    assert (f["value"], f["qualifier"], f["rule"]) == (140, "no fewer than", "national marker")
    assert f["evidence"].startswith("He said troops neutralised no fewer than 140")


def test_national_total_falls_back_to_first_sentence_without_region():
    f = national_total(WEEKLY, "rescued")
    assert (f["value"], f["rule"]) == (96, "no region named")


def test_national_total_skips_regional_sentences_without_marker():
    text = (
        "The DHQ briefed journalists in Abuja on Thursday. "
        "Troops of Operation Safe Haven arrested 30 suspects in Plateau. Troops also arrested 75 others."
    )
    f = national_total(text, "arrested")
    assert (f["value"], f["rule"]) == (75, "no region named")


def test_national_total_ignores_section_copy():
    text = (
        "The DHQ said troops of Operation Delta Safe destroyed 43 illegal refining sites. "
        "According to him, troops apprehended 32 suspected oil thieves."
    )
    assert national_total(text, "arrested") is None


def test_national_total_records_vague_only():
    text = "Troops neutralised several terrorists across the country in the last week."
    f = national_total(text, "neutralised")
    assert (f["value"], f["qualifier"], f["rule"]) == (None, "several", "vague only")


def test_evidence_truncated_to_300_characters():
    text = "Troops neutralised 43 terrorists across the country " + "and recovered items " * 40 + "."
    assert len(national_total(text, "neutralised")["evidence"]) == 300


def test_operation_figures_follow_section_until_next_operation_or_region():
    text = (
        "In the North East, troops of Operation Hadin Kai neutralised 292 terrorists and apprehended 254 suspects. "
        "Under Operation Whirl Stroke, troops neutralised 37 terrorists. "
        "He said the troops also arrested 94 suspects. "
        "In the South-South, troops of Operation Delta Safe destroyed 125 boats. "
        "He said the troops apprehended 71 persons involved in crude oil theft. "
        "In the North West, troops arrested 500 others."
    )
    ops = operation_figures(text)
    got = {op: {o: f["value"] for o, f in figs.items()} for op, figs in ops.items()}
    assert got == {
        "Hadin Kai": {"neutralised": 292, "arrested": 254},
        "Whirl Stroke": {"neutralised": 37, "arrested": 94},
        "Delta Safe": {"arrested": 71},
    }


def test_operation_name_does_not_capture_media_operations():
    text = "Director Defence Media Operations Major General Edward Buba said troops neutralised 40 terrorists."
    assert operation_figures(text) == {}


# Majority value and conflict flag


def test_majority_counts_independent_copies_not_raw_copies():
    values = {"a": 640, "b": 640, "c": 624, "d": 624}
    pairs = [("a", "b")]  # a and b are one wire copy
    m = majority(values, pairs, nan_urls=set())
    assert (m["value"], m["independent_copies_agreeing"], m["conflict"], m["tie"]) == (624, 2, True, False)


def test_majority_nan_merge_counts_credited_copies_once():
    values = {"a": 100, "b": 100, "c": 101}
    m = majority(values, [], nan_urls={"a", "b"})
    assert m["tie"] and m["value"] is None and m["conflict"]


def test_majority_ignores_copies_without_value_and_no_conflict_when_agreeing():
    m = majority({"a": 43, "b": 43, "c": None}, [], set())
    assert (m["value"], m["independent_copies_agreeing"], m["copies_reporting"], m["conflict"]) == (43, 2, 2, False)


def test_majority_with_no_values():
    m = majority({"a": None}, [], set())
    assert (m["value"], m["independent_copies_agreeing"], m["conflict"], m["tie"]) == (None, 0, False, False)


# Periods


def test_period_weekly_inferred():
    p = parse_period("weekly", date(2024, 1, 5))
    assert (p["period_start"], p["period_end"], p["stated_period_end"]) == (date(2023, 12, 30), date(2024, 1, 5), None)
    assert p["period_flag"].startswith("inferred")


@pytest.mark.parametrize(
    "note,start,end",
    [
        ("monthly: August", date(2024, 8, 1), date(2024, 8, 31)),
        ("quarterly: January to March", date(2024, 1, 1), date(2024, 3, 31)),
        ("quarterly: third quarter", date(2024, 7, 1), date(2024, 9, 30)),
        ("annual: 2024", date(2024, 1, 1), date(2024, 12, 31)),
    ],
)
def test_period_stated(note, start, end):
    p = parse_period(note, date(2024, 9, 26))
    assert (p["period_start"], p["period_end"], p["stated_period_end"]) == (start, end, end)
    assert p["period_flag"].startswith("stated")


def test_period_year_to_date_keeps_stated_end_from_notes():
    p = parse_period("year to date: 11 months", date(2024, 12, 5), 'Bodies say "from January to December".')
    assert (p["period_end"], p["stated_period_end"]) == (date(2024, 11, 30), date(2024, 12, 31))


def test_period_note_takes_most_common():
    notes = ["Period: weekly.", "Period: weekly. Headline differs.", "Period: monthly: May."]
    assert period_note(notes) == "weekly"
