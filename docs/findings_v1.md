# Findings, v1.1

This document reports what the Scoreboard found in Defence Headquarters (DHQ) claims of troops' operational results, 2021 to 2026. Each figure cites the table it comes from. The data are frozen at v1.0 (docs/freeze_v1.0.md), with four v1.1 corrections made against DHQ's own archived statements (data/review/figures_corrections_v1.1.csv). The audits test whether DHQ's figures are consistent with each other. They do not test whether the figures are true.

## Scope

- 220 DHQ briefings, January 2021 to October 2026, identified among 1,741 classified news items and reported in 1,057 article copies from 11 outlets (data/review/full_classification.csv, data/review/extraction_sheet_v3.csv, data/briefings/full_briefings.csv).
- Three outcomes per briefing: neutralised, arrested and rescued, giving 660 briefing-outcome values (data/briefings/briefing_figures_final_v1.1.csv).
- Validation: in a second independent sample of 33 briefings, the numeric values were correct on 96 of 99 fields (97.0%), against a target of 95% (data/validation/round2_adjudication.csv). The first round scored 90 of 96 (93.8%); the causes were corrected before round 2 (docs/methods_changes.md).

## 1. National totals were rare before mid-2023

Of the 660 values, 374 are national figures, 220 are not reported nationally, 53 are vague and 13 are unresolved (briefing_figures_final_v1.1.csv).

| Year | Briefings | Briefings with any national figure |
|---|---|---|
| 2021 | 18 | 3 |
| 2022 | 26 | 4 |
| 2023 | 38 | 25 |
| 2024 | 57 | 55 |
| 2025 | 46 | 35 |
| 2026 | 35 | 25 |

In 2021 and 2022, DHQ briefings reported figures theatre by theatre or operation by operation. DHQ's own archived statements confirm this: none of the 8 statements retrieved for July 2022 to January 2023 gives a national total; each reports figures zone by zone (data/dhq_site/dhq_comparison_v1.1.csv). From mid-2023, weekly statements carried a national summary.

## 2. Some national figures in the news do not come from DHQ

Some outlets printed national totals for briefings in which DHQ gave none. For the briefing of 26 January 2023 (B2023-002), Blueprint reported that "troops deployed to various parts of the country" neutralised 114, arrested 115 and rescued 101 (data/review/figures_hand_coded.csv, notes); none of these numbers appears in DHQ's statement (dhq_comparison_v1.1.csv). These values were corrected to not reported in v1.1. Ten other single-copy national values dated before July 2023 are flagged as unverified against DHQ's text (data/review/pre2023_single_copy_flags.csv).

## 3. The neutralised count largely disappeared in 2025

In 2025, 19 of 46 briefings gave only a vague term ("several", "scores", "dozens") for those neutralised, and 12 gave a number. In 2026, the figures are 14 vague and 12 numeric out of 35. Arrested and rescued figures were given as numbers more often: in 2025, 31 and 33 of 46 briefings; in 2026, 17 and 24 of 35 (briefing_figures_final_v1.1.csv).

## 4. DHQ's 2024 annual total rose by 2,903 in 26 days

On 5 December 2024, DHQ reported 8,034 terrorists neutralised in 2024 (B2024-053). On 31 December 2024, it reported 10,937 for the year (B2024-057). Both figures are evidence grade 2: the 5 December figure rests on 4 independent copies and the 31 December figure on 2 (data/briefings/value_grades.csv).

Using grade 2 figures only, the year-to-date total plus the weekly figures for December accounts for 8,394. The remaining 2,543 fall in 12 uncovered days, which implies 1,483 neutralised per week, 5.19 times the largest weekly figure DHQ reported in 2024 (286) (outputs/audit_v1.0/sensitivity/grade2_residual.csv, row A243). The arrested (12,538 against 12,399) and rescued (7,063 against 6,980) totals stay close to the same base and weekly figures, so the jump is specific to the neutralised count. The annual check itself marks all three rows not testable, because some December days are uncovered (outputs/audit_v1.0/annual.csv).

If the 5 December figure was meant as a full-year total, as some copies phrase it ("from January to December"), the two annual figures conflict outright.

## 5. Other arithmetic results

August 2024: DHQ's monthly total of 1,166 neutralised (announced 29 August) exceeds its three weekly figures for the month (426) by an amount that implies 576 per uncovered week, 2.01 times the largest weekly figure of 2024. The result holds on grade 2 figures (results.csv, row A195).

May 2024: DHQ's three weekly rescue figures for May (140, 253 and 206; 599 in all) exceed its monthly total of 563 (results.csv, row A052). One outlet describes the 253 as covering two weeks rather than one; if so, the gap disappears.

Two apparent gaps did not hold on review. February 2024 arrests mixed totals with and without oil-theft arrests, and July 2024 counted days from late June (outputs/audit_v1.0/audit_review_v1.0.csv).

## 6. Totals announced before their period ended

Of 33 monthly, quarterly and annual totals with a stated period, 9 were announced 1 to 5 days before that period ended, including the second and third quarters of 2024 (announced 27 June and 26 September) and the year 2023 (announced 29 December) (outputs/audit_v1.0/period_end.csv). Such figures cannot cover the last days of the period they name.

## 7. Most claims cannot be checked

Of 332 audit checks, 207 (62%) are not testable: a total has no matching weekly figures, weeks are missing, or briefing periods overlap (22 checks) (outputs/audit_v1.0/results.csv). Every quarterly total lacked at least one monthly figure, so none of the 24 quarter checks could run. Irregular schedules, missing weeks and overlapping periods leave most of DHQ's totals without a published basis against which to test them.

## 8. Outlets often report the same briefing differently

Independent copies of the same briefing gave different national values for 26 briefing-outcomes in the automatic extraction (12 conflict, 14 majority; data/briefings/briefing_figures.csv), and 13 values remain unresolved because two national figures have equal support. Examples:

- For B2024-008, DHQ's statement as quoted reads "arrested 264 of them including 104 perpetrators of oil theft"; the News Agency of Nigeria wire reported 368, counting the 104 twice.
- For B2024-014, the News Agency of Nigeria wire text, carried by three outlets, gives 121 neutralised and 253 arrested, while Leadership and the same three outlets' headlines give 212 and 252.

In validation round 1, 23 values had been recorded as national because the sentence said "theatres of operation", although it also named specific zones (data/review/figures_corrections.csv).

## Limitations

- Source. Almost all figures come from news reports. DHQ's own statements could be retrieved for 8 briefings only, through the Internet Archive, because the DHQ website did not respond (docs/source_access_log.csv).
- Consistency, not truth. The audits test whether DHQ's figures agree with each other. A consistently inflated or deflated series would pass.
- Evidence. In v1.0, 109 of 378 reported values rest on a single independent copy (grade 3) (data/briefings/value_grades.csv). Findings above rely on grade 2 figures unless stated.
- Coding. Hand coding and validation were AI-assisted; the author coded 6 validation briefings by hand. Disagreements were adjudicated against the article texts (docs/methods_changes.md).
- Development year. The audit rules were developed on 2024 data, so 2024 results are labelled "development year" in the outputs.
- Within-briefing check. Theatre figures were not extracted beyond two 2024 briefings, so whether theatre figures add up to national totals is not tested for the full period.
