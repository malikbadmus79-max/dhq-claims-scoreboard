"""v1.1: the v1.0 figures with corrections found against DHQ's archived statements, and the audits rerun.

Usage: python -m scoreboard.audit_v1_1

Inputs, besides the v1.0 tables (which are only read):
- data/review/figures_corrections_v1.1.csv: corrections found against DHQ statements (archived copies,
  docs/sources.md). Same columns as data/review/figures_corrections.csv, but auto_value, auto_qualifier and
  auto_status hold the v1.0 final value, qualifier and final_status (data/briefings/briefing_figures_final.csv),
  since a v1.1 correction may change a hand row as well as an automatic one. check_corrections lists every
  failure: unknown or duplicate keys, auto_* differing from the v1.0 table, a corrected_status outside
  CORRECTED_STATUSES, a value given with any status but reported, an empty reason.
- data/review/pre2023_single_copy_flags.csv: reported national values dated before FLAG_BEFORE that rest
  on one independent copy (data/briefings/value_grades.csv); check_flags lists keys that are not such
  values in v1.1.
- data/dhq_site/dhq_comparison_v1.1.csv: briefings compared with a DHQ statement (verdict other than
  "no match"); each counts one DHQ copy (dhq_copies 1), so its period-end row is grade 1 (Deviations,
  2026-10-25: a "DHQ statement, archived copy" counts as DHQ's own text).

Writes data/briefings/briefing_figures_final_v1.1.csv (v1.0 rows, corrected rows with source
"correction v1.1" and the reason as notes) and data/briefings/check_briefings_v1.1.csv, runs
scoreboard.audit_v1 into outputs/audit_v1.1/, and writes the sensitivity run without the flagged values to
outputs/audit_v1.1/sensitivity/excluding_pre2023_flags.csv (status beside the v1.1 status).
"""

import argparse

import pandas as pd

from scoreboard import audit_v1
from scoreboard.audit_inputs import CHECK_BRIEFINGS, VALUE_GRADES
from scoreboard.checks import CHECK_COLUMNS, load_briefings
from scoreboard.config import PROJECT_ROOT
from scoreboard.extract import OUTCOMES
from scoreboard.final_figures import FINAL_FIGURES, POSITIVE_INT_RE
from scoreboard.triage_check import REVIEW_DIR

CORRECTIONS_V11 = REVIEW_DIR / "figures_corrections_v1.1.csv"
FLAGS = REVIEW_DIR / "pre2023_single_copy_flags.csv"
COMPARISON = PROJECT_ROOT / "data" / "dhq_site" / "dhq_comparison_v1.1.csv"
FINAL_V11 = FINAL_FIGURES.parent / "briefing_figures_final_v1.1.csv"
CHECK_V11 = CHECK_BRIEFINGS.parent / "check_briefings_v1.1.csv"
AUDIT_DIR_V11 = PROJECT_ROOT / "outputs" / "audit_v1.1"
SENSITIVITY = AUDIT_DIR_V11 / "sensitivity" / "excluding_pre2023_flags.csv"
SOURCE = "correction v1.1"
CORRECTED_STATUSES = ("reported", "vague", "not reported", "unresolved")
FLAG_BEFORE = "2023-07-01"
NO_MATCH = "no match"
KEY = ["briefing_id", "outcome"]


def _key(r) -> str:
    return f"{r.briefing_id} {r.outcome}"


def check_corrections(corrections: pd.DataFrame, final: pd.DataFrame) -> list[str]:
    failures = [f"{_key(r)}: duplicate key" for r in
                corrections[corrections.duplicated(KEY, keep=False)].drop_duplicates(KEY).itertuples()]
    v10 = final.set_index(KEY)
    for r in corrections.itertuples():
        if (r.briefing_id, r.outcome) not in v10.index:
            failures.append(f"{_key(r)}: not in {FINAL_FIGURES.name}")
            continue
        v = v10.loc[(r.briefing_id, r.outcome)]
        for col, v10_col in (("auto_value", "value"), ("auto_qualifier", "qualifier"), ("auto_status", "final_status")):
            if getattr(r, col) != v[v10_col]:
                failures.append(f"{_key(r)}: {col} {getattr(r, col)!r} but v1.0 {v10_col} is {v[v10_col]!r}")
        if r.corrected_status not in CORRECTED_STATUSES:
            failures.append(f"{_key(r)}: corrected_status {r.corrected_status!r} not allowed")
        if r.corrected_status == "reported" and not POSITIVE_INT_RE.fullmatch(r.corrected_value):
            failures.append(f"{_key(r)}: reported but corrected_value {r.corrected_value!r} is not a positive integer")
        if r.corrected_status != "reported" and r.corrected_value:
            failures.append(f"{_key(r)}: corrected_value given with status {r.corrected_status!r}")
        if not r.reason.strip():
            failures.append(f"{_key(r)}: empty reason")
    return failures


def apply_corrections(final: pd.DataFrame, corrections: pd.DataFrame) -> pd.DataFrame:
    out = final.copy().set_index(KEY)
    for r in corrections.itertuples():
        out.loc[(r.briefing_id, r.outcome), ["value", "qualifier", "final_status", "source", "notes"]] = \
            [r.corrected_value, r.corrected_qualifier, r.corrected_status, SOURCE, r.reason]
    return out.reset_index()[final.columns]


def check_flags(flags: pd.DataFrame, final: pd.DataFrame, grades: pd.DataFrame) -> list[str]:
    """Flagged keys that are not reported, single-copy values dated before FLAG_BEFORE in `final`."""
    t = final.merge(grades[[*KEY, "independent_copies_supporting"]], on=KEY, how="left").set_index(KEY)
    failures = []
    for r in flags.itertuples():
        if (r.briefing_id, r.outcome) not in t.index:
            failures.append(f"{_key(r)}: not in the final table")
            continue
        v = t.loc[(r.briefing_id, r.outcome)]
        if v["final_status"] != "reported" or v["value"] != r.value:
            failures.append(f"{_key(r)}: not reported with value {r.value!r}")
        elif str(v["independent_copies_supporting"]) != "1":
            failures.append(f"{_key(r)}: {v['independent_copies_supporting']} independent copies, not 1")
        elif v["briefing_date"] >= FLAG_BEFORE:
            failures.append(f"{_key(r)}: dated {v['briefing_date']}, not before {FLAG_BEFORE}")
    return failures


def check_table(v10_check: pd.DataFrame, final: pd.DataFrame, comparison: pd.DataFrame,
                exclude: pd.DataFrame | None = None) -> pd.DataFrame:
    """The v1.0 checks.py briefing table with the v1.1 values and DHQ copies; values in `exclude` blanked."""
    out = v10_check.copy().set_index("confirmed_group_id")
    values = final.set_index(KEY)
    for o in OUTCOMES:
        rows = values.xs(o, level="outcome").reindex(out.index)
        reported = rows["final_status"] == "reported"
        out[o] = rows["value"].where(reported, "")
        out[f"{o}_qualifier"] = rows["qualifier"]
        out[f"{o}_final_status"] = rows["final_status"]
        out[f"{o}_source"] = rows["source"]
        out[f"{o}_independent_copies_agreeing"] = out[f"{o}_independent_copies_agreeing"].where(reported, "0")
    compared = comparison.loc[comparison["verdict"] != NO_MATCH, "briefing_id"]
    out.loc[out.index.isin(compared), "dhq_copies"] = "1"
    for r in (exclude.itertuples() if exclude is not None else []):
        out.loc[r.briefing_id, [r.outcome, f"{r.outcome}_independent_copies_agreeing"]] = ["", "0"]
    return out.reset_index()


def sensitivity(results: pd.DataFrame, check_path, out_path) -> pd.DataFrame:
    """All checks on `check_path`, beside the v1.1 status of each row (matched by check, subject, outcome)."""
    rows = audit_v1.audit(load_briefings(check_path), audit_v1.pilot_within_rows(
        pd.read_csv(audit_v1.PILOT_CHECKS, keep_default_na=False, dtype=str),
        pd.read_csv(audit_v1.BRIEFINGS, keep_default_na=False, dtype=str))).astype(str)
    key = ["check", "subject", "outcome"]
    main = results[["check_id", *key, "status", "evidence_grade"]].rename(
        columns={"status": "v1_1_status", "evidence_grade": "v1_1_grade"})
    out = rows.drop(columns="check_id").merge(main, on=key, how="left")
    out["status_changed"] = out["status"] != out["v1_1_status"]
    out = out[["check_id", *key, "v1_1_status", "status", "status_changed", "v1_1_grade", "evidence_grade",
               *[c for c in CHECK_COLUMNS if c not in ("check_id", *key, "status", "evidence_grade")]]]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


def build():
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    final, corrections = read(FINAL_FIGURES), read(CORRECTIONS_V11)
    failures = check_corrections(corrections, final)
    final_v11 = apply_corrections(final, corrections) if not failures else None
    if final_v11 is not None:
        failures += [f"{FLAGS.name}: {f}" for f in check_flags(read(FLAGS), final_v11, read(VALUE_GRADES))]
    if failures:
        raise ValueError(f"{len(failures)} failures; nothing written:\n" + "\n".join(failures))
    final_v11.to_csv(FINAL_V11, index=False)
    comparison = read(COMPARISON)
    check_table(read(CHECK_BRIEFINGS), final_v11, comparison).to_csv(CHECK_V11, index=False)
    results = audit_v1.build(CHECK_V11, AUDIT_DIR_V11).astype(str)
    excluded = CHECK_V11.with_name("check_briefings_v1.1_excluding_flags.csv")
    check_table(read(CHECK_BRIEFINGS), final_v11, comparison, read(FLAGS)).to_csv(excluded, index=False)
    sens = sensitivity(results, excluded, SENSITIVITY)
    excluded.unlink()
    return final_v11, results, sens


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    final_v11, results, sens = build()
    print(f"{FINAL_V11.name}: {(final_v11['source'] == SOURCE).sum()} v1.1 corrections applied")
    print(pd.crosstab(results["check"], results["status"], margins=True).to_string())
    print(f"sensitivity without flagged values: {sens['status_changed'].sum()} rows change status")


if __name__ == "__main__":
    main()
