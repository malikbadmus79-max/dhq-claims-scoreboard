"""The v1.0 audits: every check in docs/audit_rules.md on the frozen v1.0 data.

Usage: python -m scoreboard.audit_v1

Reads data/briefings/check_briefings.csv (built by scoreboard.audit_inputs --step briefings) and runs
scoreboard.checks.run_checks with the v1.0 rules (Deviations, 2026-10-24 and 2026-10-25): short briefings
count as parts, missing weeks in the coverage variant are weeks whose Thursday no part's period covers
(missing_by "period"), and parts overlapping by more than OVERLAP_DAYS day make a row not testable.

The within-briefing check is limited to the 2024 pilot briefings with operation figures: its rows are
taken unchanged from outputs/tables/pilot_checks_2024.csv, with the pilot briefing IDs (B2024-035,
B2024-038) mapped to the v1.0 IDs through pilot_group_id in data/briefings/full_briefings.csv.

Writes outputs/audit_v1.0/results.csv (every check row, with status, evidence_grade and grade_label),
one CSV per check (<check>.csv) and week_coverage.csv (every Monday-to-Sunday week, 2021 to 2026).
"""

import argparse

import pandas as pd

from scoreboard.audit_inputs import CHECK_BRIEFINGS
from scoreboard.briefings import BRIEFINGS
from scoreboard.checks import CHECK_COLUMNS, load_briefings, run_checks, week_coverage
from scoreboard.config import PROJECT_ROOT
from scoreboard.discover import TABLES_DIR
from scoreboard.triage_check import YEARS

AUDIT_DIR = PROJECT_ROOT / "outputs" / "audit_v1.0"
PILOT_CHECKS = TABLES_DIR / "pilot_checks_2024.csv"
OVERLAP_DAYS = 1
WITHIN = "a. within_briefing"
GRADE3_LABEL = "grade 3, media-relay level"
RESULT_COLUMNS = [*CHECK_COLUMNS, "grade_label"]


def pilot_within_rows(pilot_checks: pd.DataFrame, briefings: pd.DataFrame) -> pd.DataFrame:
    """The pilot's within-briefing rows, with subjects in v1.0 IDs and the pilot check ID in the note."""
    to_v1 = dict(zip(briefings["pilot_group_id"], briefings["briefing_id"]))
    rows = pilot_checks[pilot_checks["check"] == WITHIN].copy()
    pilot_ids = rows["subject"].str.split().str[0]
    rows["subject"] = [f"{to_v1[p]} (pilot {s})" for p, s in zip(pilot_ids, rows["subject"])]
    rows["side_a"] = [a.replace(p, to_v1[p]) for p, a in zip(pilot_ids, rows["side_a"])]
    rows["note"] = [f"{n} Pilot result: {PILOT_CHECKS.name}, {cid}.".strip()
                    for n, cid in zip(rows["note"], rows["check_id"])]
    rows["reason"] = ""
    return rows


def audit(check_briefings: pd.DataFrame, pilot_rows: pd.DataFrame) -> pd.DataFrame:
    checks = run_checks(check_briefings, pd.DataFrame(), [], missing_by="period", overlap_days=OVERLAP_DAYS)
    results = pd.concat([pilot_rows.astype(object), checks], ignore_index=True)
    results["check_id"] = [f"A{n:03d}" for n in range(1, len(results) + 1)]
    results["evidence_grade"] = results["evidence_grade"].astype(int)
    results["grade_label"] = results["evidence_grade"].map(lambda g: GRADE3_LABEL if g == 3 else "")
    return results[RESULT_COLUMNS]


def build(check_path=CHECK_BRIEFINGS, out_dir=AUDIT_DIR):
    read = lambda p: pd.read_csv(p, keep_default_na=False, dtype=str)
    briefings = load_briefings(check_path)
    results = audit(briefings, pilot_within_rows(read(PILOT_CHECKS), read(BRIEFINGS)))
    out_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(out_dir / "results.csv", index=False)
    for check, rows in results.groupby("check", sort=False):
        rows.to_csv(out_dir / f"{check.split('. ', 1)[1]}.csv", index=False)
    pd.concat([week_coverage(briefings, y) for y in YEARS]).drop_duplicates("iso_week").to_csv(
        out_dir / "week_coverage.csv", index=False)
    return results


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    results = build()
    print(f"{len(results)} check rows written to {AUDIT_DIR}")
    print(pd.crosstab(results["check"], results["status"], margins=True).to_string())
    print(pd.crosstab(results["status"], results["evidence_grade"], margins=True).to_string())


if __name__ == "__main__":
    main()
