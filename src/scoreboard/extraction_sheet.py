"""Extraction and headline-body sheet for every item in a confirmed briefing.

Usage: python -m scoreboard.extraction_sheet

Reads data/review/group_review_coded.csv and the stored body text in data_raw/text/ (no requests) and
writes data/review/extraction_sheet.csv, one row per item ordered by briefing_id, date, outlet and url,
with automatic proposals for hand confirmation, and data_private/extraction_snippets.csv, which holds the
evidence sentences and is not committed (.gitignore). The field definitions are the pilot's
(docs/audit_rules.md, Extraction rules), applied with the pilot code itself:
- headline_<outcome>: scoreboard.relay.headline_figures on the title.
- body_<outcome>: scoreboard.extract.national_total on the body (first sentence with a national marker,
  else the first naming no region, state or operation, else a vague-only sentence); failing all three,
  the first sentence in the body with a figure for the outcome, region or not ("first mention").
  body_<outcome>_rule records which.
- Values are counts; qualifiers ("over", "no fewer than", "plus 1 named") are kept in
  <field>_qualifier, and a vague term ("scores", "several") is a qualifier with no value.
- snippets: the sentence each body figure came from, one per value, cut to EVIDENCE_CHARS characters,
  in data_private/extraction_snippets.csv (briefing_id, url, outcome, snippet; url and outcome are the
  key). The public sheet holds only snippet_ref, the outcomes of that row with a snippet.
- proposed_headline_body_check: "differs" when a headline figure is absent from the body or differs
  from the body figure for the same outcome, unless the headline only rounds it ("over 40" for 43,
  scoreboard.relay.is_rounded); blank otherwise. proposed_reason gives the figures behind each proposal,
  including rounded cases.
confirmed_headline_body_check and extraction_notes are left blank for hand confirmation. It refuses to
overwrite a sheet in which those columns have been filled. Pilot extraction files are only read.
"""

import argparse

import pandas as pd

from scoreboard.briefings import GROUP_CODED
from scoreboard.config import PROJECT_ROOT
from scoreboard.extract import EVIDENCE_CHARS, OUTCOMES, find_figure, national_total, split_sentences
from scoreboard.relay import headline_figures, is_rounded, numbers_in
from scoreboard.triage_check import REVIEW_DIR
from scoreboard.wirecheck import text_path

EXTRACTION_SHEET = REVIEW_DIR / "extraction_sheet.csv"
SNIPPETS = PROJECT_ROOT / "data_private" / "extraction_snippets.csv"
SNIPPET_COLUMNS = ["briefing_id", "url", "outcome", "snippet"]
FIGURE_COLUMNS = [c for o in OUTCOMES for c in (f"headline_{o}", f"headline_{o}_qualifier", f"body_{o}",
                                                 f"body_{o}_qualifier", f"body_{o}_rule")]
SHEET_COLUMNS = ["briefing_id", "review_id", "decided_by", "outlet", "date", "title", "url", "text_path",
                 *FIGURE_COLUMNS, "snippet_ref", "proposed_headline_body_check", "proposed_reason",
                 "confirmed_headline_body_check", "extraction_notes"]
HAND_COLUMNS = ("confirmed_headline_body_check", "extraction_notes")


def first_mention(text: str, outcome: str) -> dict | None:
    """The first sentence with a numeric figure for the outcome, else the first with a vague one."""
    vague = None
    for s in split_sentences(text):
        f = find_figure(s, outcome)
        if f is None:
            continue
        if f["value"] is not None:
            return {**f, "rule": "first mention", "evidence": s[:EVIDENCE_CHARS]}
        vague = vague or {**f, "rule": "first mention, vague only", "evidence": s[:EVIDENCE_CHARS]}
    return vague


def body_figure(text: str, outcome: str) -> dict:
    if not text:
        return {"value": None, "qualifier": "", "rule": "no text", "evidence": ""}
    f = national_total(text, outcome) or first_mention(text, outcome)
    return f or {"value": None, "qualifier": "", "rule": "not reported", "evidence": ""}


def proposal(title: str, text: str, body: dict[str, dict]) -> tuple[str, str]:
    """The proposed headline-body check and the figures behind it."""
    if not text:
        return "", ""
    present = numbers_in(text)
    reasons, differs = [], False
    for outcome, h in headline_figures(title).items():
        b = body[outcome]["value"]
        q = f" ({h['qualifier']})" if h["qualifier"] else ""
        if h["value"] not in present:
            reason = f"{outcome}: headline {h['value']:,}{q} not in body"
        elif b is not None and b != h["value"]:
            reason = f"{outcome}: headline {h['value']:,}{q} vs body {b:,}"
        else:
            continue
        if is_rounded(h["value"], h["qualifier"], b):
            reason += ", rounded"
        else:
            differs = True
        reasons.append(reason)
    return ("differs" if differs else ""), "; ".join(reasons)


def sheet_row(item: dict, text: str) -> tuple[dict, list[dict]]:
    """The public sheet row and the private snippet rows, one per outcome with an evidence sentence."""
    row = {c: item.get(c, "") for c in ("review_id", "decided_by", "outlet", "date", "title", "url")}
    row["briefing_id"] = item["confirmed_group_id"]
    headline = headline_figures(item["title"])
    body = {o: body_figure(text, o) for o in OUTCOMES}
    for o in OUTCOMES:
        h = headline.get(o, {"value": None, "qualifier": ""})
        row[f"headline_{o}"], row[f"headline_{o}_qualifier"] = h["value"], h["qualifier"]
        row[f"body_{o}"], row[f"body_{o}_qualifier"] = body[o]["value"], body[o]["qualifier"]
        row[f"body_{o}_rule"] = body[o]["rule"]
    snippets = [{"briefing_id": row["briefing_id"], "url": row["url"], "outcome": o, "snippet": body[o]["evidence"]}
                for o in OUTCOMES if body[o]["evidence"]]
    row["snippet_ref"] = "; ".join(s["outcome"] for s in snippets)
    row["proposed_headline_body_check"], row["proposed_reason"] = proposal(item["title"], text, body)
    return row, snippets


def build_sheet(items: pd.DataFrame, text_path=text_path) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, snippets = [], []
    for item in items.to_dict("records"):
        path = text_path(item["url"])
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        row, found = sheet_row(item, text)
        rows.append({**row, "text_path": str(path) if text else ""})
        snippets += found
    sheet = pd.DataFrame(rows).assign(**{c: "" for c in HAND_COLUMNS})
    for o in OUTCOMES:
        for c in (f"headline_{o}", f"body_{o}"):
            sheet[c] = sheet[c].astype("Int64")
    sheet = sheet.sort_values(["briefing_id", "date", "outlet", "url"], ignore_index=True)[SHEET_COLUMNS]
    order = {u: i for i, u in enumerate(sheet["url"])}
    snippets = pd.DataFrame(snippets, columns=SNIPPET_COLUMNS)
    snippets = snippets.sort_values(["url", "outcome"], key=lambda c: c.map(order) if c.name == "url" else
                                    c.map(OUTCOMES.index), ignore_index=True)
    return sheet, snippets


def build(coded_path=GROUP_CODED, sheet_path=EXTRACTION_SHEET, snippets_path=SNIPPETS,
          text_path=text_path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sheet_path.exists():
        old = pd.read_csv(sheet_path, keep_default_na=False, dtype=str)
        if any((old[c] != "").any() for c in HAND_COLUMNS):
            raise RuntimeError(f"{sheet_path} has hand entries in it; not overwritten")
    sheet, snippets = build_sheet(pd.read_csv(coded_path, keep_default_na=False, dtype=str), text_path)
    for path, df in ((sheet_path, sheet), (snippets_path, snippets)):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return sheet, snippets


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    sheet, snippets = build()
    print(f"items: {len(sheet)}; snippets: {len(snippets)}; text missing: {int((sheet['text_path'] == '').sum())}; "
          f"proposed differs: {int((sheet['proposed_headline_body_check'] == 'differs').sum())}")
    for o in OUTCOMES:
        print(o, sheet[f"body_{o}_rule"].value_counts().to_dict())
    none = sheet[[f"body_{o}" for o in OUTCOMES]].isna().all(axis=1)
    print(f"items with no numeric body figure for any outcome: {int(none.sum())}")


if __name__ == "__main__":
    main()
