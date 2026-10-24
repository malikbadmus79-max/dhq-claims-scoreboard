"""Briefing figures from the national-marker body values of each briefing's copies.

Usage: python -m scoreboard.briefing_figures

Reads data/review/extraction_sheet_v3.csv and the stored body text in data_raw/text/ (no requests), and
writes data/briefings/briefing_figures.csv, one row per briefing and outcome. Only body values found by
the national-marker rule (body_<outcome>_rule "national marker", with a number) are used.

Independent copies follow the pilot (scoreboard.extract, docs/audit_rules.md): copies of one briefing
whose bodies reach the same_wire similarity threshold (SAME_WIRE_THRESHOLD, 0.3) count once, and so do
copies credited to the News Agency of Nigeria. The value and status come from scoreboard.extract.majority:
- value: the national-marker value given by most independent copies (then most copies, then the lower
  value), with qualifier the most common qualifier among the copies giving it (on a tie, that of the first
  such copy in sheet order); blank when two values tie on independent copies.
- copies_with_value, independent_copies_with_value: copies giving that value (in a tie, the first-ranked
  tied value). copies_other, independent_copies_other: copies giving any other national-marker value;
  other_values lists those values as "value (copies, independent)", in rank order.
- status: "agreed" when all national-marker copies give one value, "majority" when one value has the most
  independent copies, "conflict" when values tie on independent copies, "needs hand extraction" when no
  copy has a national-marker value.

Also writes data/review/figures_hand_sheet.csv, one row per briefing and outcome not "agreed", for hand
extraction: status, the briefing's period class (data/briefings/full_briefings.csv; period_classes when
its members carry more than one), and every copy in sheet order as parallel "; "-separated lists of
outlet, value, qualifier, rule and url. snippet_keys gives, per copy, the key ("url::outcome") of its
evidence sentence in the private snippets file (data_private/extraction_snippets_v3.csv), or "none".
confirmed_value, confirmed_qualifier, confirmed_status (reported, vague, not reported) and figure_notes
are left blank; the hand sheet is not overwritten once any of them is filled.
"""

import argparse

import pandas as pd

from scoreboard.briefings import BRIEFINGS
from scoreboard.extract import OUTCOMES, count_independent, majority, same_wire_pairs
from scoreboard.extraction_sheet import EXTRACTION_SHEET, SNIPPETS
from scoreboard.triage_check import REVIEW_DIR
from scoreboard.wirecheck import has_nan_credit, load_bodies

BRIEFING_FIGURES = BRIEFINGS.parent / "briefing_figures.csv"
NATIONAL_RULE = "national marker"
STATUSES = ("agreed", "majority", "conflict", "needs hand extraction")
HAND_SHEET = REVIEW_DIR / "figures_hand_sheet.csv"
HAND_COLUMNS = ["confirmed_value", "confirmed_qualifier", "confirmed_status", "figure_notes"]
CONFIRMED_STATUSES = ("reported", "vague", "not reported")
COPY_FIELDS = ["outlet", "value", "qualifier", "rule", "url"]
HAND_SHEET_COLUMNS = ["briefing_id", "outcome", "status", "period_class", "copies", "national_copies",
                      *[f"copy_{f}s" for f in COPY_FIELDS], "snippet_keys", *HAND_COLUMNS]
FIGURE_COLUMNS = ["briefing_id", "outcome", "value", "qualifier", "copies_with_value",
                  "independent_copies_with_value", "copies_other", "independent_copies_other", "other_values",
                  "national_copies", "items", "status"]


def ranked_values(values: dict[str, int], pairs, nan_urls: set[str]) -> list[tuple[int, list[str], int]]:
    """(value, urls, independent copies) per value, ranked as scoreboard.extract.majority ranks them."""
    by_value: dict[int, list[str]] = {}
    for url, v in values.items():
        by_value.setdefault(v, []).append(url)
    rows = [(v, urls, count_independent(urls, pairs, nan_urls)) for v, urls in by_value.items()]
    return sorted(rows, key=lambda r: (-r[2], -len(r[1]), r[0]))


def outcome_row(briefing_id: str, outcome: str, items: pd.DataFrame, pairs, nan_urls: set[str]) -> dict:
    national = items[(items[f"body_{outcome}_rule"] == NATIONAL_RULE) & (items[f"body_{outcome}"] != "")]
    values = dict(zip(national["url"], pd.to_numeric(national[f"body_{outcome}"]).astype(int)))
    row = {"briefing_id": briefing_id, "outcome": outcome, "value": "", "qualifier": "", "copies_with_value": 0,
           "independent_copies_with_value": 0, "copies_other": 0, "independent_copies_other": 0,
           "other_values": "", "national_copies": len(national), "items": len(items)}
    if not values:
        return {**row, "status": "needs hand extraction"}
    m = majority(values, pairs, nan_urls)
    ranked = ranked_values(values, pairs, nan_urls)
    (top_value, top_urls, top_independent), others = ranked[0], ranked[1:]
    other_urls = [u for _, urls, _ in others for u in urls]
    row |= {"copies_with_value": len(top_urls), "independent_copies_with_value": top_independent,
            "copies_other": len(other_urls),
            "independent_copies_other": count_independent(other_urls, pairs, nan_urls) if other_urls else 0,
            "other_values": "; ".join(f"{v:,} ({len(urls)}, {ind})" for v, urls, ind in others)}
    if m["tie"]:
        return {**row, "other_values": "; ".join(f"{v:,} ({len(urls)}, {ind})" for v, urls, ind in ranked),
                "status": "conflict"}
    quals = national.loc[national["url"].isin(top_urls), f"body_{outcome}_qualifier"]
    qualifier = max(dict.fromkeys(quals), key=lambda q: (quals == q).sum())
    return {**row, "value": int(m["value"]), "qualifier": qualifier,
            "status": "majority" if m["conflict"] else "agreed"}


def briefing_figures(sheet: pd.DataFrame, bodies: pd.Series) -> pd.DataFrame:
    rows = []
    for b, g in sheet.groupby("briefing_id", sort=True):
        urls = list(g["url"])
        pairs = same_wire_pairs(urls, bodies)
        nan_urls = {u for u in urls if has_nan_credit(bodies[u])}
        rows += [outcome_row(b, o, g, pairs, nan_urls) for o in OUTCOMES]
    return pd.DataFrame(rows, columns=FIGURE_COLUMNS)


def hand_sheet(figures: pd.DataFrame, sheet: pd.DataFrame, briefings: pd.DataFrame,
               snippet_keys: set[tuple[str, str]]) -> pd.DataFrame:
    period = briefings.set_index("briefing_id").apply(
        lambda b: b["period_class"] or b["period_classes"], axis=1)
    rows = []
    for f in figures[figures["status"] != "agreed"].itertuples():
        copies = sheet[sheet["briefing_id"] == f.briefing_id]
        o = f.outcome
        lists = {"outlet": copies["outlet"], "value": copies[f"body_{o}"], "qualifier": copies[f"body_{o}_qualifier"],
                 "rule": copies[f"body_{o}_rule"], "url": copies["url"]}
        rows.append({"briefing_id": f.briefing_id, "outcome": o, "status": f.status,
                     "period_class": period.get(f.briefing_id, ""), "copies": len(copies),
                     "national_copies": f.national_copies,
                     **{f"copy_{k}s": "; ".join(v.replace("", "-") if k != "url" else v) for k, v in lists.items()},
                     "snippet_keys": "; ".join(f"{u}::{o}" if (u, o) in snippet_keys else "none" for u in copies["url"]),
                     **{c: "" for c in HAND_COLUMNS}})
    return pd.DataFrame(rows, columns=HAND_SHEET_COLUMNS)


def build(sheet_path=EXTRACTION_SHEET, out_path=BRIEFING_FIGURES, load_bodies=load_bodies,
          briefings_path=BRIEFINGS, snippets_path=SNIPPETS, hand_path=HAND_SHEET) -> tuple[pd.DataFrame, pd.DataFrame]:
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    if hand_path.exists() and (read(hand_path)[HAND_COLUMNS] != "").any().any():
        raise RuntimeError(f"{hand_path} has hand entries in it; not overwritten")
    sheet = read(sheet_path).sort_values(["briefing_id", "date", "outlet", "url"], ignore_index=True)
    table = briefing_figures(sheet, load_bodies(sheet["url"]))
    snippets = read(snippets_path)
    hand = hand_sheet(table, sheet, read(briefings_path), set(zip(snippets["url"], snippets["outcome"])))
    for path, df in ((out_path, table), (hand_path, hand)):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return table, hand


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    table, hand = build()
    print(f"briefings: {table['briefing_id'].nunique()}; rows: {len(table)}; hand sheet rows: {len(hand)}")
    print(pd.crosstab(table["status"], table["outcome"], margins=True).reindex([*STATUSES, "All"]).fillna(0)
          .astype(int).to_string())


if __name__ == "__main__":
    main()
