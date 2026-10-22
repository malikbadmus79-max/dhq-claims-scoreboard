"""Triage rules for is_operational_briefing, evaluated on the 2024 pilot labels.

Usage:
  python -m scoreboard.triage evaluate     # every rule on the pilot; writes triage_pilot_evaluation.csv
  python -m scoreboard.triage carry-over   # copies pilot labels to data/review/full_labels.csv

Each rule reads the title and the body text in data_raw/text/ and returns "yes", "no" or None (no
decision), with a reason. A rule is accepted only if it fires on at least MIN_FIRES pilot items with
precision of at least MIN_PRECISION. With the accepted rules, an item is decided when every
accepted rule that fires agrees; items with no firing rule, or with conflicting rules, are left for
hand review. The rules were set on the same 230 pilot items they are evaluated on (docs/triage_rules.md).
After the accepted rules, guard() sends a "no" back to hand review when the text names DHQ and has a
briefing or period phrase; it never produces "yes".

Pilot item IDs are P2024-r<row>, the 1-based row in data/review/pilot_review_2024.csv.
"""

import argparse
import re
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from scoreboard.config import PROJECT_ROOT
from scoreboard.discover import TABLES_DIR
from scoreboard.wirecheck import text_path

PILOT_REVIEW = PROJECT_ROOT / "data" / "review" / "pilot_review_2024.csv"
# Labels for full-collection items, one row per URL; carry-over fills it from the pilot.
FULL_LABELS = PROJECT_ROOT / "data" / "review" / "full_labels.csv"
LABEL_COLUMNS = ["year", "outlet", "url", "is_operational_briefing", "label_source", "pilot_item_id"]
EVALUATION_FILE = "triage_pilot_evaluation.csv"
MIN_FIRES = 20
MIN_PRECISION = 0.98

OUTCOME = r"(?:neutrali[sz]ed|neutrali[sz]e|killed|eliminated|arrested|apprehended|rescued|surrendered|recovered)"
NUMBER = r"\d[\d,]*"
DHQ_ATTRIBUTION = re.compile(r"\bDHQ\b|Defen[cs]e Headquarters|Defen[cs]e Media Operations|\bBuba\b(?![\s-]+Marwa)", re.I)
NATIONAL = re.compile(r"across the country|theatres? of operations?|across the nation|nationwide", re.I)
OUTCOME_NUMBER = re.compile(rf"\b{OUTCOME}\s+(?:a\s+total\s+of\s+|over\s+|about\s+|no\s+fewer\s+than\s+)?{NUMBER}"
                            rf"|{NUMBER}\s+(?:[A-Za-z/-]+\s+){{0,4}}(?:were\s+|have\s+been\s+)?{OUTCOME}", re.I)
BRIEFING = re.compile(r"while briefing|bi-?weekly|biweekly|Director,?\s+(?:of\s+)?Defen[cs]e Media Operations", re.I)
PERIOD = re.compile(r"\bin (?:one|a|two|three) weeks?\b|\bone week\b|\bin the past (?:one |two )?weeks?\b|"
                    r"\b(?:last|past) week\b|\bin (?:january|february|march|april|may|june|july|august|september|"
                    r"october|november|december)\b|\bin \d{4}\b|\bmonth\b|\bweekly\b", re.I)
# A reporting period as body text states it: "in the last one week", "between January 4 and 10".
BODY_PERIOD = re.compile(r"\b(?:in the (?:last|past) (?:one |two |three )?weeks?|within the week|in one week|in a week|"
                         r"(?:in|over|for) the (?:past|last) (?:one |two |\d+ )?(?:weeks?|days|months?)|"
                         r"between \w+ \d{1,2}(?:st|nd|rd|th)? and \w* ?\d{1,2}|from \w+ \d{1,2}(?:st|nd|rd|th)? to)", re.I)
OTHER_SOURCE = re.compile(r"\bPolice\b|\bNDLEA\b|\bEFCC\b|\bCustoms\b|\bNSCDC\b|\bImmigration\b|\bCommissioner\b", re.I)
NON_BRIEFING_TITLE = re.compile(r"\bdenies\b|\bdebunks?\b|\bwanted\b|\bcourt\b|\bvows?\b|\bassures?\b|\bcondemns?\b|"
                                r"\binquiry\b|\bcourt[- ]martial\b|\bwarns?\b|\bopinion\b|\beditorial\b|\btribute\b", re.I)
# Guard for auto-no, added after the triage check (docs/triage_rules.md, "Triage check").
GUARD_DHQ = re.compile(r"Defen[cs]e Media Operations|Defen[cs]e Headquarters|\bDHQ\b", re.I)
GUARD_PHRASE = re.compile(r"\bbriefing|\bbi-?weekly\b|\bweekly\b|\bupdates?\b|\b(?:news|press) conference|"
                          r"\bwithin the last\b|\bin the last\b|\bpast two weeks\b|"
                          r"\bbetween (?:\w+ )?\d{1,2}(?:st|nd|rd|th)? and (?:\w+ )?\d{1,2}", re.I)


@dataclass
class Item:
    title: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.title} {self.body}"


@dataclass
class Rule:
    name: str
    decision: str
    description: str
    test: Callable[[Item], bool]

    def apply(self, item: Item) -> tuple[str | None, str]:
        return (self.decision, self.description) if self.test(item) else (None, "")


RULES = [
    # yes: a DHQ results statement over a period or across theatres.
    Rule("title_period_number", "yes", "title states a period and an outcome number; text attributed to DHQ",
         lambda i: bool(PERIOD.search(i.title) and OUTCOME_NUMBER.search(i.title) and DHQ_ATTRIBUTION.search(i.text))),
    Rule("title_number_body_period", "yes", "outcome number in the title, a period stated in the body, DHQ named",
         lambda i: bool(OUTCOME_NUMBER.search(i.title) and BODY_PERIOD.search(i.text) and DHQ_ATTRIBUTION.search(i.text))),
    Rule("title_number_national", "yes", "outcome number in the title, a national marker, DHQ named",
         lambda i: bool(OUTCOME_NUMBER.search(i.title) and NATIONAL.search(i.text) and DHQ_ATTRIBUTION.search(i.text))),
    Rule("national_results", "yes", "DHQ named, a national marker and an outcome number anywhere",
         lambda i: bool(DHQ_ATTRIBUTION.search(i.text) and NATIONAL.search(i.text) and OUTCOME_NUMBER.search(i.text))),
    Rule("briefing_format", "yes", "briefing-format phrase and an outcome number anywhere",
         lambda i: bool(BRIEFING.search(i.text) and OUTCOME_NUMBER.search(i.text))),
    Rule("dhq_outcome_number", "yes", "DHQ named and an outcome number anywhere",
         lambda i: bool(DHQ_ATTRIBUTION.search(i.text) and OUTCOME_NUMBER.search(i.text))),
    # no: single incidents, other sources, statements without results.
    Rule("no_number_no_period", "no", "no outcome number and no stated period in title or body",
         lambda i: not OUTCOME_NUMBER.search(i.text) and not PERIOD.search(i.text) and not BODY_PERIOD.search(i.text)),
    Rule("no_national_no_period", "no", "no national marker, no stated period and no briefing phrase",
         lambda i: not NATIONAL.search(i.text) and not PERIOD.search(i.text) and not BRIEFING.search(i.text)),
    Rule("no_outcome_number", "no", "no outcome verb next to a number in title or body",
         lambda i: not OUTCOME_NUMBER.search(i.text)),
    Rule("non_briefing_title", "no", "title is a denial, warning, vow, court, inquiry, wanted list or opinion",
         lambda i: bool(NON_BRIEFING_TITLE.search(i.title))),
    Rule("other_agency_source", "no", "police or another agency named and DHQ not named",
         lambda i: bool(OTHER_SOURCE.search(i.text)) and not DHQ_ATTRIBUTION.search(i.text)),
]


def load_item(title: str, url: str) -> Item:
    path = text_path(url)
    return Item(title, path.read_text(encoding="utf-8") if path.exists() else "")


def pilot_items() -> pd.DataFrame:
    review = pd.read_csv(PILOT_REVIEW, keep_default_na=False, dtype=str)
    review.insert(0, "item_id", [f"P2024-r{i:03d}" for i in range(1, len(review) + 1)])
    return review


def evaluate(review: pd.DataFrame, rules=RULES) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per rule: items fired on, correct, precision, wrong item IDs, accepted. Also the per-item
    decisions of every rule."""
    items = [load_item(t, u) for t, u in zip(review["title"], review["url"])]
    decisions = pd.DataFrame({r.name: [r.apply(i)[0] for i in items] for r in rules}, index=review["item_id"])
    labels = review.set_index("item_id")["is_operational_briefing"]
    rows = []
    for r in rules:
        fired = decisions[r.name].notna()
        correct = decisions.loc[fired, r.name] == labels[fired]
        n = int(fired.sum())
        precision = correct.mean() if n else float("nan")
        rows.append({"rule": r.name, "decision": r.decision, "description": r.description, "fires": n,
                     "correct": int(correct.sum()), "precision": round(precision, 3) if n else "",
                     "accepted": n >= MIN_FIRES and precision >= MIN_PRECISION,
                     "wrong_item_ids": "; ".join(correct[~correct].index)})
    return pd.DataFrame(rows), decisions


def combine(decisions: pd.DataFrame, accepted: list[str]) -> pd.Series:
    """yes or no when every accepted rule that fires agrees; '' (hand review) otherwise."""
    def one(row):
        votes = {v for v in row[accepted] if isinstance(v, str)}
        return votes.pop() if len(votes) == 1 else ""
    return decisions.apply(one, axis=1) if accepted else pd.Series("", index=decisions.index)


def guard(item: Item, decision: str) -> str:
    """'' (hand review) for a "no" whose text names DHQ and has a briefing or period phrase."""
    if decision == "no" and GUARD_DHQ.search(item.text) and GUARD_PHRASE.search(item.text):
        return ""
    return decision


def carry_over(tables_dir=TABLES_DIR, labels_path=FULL_LABELS) -> pd.DataFrame:
    """Copies the pilot label to every full-collection item with the same URL, label_source
    "pilot", into data/review/full_labels.csv. Rows from any other source are kept."""
    review = pilot_items()[["item_id", "url", "is_operational_briefing"]].rename(columns={"item_id": "pilot_item_id"})
    rows = []
    for path in sorted(tables_dir.glob("full_inventory_*.csv")):
        inv = pd.read_csv(path, keep_default_na=False, dtype=str)
        rows.append(inv[["outlet", "url"]].assign(year=path.stem[-4:]))
    full = pd.concat(rows, ignore_index=True)
    out = full.merge(review, on="url", how="inner").assign(label_source="pilot")[LABEL_COLUMNS]
    if labels_path.exists():
        old = pd.read_csv(labels_path, keep_default_na=False, dtype=str)
        out = pd.concat([old[old["label_source"] != "pilot"], out], ignore_index=True)
    labels_path.parent.mkdir(parents=True, exist_ok=True)
    out.sort_values(["year", "url"])[LABEL_COLUMNS].to_csv(labels_path, index=False)
    return out[out["label_source"] == "pilot"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("evaluate")
    sub.add_parser("carry-over")
    args = parser.parse_args(argv)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 80)
    if args.cmd == "carry-over":
        out = carry_over()
        print(f"full-collection items with a pilot label: {len(out)}")
        print(out.groupby(["year", "is_operational_briefing"]).size().to_string())
        return
    review = pilot_items()
    table, decisions = evaluate(review)
    table.to_csv(TABLES_DIR / EVALUATION_FILE, index=False)
    print("RULE EVALUATION ON THE PILOT (230 items)")
    print(table.drop(columns=["description"]).to_string(index=False))
    accepted = list(table.loc[table["accepted"], "rule"])
    result = combine(decisions, accepted)
    labels = review.set_index("item_id")["is_operational_briefing"]
    print(f"\nACCEPTED RULES: {accepted}")
    print(f"auto yes: {int((result == 'yes').sum())}, auto no: {int((result == 'no').sum())}, "
          f"hand review: {int((result == '').sum())}")
    errors = result[(result != "") & (result != labels)]
    print(f"errors: {len(errors)}")
    for item_id, decided in errors.items():
        row = review.set_index("item_id").loc[item_id]
        print(f"  {item_id}: auto {decided}, label {row['is_operational_briefing']}: {row['title']}")


if __name__ == "__main__":
    main()
