import json

import pandas as pd

from scoreboard.discover import (
    assign_groups,
    build_inventory,
    headline_figures,
    is_candidate,
    match_field,
    period_phrase,
    write_outputs,
)
from scoreboard.fetch import Response


def test_candidate_needs_dhq_and_outcome():
    assert is_candidate("DHQ: Troops neutralise 120 terrorists in one week")
    assert is_candidate("Buba: troops apprehend 30 suspects")
    assert is_candidate("Defence Media Operations: troops eliminate 12 bandits")
    assert not is_candidate("DHQ briefs journalists on welfare")
    assert not is_candidate("Troops kill 50 terrorists")


def test_title_lacks_dhq_but_excerpt_has_it():
    title = "Troops neutralise 120 terrorists in one week"
    excerpt = "The Defence Headquarters said on Thursday that troops recorded gains."
    assert not is_candidate(title)
    assert is_candidate(title, excerpt)
    assert match_field(title, excerpt) == "both"


def test_matched_field_values():
    assert match_field("DHQ: troops rescue 40 hostages", "Unrelated summary.") == "title"
    assert match_field("Weekly update", "Defence Headquarters said troops arrested 20.") == "excerpt"
    assert match_field("DHQ: troops rescue 40", "Buba said troops arrested 20.") == "both"
    assert match_field("Weekly update", "Nothing relevant.") is None


def test_period_phrase():
    assert period_phrase("DHQ: Troops killed 974 terrorists in February") == "in February"
    assert period_phrase("Troops neutralise 200 in two weeks") == "two weeks"
    assert period_phrase("Troops arrest 30") == ""


def test_headline_figures_skip_years_and_small_numbers():
    assert headline_figures("1,166 terrorists killed, 2,742 surrendered in 2024: 3 states") == {1166, 2742}


def test_groups_by_shared_figure_within_three_days():
    df = pd.DataFrame(
        {
            "publish_date": ["2024-03-01", "2024-03-03", "2024-03-20", "2024-03-02"],
            "title": [
                "DHQ: Troops kill 974 terrorists",
                "Troops neutralised 974 terrorists, DHQ says",
                "DHQ: Troops kill 974 terrorists",
                "DHQ: Troops arrest 55 suspects",
            ],
        }
    )
    groups = assign_groups(df)
    assert groups[0] == groups[1]
    assert groups[2] != groups[0]
    assert groups[3] not in (groups[0], groups[2])


class FakeFetcher:
    """Answers every outlet with one post whose title lacks DHQ but whose excerpt has it."""

    skip_reason = None
    EXCERPT = "<p>Defence Headquarters spokesman said the ZQXEXCERPTMARKER operations continued.</p>"

    def get(self, url, params=None):
        params = params or {}
        if params.get("per_page") == 1:
            return Response(url, 200, json.dumps([]))
        if params.get("search") != "DHQ":
            return Response(url, 200, json.dumps([]))
        domain = url.split("/")[2]
        post = {
            "date": "2024-05-02T10:00:00",
            "link": f"https://{domain}/troops-neutralise-150",
            "title": {"rendered": "Troops neutralise 150 terrorists in one week"},
            "excerpt": {"rendered": self.EXCERPT},
        }
        return Response(url, 200, json.dumps([post]), headers={"X-WP-TotalPages": "1"})


def test_excerpt_text_never_written(tmp_path):
    inventory, outlets = build_inventory(2024, fetcher=FakeFetcher())
    assert len(inventory) == len(outlets)
    assert set(inventory["matched_field"]) == {"both"}
    assert not inventory["kept_by_title_alone"].any()

    write_outputs(inventory, outlets, 2024, tables_dir=tmp_path)
    for csv in tmp_path.glob("*.csv"):
        text = csv.read_text(encoding="utf-8")
        assert "ZQXEXCERPTMARKER" not in text
        assert "spokesman said" not in text
        assert "excerpt" not in pd.read_csv(csv).columns


def test_buba_rule_in_candidate_filter():
    assert is_candidate("Troops neutralise 40 terrorists – Buba")
    assert is_candidate("Weekly update", "Maj.-Gen. Edward Buba said troops arrested 20 suspects.")
    assert not is_candidate("Agency arrests 14,480 suspects", "Chairman Buba Marwa said the arrests continued.")
    assert not is_candidate("Agency arrests 300", "BUBA-MARWA told journalists.")
