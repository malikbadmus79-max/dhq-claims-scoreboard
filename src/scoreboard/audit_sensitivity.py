"""Sensitivity runs for the v1.0 audits.

Usage: python -m scoreboard.audit_sensitivity

Both runs read data/briefings/check_briefings.csv, use the v1.0 rules of scoreboard.audit_v1 and write to
outputs/audit_v1.0/sensitivity/. Neither changes data/briefings/check_briefings.csv or the main results.

a. oil_theft_arrested.csv: arrested excluding oil-theft arrests. B2024-008 arrested is set to
   OIL_THEFT_VALUE (the 264 of briefing_figures_final.csv includes 104 oil-theft arrests; review row A045 in
   outputs/audit_v1.0/audit_review_v1.0.csv), and the month_weeks, coverage_variant and implied_residual
   checks are rerun for arrested. Each row gives the main-run status beside the sensitivity status.
b. grade2_residual.csv: implied_residual with grade 2 figures only. For each outcome, every briefing whose
   figure for that outcome is grade 3 (fewer than two independent copies) is left out, so its period
   counts as missing; totals, the year-to-date base and the largest weekly reference figure are grade 2.
"""

import argparse

import pandas as pd

from scoreboard.audit_inputs import CHECK_BRIEFINGS
from scoreboard.audit_v1 import AUDIT_DIR, OVERLAP_DAYS
from scoreboard.checks import (MIN_COPIES, coverage_variant_checks, load_briefings, month_week_checks,
                               residual_checks, with_effective_end)
from scoreboard.extract import OUTCOMES

SENSITIVITY_DIR = AUDIT_DIR / "sensitivity"
OIL_THEFT_BRIEFING = "B2024-008"
OIL_THEFT_VALUE = 160
KEY = ["check", "subject", "outcome"]
COMPARE_COLUMNS = [*KEY, "side_a_value", "side_b_value", "difference", "evidence_grade", "reason", "note"]


def _rows(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    # check_id is blank on fresh rows; the main run's ID is merged in by key.
    return df.drop(columns="check_id") if not df.empty else pd.DataFrame(columns=[*KEY, "status"])


def arrested_checks(briefings: pd.DataFrame) -> pd.DataFrame:
    effective = with_effective_end(briefings)
    rows = [*month_week_checks(effective, OVERLAP_DAYS),
            *coverage_variant_checks(effective, "period", OVERLAP_DAYS),
            *residual_checks(effective, OVERLAP_DAYS)]
    return _rows(rows).query("outcome == 'arrested'")


def oil_theft_run(briefings: pd.DataFrame, main: pd.DataFrame) -> pd.DataFrame:
    """The arrested rows of month_weeks, coverage_variant and implied_residual with B2024-008 arrested set
    to OIL_THEFT_VALUE, beside the main-run status and values."""
    changed = briefings.copy()
    changed.loc[changed["confirmed_group_id"] == OIL_THEFT_BRIEFING, "arrested"] = OIL_THEFT_VALUE
    rows = arrested_checks(changed)
    main = main[main["check"].isin(rows["check"].unique())][["check_id", *KEY, "status", "side_b_value"]]
    out = rows.merge(main.rename(columns={"status": "main_status", "side_b_value": "main_side_b_value"}),
                     on=KEY, how="left")
    out["status_changed"] = out["status"] != out["main_status"]
    return out[["check_id", *COMPARE_COLUMNS[:3], "main_status", "status", "status_changed", "main_side_b_value",
                *COMPARE_COLUMNS[3:]]]


def grade2_only(briefings: pd.DataFrame, outcome: str) -> pd.DataFrame:
    """The briefings whose `outcome` figure has two or more independent copies."""
    copies = pd.to_numeric(briefings[f"{outcome}_independent_copies_agreeing"], errors="coerce").fillna(0)
    return briefings[(copies >= MIN_COPIES) & briefings[outcome].notna()]


def grade2_residual_run(briefings: pd.DataFrame, main: pd.DataFrame) -> pd.DataFrame:
    effective = with_effective_end(briefings)
    rows = []
    for outcome in OUTCOMES:
        rows += [r for r in residual_checks(grade2_only(effective, outcome), OVERLAP_DAYS) if r["outcome"] == outcome]
    out = _rows(rows)
    main = main[main["check"] == "b. implied_residual"][["check_id", *KEY, "status", "residual_ratio"]]
    out = out.merge(main.rename(columns={"status": "main_status", "residual_ratio": "main_residual_ratio"}),
                    on=KEY, how="left")
    return out[["check_id", *KEY, "main_status", "status", "side_a_value", "side_b_value", "missing_parts",
                "implied_per_missing_week", "largest_weekly_figure", "residual_ratio", "main_residual_ratio",
                "evidence_grade", "reason", "note"]]


def build(check_path=CHECK_BRIEFINGS, results_path=AUDIT_DIR / "results.csv", out_dir=SENSITIVITY_DIR):
    briefings = load_briefings(check_path)
    main = pd.read_csv(results_path, keep_default_na=False, dtype=str)
    oil, g2 = oil_theft_run(briefings, main), grade2_residual_run(briefings, main)
    out_dir.mkdir(parents=True, exist_ok=True)
    oil.to_csv(out_dir / "oil_theft_arrested.csv", index=False)
    g2.to_csv(out_dir / "grade2_residual.csv", index=False)
    return oil, g2


def main(argv=None):
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    oil, g2 = build()
    print(f"a. oil theft: {len(oil)} arrested rows, {oil['status_changed'].sum()} change status")
    print(f"b. grade 2 residual: {len(g2)} rows; {(g2['status'] == 'implausible residual').sum()} implausible")


if __name__ == "__main__":
    main()
