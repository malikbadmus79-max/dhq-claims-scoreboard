import re
from pathlib import Path

import pandas as pd
import pytest

from scoreboard.config import PROJECT_ROOT
from scoreboard.wirecheck import (
    SAME_WIRE_COMMENT,
    build_review,
    compare_groups,
    extract_body,
    has_nan_credit,
    independent_copies,
    similarity,
    suggested_type,
    write_outputs,
)

WIRE = (
    "The Defence Headquarters said troops of Operation Hadin Kai neutralised 120 terrorists and "
    "arrested 45 suspects in the North East during the week under review. The Director of Defence "
    "Media Operations told journalists in Abuja on Thursday that the troops also rescued 30 hostages "
    "and recovered 75 assorted weapons and 1,200 rounds of ammunition across several locations."
)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Troops neutralise 148 terrorists in one week – DHQ", "weekly"),
        ("DHQ: Troops kill 300 terrorists in the last two weeks", "fortnightly"),
        ("DHQ: Troops killed 974 terrorists, rescued 466 hostages in February", "monthly"),
        ("10,937 terrorists killed, 16,171 surrendered to troops in 2024: DHQ", "annual or year-end"),
        ("Sokoto villagers not killed by military strikes — DHQ", ""),
        ("DHQ: Troops arrest 30 in the last", ""),
    ],
)
def test_suggested_type(title, expected):
    assert suggested_type(title) == expected


def test_similarity_ignores_digits():
    other_figures = re.sub(r"\d", "7", WIRE)
    assert similarity(WIRE, other_figures) == 1.0


def test_similarity_unrelated_near_zero():
    unrelated = (
        "The state government announced a new school feeding programme for primary pupils, "
        "with officials saying the scheme would begin next term and cover every local council area."
    )
    assert similarity(WIRE, unrelated) < 0.05


def test_same_wire_reduces_independent_count():
    urls = ["a", "b", "c"]
    assert independent_copies(urls, []) == 3
    assert independent_copies(urls, [("a", "b")]) == 2
    assert independent_copies(urls, [("a", "b"), ("b", "c")]) == 1


def test_compare_groups_merges_wire_copies():
    inventory = pd.DataFrame(
        {
            "briefing_group_id": ["P2024-001"] * 3,
            "outlet": ["Gazette", "TheWill", "Blueprint"],
            "url": ["u1", "u2", "u3"],
        }
    )
    bodies = pd.Series({"u1": WIRE, "u2": re.sub(r"\d", "9", WIRE), "u3": "Entirely different wording " * 20})
    pairs, groups = compare_groups(inventory, bodies)
    assert pairs["same_wire"].sum() == 1
    assert groups.loc[0, "independent_copies"] == 2


def test_nan_credit():
    assert has_nan_credit("Abuja, Jan. 5, 2024 (NAN) The Defence Headquarters said")
    assert has_nan_credit("the News Agency of Nigeria reports")
    assert not has_nan_credit("the nan of the matter")


def test_extract_body_prefers_article_paragraphs():
    page = (
        "<html><body><nav><p>Home News Sport</p></nav>"
        f"<div class='entry-content'><p>{WIRE}</p><p>{WIRE}</p></div>"
        "<footer><p>Copyright notice</p></footer></body></html>"
    )
    body = extract_body(page)
    assert "Operation Hadin Kai" in body and "Copyright" not in body and "Home News" not in body


def test_written_files_hold_no_body_text(tmp_path):
    marker = "ZQXBODYMARKER sentence that must never leave data raw"
    inventory = pd.DataFrame(
        {
            "briefing_group_id": ["P2024-001", "P2024-001"],
            "outlet": ["Gazette", "TheWill"],
            "publish_date": ["2024-05-02", "2024-05-02"],
            "title": ["DHQ: Troops neutralise 150 in one week", "Troops neutralise 150 terrorists – DHQ"],
            "url": ["u1", "u2"],
            "matched_field": ["both", "both"],
        }
    )
    bodies = pd.Series({"u1": WIRE + " " + marker, "u2": WIRE})
    items = inventory[["url", "outlet", "briefing_group_id"]].copy()
    items["fetch_status"] = "ok"
    items["body_words"] = items["url"].map(lambda u: len(bodies[u].split()))
    items["nan_credit"] = items["url"].map(lambda u: has_nan_credit(bodies[u]))
    pairs, groups = compare_groups(inventory, bodies)
    review = build_review(inventory, items, groups, 2024)
    write_outputs(pairs, items, groups, review, 2024, tables_dir=tmp_path / "t", review_dir=tmp_path / "r")

    similarity_csv = (tmp_path / "t" / "pilot_copy_similarity_2024.csv").read_text(encoding="utf-8")
    assert similarity_csv.startswith(SAME_WIRE_COMMENT)
    for path in tmp_path.rglob("*.csv"):
        text = path.read_text(encoding="utf-8")
        assert "ZQXBODYMARKER" not in text
        assert "Operation Hadin Kai" not in text


def _published_files():
    for folder in ("outputs", "data"):
        for path in (PROJECT_ROOT / folder).rglob("*"):
            if path.is_file() and path.name != ".gitkeep":
                yield path


def test_no_body_text_in_outputs_or_data():
    """Any run of 20 consecutive words from a stored body must not appear in published files."""
    text_dir = PROJECT_ROOT / "data_raw" / "text"
    bodies = [p.read_text(encoding="utf-8") for p in text_dir.glob("*.txt")] if text_dir.exists() else []
    if not bodies:
        pytest.skip("no stored body text to check against")
    published = " ".join(" ".join(p.read_text(encoding="utf-8", errors="ignore").split()) for p in _published_files())
    for body in bodies:
        words = body.split()
        for start in range(0, max(len(words) - 20, 0), 20):
            window = " ".join(words[start : start + 20])
            assert window not in published, f"body text found in published files: {window[:80]}"


def test_domain_skipped_after_repeated_failures():
    from scoreboard.wirecheck import MAX_CONSECUTIVE_FAILURES, _fetch_domain

    class FailingFetcher:
        skip_reason = "request failed"

        def __init__(self):
            self.calls = 0

        def get(self, url, params=None):
            self.calls += 1
            return None

    fetcher = FailingFetcher()
    urls = [f"https://failing.example/zqx-test-{i}" for i in range(6)]
    rows = _fetch_domain(urls, fetcher)
    assert fetcher.calls == MAX_CONSECUTIVE_FAILURES
    assert [r["fetch_status"] for r in rows].count("skipped after repeated failures") == 6 - MAX_CONSECUTIVE_FAILURES


def test_threshold_from_config():
    from scoreboard.config import load_config
    from scoreboard.wirecheck import SAME_WIRE_THRESHOLD, SENSITIVITY_THRESHOLDS

    wire = load_config()["wire_copy"]
    assert SAME_WIRE_THRESHOLD == wire["same_wire_threshold"] == 0.3
    assert SENSITIVITY_THRESHOLDS == [0.45, 0.6]
    assert "0.3" in SAME_WIRE_COMMENT


def test_sensitivity_columns_count_independent_copies_per_threshold():
    from scoreboard.wirecheck import sensitivity_column

    inventory = pd.DataFrame({"briefing_group_id": ["G"] * 2, "outlet": ["A", "B"], "url": ["u1", "u2"]})
    words = WIRE.split()
    half = " ".join(words[: len(words) // 2]) + " " + "unrelated filler text about school feeding " * 6
    bodies = pd.Series({"u1": WIRE, "u2": half})
    sim = similarity(WIRE, half)
    pairs, groups = compare_groups(inventory, bodies, threshold=sim - 0.01, sensitivity=[sim + 0.01])
    assert groups.loc[0, "independent_copies"] == 1
    assert groups.loc[0, sensitivity_column(sim + 0.01)] == 2
    assert groups.loc[0, "max_similarity"] == round(sim, 3)


@pytest.mark.parametrize(
    "title,excerpt,expected",
    [
        ("NDLEA arrests 40 drug suspects in Kano", "", True),
        ("Police rescue 12 kidnap victims", "The command spokesman said officers arrested two.", True),
        ("Navy arrests 5 oil thieves", "Defence Headquarters said the operation continued.", False),
        ("NAF airstrikes neutralise terrorists", "Buba told journalists in Abuja.", False),
        ("Troops neutralise 120 terrorists – DHQ", "", False),
    ],
)
def test_likely_off_topic(title, excerpt, expected):
    from scoreboard.wirecheck import likely_off_topic

    assert likely_off_topic(title, excerpt) is expected


def test_review_keeps_hand_entries_and_sorts():
    inventory = pd.DataFrame(
        {
            "briefing_group_id": ["P2024-002", "P2024-001"],
            "outlet": ["Gazette", "TheWill"],
            "publish_date": ["2024-05-03", "2024-05-02"],
            "title": ["DHQ: Troops neutralise 150 in one week", "Troops neutralise 90 – DHQ"],
            "url": ["u1", "u2"],
            "matched_field": ["title", "title"],
        }
    )
    bodies = pd.Series({"u1": WIRE, "u2": WIRE})
    items = pd.DataFrame({"url": ["u1", "u2"], "nan_credit": [False, True]})
    _, groups = compare_groups(inventory, bodies)
    previous = pd.DataFrame({"url": ["u1"], "is_operational_briefing": ["yes"], "confirmed_group_id": ["B1"], "notes": [""]})
    review = build_review(inventory, items, groups, 2024, previous=previous)
    assert list(review["url"]) == ["u2", "u1"]
    assert review.set_index("url").loc["u1", "is_operational_briefing"] == "yes"
    assert review.set_index("url").loc["u2", "is_operational_briefing"] == ""


def test_buba_rule_in_off_topic():
    from scoreboard.wirecheck import likely_off_topic

    assert likely_off_topic("NDLEA arrests 300 suspects", "Chairman Buba Marwa said the agency continued raids.")
    assert not likely_off_topic("NAF airstrikes neutralise terrorists", "Maj.-Gen. Edward Buba said in Abuja.")


def test_nan_merge_counts_nan_copies_as_one():
    assert independent_copies(["a", "b", "c"], [], nan_credited=["a", "c"]) == 2
    assert independent_copies(["a", "b", "c"], [("a", "b")], nan_credited=["b", "c"]) == 1


def test_strict_column_merges_nan_credited_copies():
    inventory = pd.DataFrame(
        {"briefing_group_id": ["G"] * 3, "outlet": ["NAN", "Gazette", "TheWill"], "url": ["u1", "u2", "u3"]}
    )
    bodies = pd.Series(
        {
            "u1": "Abuja (NAN) " + "troops conducted operations across several states and recovered arms " * 4,
            "u2": "The News Agency of Nigeria reports " + "officials described clearance work in remote villages " * 4,
            "u3": "The spokesman described separate patrols along the border with new equipment " * 4,
        }
    )
    _, groups = compare_groups(inventory, bodies)
    assert groups.loc[0, "independent_copies"] == 3
    assert groups.loc[0, "independent_copies_strict"] == 2
