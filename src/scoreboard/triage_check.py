"""Apply the frozen triage rules to the full collection and draw the triage check sample.

Usage:
  python -m scoreboard.triage_check apply
  python -m scoreboard.triage_check sample
  python -m scoreboard.triage_check sample2
  python -m scoreboard.triage_check score

`apply` uses the rules in scoreboard.triage that outputs/tables/triage_pilot_evaluation.csv marks
accepted (the frozen set; triage.py is not changed here). Every full-collection item without a
pilot label (data/review/full_labels.csv) gets a decision: "yes" or "no" when every accepted rule
that fires agrees, "uncertain" when none fires or they disagree, "no text" when data_raw/text holds
no body text. The auto-no guard (scoreboard.triage.guard) then turns "no" into "uncertain" where it
applies; column guard marks those items "moved". Writes outputs/tables/full_triage_<year>.csv.

`sample` draws SAMPLE_PER_DECISION auto-yes and SAMPLE_PER_DECISION auto-no items from years other
than EXCLUDED_YEAR with the fixed seed SEED, shuffles them, and writes the blind sheet
data/review/triage_check_sheet.csv (no decision or rule name) and the answer key
data/review/triage_check_key.csv. It refuses to overwrite a sheet in which coding has begun.

`sample2` draws SAMPLE_PER_DECISION auto-no items (after the guard) from the same years with seed
SEED2, excluding every URL in the first key, and writes data/review/triage_check2_sheet.csv and
data/review/triage_check2_key.csv in the same blind format, with check IDs TC2-001 to TC2-030.

`score` compares the hand codes (data/review/triage_check_coded.csv) with the key by check_id and
applies the pass rule: at most MAX_ERRORS disagreements in each decision group. "unsure" codes are
counted separately and are not errors. Writes outputs/tables/triage_check_result.csv.
"""

import argparse

import pandas as pd

from scoreboard.config import PROJECT_ROOT
from scoreboard.discover import TABLES_DIR
from scoreboard.triage import EVALUATION_FILE, FULL_LABELS, RULES, combine, guard, load_item

YEARS = range(2021, 2027)
SEED = 20261022
SEED2 = 20261023
SAMPLE_PER_DECISION = 30
EXCLUDED_YEAR = 2024
REVIEW_DIR = PROJECT_ROOT / "data" / "review"
SHEET = REVIEW_DIR / "triage_check_sheet.csv"
KEY = REVIEW_DIR / "triage_check_key.csv"
CODED = REVIEW_DIR / "triage_check_coded.csv"
SHEET2 = REVIEW_DIR / "triage_check2_sheet.csv"
KEY2 = REVIEW_DIR / "triage_check2_key.csv"
RESULT = "triage_check_result.csv"
MAX_ERRORS = 1
TRIAGE_COLUMNS = ["url", "outlet", "date", "decision", "rules_fired", "reason", "guard"]
SHEET_COLUMNS = ["check_id", "year", "outlet", "date", "title", "url", "is_operational_briefing", "notes"]
KEY_COLUMNS = ["check_id", "year", "url", "decision", "rules_fired", "seed"]


def accepted_rules(tables_dir=TABLES_DIR) -> list:
    table = pd.read_csv(tables_dir / EVALUATION_FILE, keep_default_na=False, dtype=str)
    names = set(table.loc[table["accepted"] == "True", "rule"])
    return [r for r in RULES if r.name in names]


def triage_year(inventory: pd.DataFrame, rules: list, pilot_urls: set) -> pd.DataFrame:
    rows = []
    for row in inventory.itertuples():
        if row.url in pilot_urls:
            continue
        item = load_item(row.title, row.url)
        base = {"url": row.url, "outlet": row.outlet, "date": row.publish_date}
        if not item.body:
            rows.append({**base, "decision": "no text", "rules_fired": "", "reason": "", "guard": ""})
            continue
        fired = [(r.name, *r.apply(item)) for r in rules]
        fired = [(name, dec, why) for name, dec, why in fired if dec]
        decision = combine(pd.DataFrame([{n: d for n, d, _ in fired}], columns=[r.name for r in rules]),
                           [r.name for r in rules]).iloc[0]
        guarded = guard(item, decision)
        rows.append({**base, "decision": guarded or "uncertain", "rules_fired": "; ".join(n for n, _, _ in fired),
                     "reason": "; ".join(w for _, _, w in fired), "guard": "moved" if guarded != decision else ""})
    return pd.DataFrame(rows, columns=TRIAGE_COLUMNS)


def pilot_labelled_urls(labels_path=FULL_LABELS) -> set:
    if not labels_path.exists():
        return set()
    labels = pd.read_csv(labels_path, keep_default_na=False, dtype=str)
    return set(labels.loc[labels["label_source"] == "pilot", "url"])


def apply_all(tables_dir=TABLES_DIR, labels_path=FULL_LABELS) -> pd.DataFrame:
    rules, pilot = accepted_rules(tables_dir), pilot_labelled_urls(labels_path)
    counts = []
    for year in YEARS:
        inv = pd.read_csv(tables_dir / f"full_inventory_{year}.csv", keep_default_na=False, dtype=str)
        out = triage_year(inv, rules, pilot)
        out.to_csv(tables_dir / f"full_triage_{year}.csv", index=False)
        c = out["decision"].value_counts()
        counts.append({"year": year, "items": len(inv), "pilot_labelled": int(inv["url"].isin(pilot).sum()),
                       "auto_yes": int(c.get("yes", 0)), "auto_no": int(c.get("no", 0)),
                       "uncertain": int(c.get("uncertain", 0)), "no_text": int(c.get("no text", 0)),
                       "guard_moved": int((out["guard"] == "moved").sum())})
    return pd.DataFrame(counts)


def draw_sample(tables_dir=TABLES_DIR, sheet=SHEET, key=KEY, seed=SEED, decisions=("yes", "no"),
                exclude=frozenset(), prefix="TC") -> tuple[pd.DataFrame, pd.DataFrame]:
    if sheet.exists():
        coded = pd.read_csv(sheet, keep_default_na=False, dtype=str)
        if (coded["is_operational_briefing"] != "").any() or (coded["notes"] != "").any():
            raise RuntimeError(f"{sheet} has coding in it; not overwritten")
    frames = []
    for year in YEARS:
        if year == EXCLUDED_YEAR:
            continue
        triage = pd.read_csv(tables_dir / f"full_triage_{year}.csv", keep_default_na=False, dtype=str)
        inv = pd.read_csv(tables_dir / f"full_inventory_{year}.csv", keep_default_na=False, dtype=str)
        frames.append(triage.merge(inv[["url", "title"]], on="url").assign(year=year))
    pool = pd.concat(frames, ignore_index=True)
    pool = pool[~pool["url"].isin(exclude)]
    picked = pd.concat([pool[pool["decision"] == d].sort_values("url").sample(SAMPLE_PER_DECISION, random_state=seed)
                        for d in decisions])
    picked = picked.sample(frac=1, random_state=seed).reset_index(drop=True)
    picked["check_id"] = [f"{prefix}-{i:03d}" for i in range(1, len(picked) + 1)]
    sheet_df = picked.assign(is_operational_briefing="", notes="")[SHEET_COLUMNS]
    key_df = picked.assign(seed=seed)[KEY_COLUMNS]
    sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet_df.to_csv(sheet, index=False)
    key_df.to_csv(key, index=False)
    return sheet_df, key_df


def compare(coded=CODED, key=KEY) -> pd.DataFrame:
    hand = pd.read_csv(coded, keep_default_na=False, dtype=str)
    answers = pd.read_csv(key, keep_default_na=False, dtype=str)
    merged = hand.merge(answers[["check_id", "decision", "rules_fired"]], on="check_id", validate="one_to_one")
    if len(merged) != len(answers):
        raise ValueError("coded sheet and key do not hold the same check_ids")
    code = merged["is_operational_briefing"]
    merged["outcome"] = "disagree"
    merged.loc[code == merged["decision"], "outcome"] = "agree"
    merged.loc[code == "unsure", "outcome"] = "unsure"
    merged.loc[code == "", "outcome"] = "uncoded"
    return merged


def score(merged: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for decision in ("yes", "no"):
        group = merged[merged["decision"] == decision]
        n = group["outcome"].value_counts()
        wrong = group[group["outcome"] == "disagree"]
        rules = sorted({r for fired in wrong["rules_fired"] for r in fired.split("; ") if r})
        rows.append({"group": f"auto-{decision}", "items": len(group), "agreements": int(n.get("agree", 0)),
                     "disagreements": int(n.get("disagree", 0)), "unsure": int(n.get("unsure", 0)),
                     "uncoded": int(n.get("uncoded", 0)), "max_errors": MAX_ERRORS,
                     "result": "pass" if len(wrong) <= MAX_ERRORS and not n.get("uncoded", 0) else "fail",
                     "rules_in_disagreements": "; ".join(rules),
                     "disagreement_ids": "; ".join(wrong["check_id"])})
    return pd.DataFrame(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apply")
    sub.add_parser("sample")
    sub.add_parser("sample2")
    sub.add_parser("score")
    args = parser.parse_args(argv)
    if args.cmd == "apply":
        print(f"accepted rules: {[r.name for r in accepted_rules()]}")
        print(apply_all().to_string(index=False))
    elif args.cmd == "score":
        merged = compare()
        result = score(merged)
        result.to_csv(TABLES_DIR / RESULT, index=False)
        print(result.to_string(index=False))
        cols = ["check_id", "title", "decision", "rules_fired", "is_operational_briefing", "notes"]
        for row in merged.loc[merged["outcome"] == "disagree", cols].itertuples(index=False):
            print("\n" + " | ".join(row))
    elif args.cmd == "sample2":
        first = set(pd.read_csv(KEY, keep_default_na=False, dtype=str)["url"])
        sheet, key = draw_sample(sheet=SHEET2, key=KEY2, seed=SEED2, decisions=("no",), exclude=first,
                                 prefix="TC2")
        print(f"seed: {SEED2}; {len(sheet)} items, {len(first)} first-check items excluded; by year:")
        print(key.groupby(["year", "decision"]).size().unstack(fill_value=0).to_string())
    else:
        sheet, key = draw_sample()
        print(f"seed: {SEED}; {len(sheet)} items; by year:")
        print(key.groupby(["year", "decision"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()
