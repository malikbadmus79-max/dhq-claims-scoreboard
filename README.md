# The Scoreboard: Auditing Nigeria's Military Claims, 2021–2026

This project builds a structured dataset of operational claims made by Nigeria's Defence Headquarters (DHQ) in public briefings between 2021 and 2026. It audits those claims for arithmetic consistency, plausibility, language and the fidelity of their relay by news media.

## Data

- data/briefings/briefing_figures_final.csv: the per-briefing figures used by the audits, one row per briefing and outcome (neutralised, arrested, rescued), with the status and source of each value.
- data/briefings/full_briefings.csv: the confirmed briefings, one row per briefing.
- data/review/full_classification.csv: the classification of every discovered item.
- docs/data_dictionary.md: the columns, allowed values and sources of these files, and the review and validation files behind each value.
- docs/freeze_v1.0.md: the v1.0 freeze record, with row counts, SHA-256 checksums and the validation result.

Raw article text and HTML are not published.

## Findings

- National totals were rare before mid-2023: 7 of the 44 briefings of 2021 and 2022 gave any national figure, against 25 of 38 in 2023 and 55 of 57 in 2024.
- Some national figures in the news do not come from DHQ: for the briefing of 26 January 2023, Blueprint's 114 neutralised, 115 arrested and 101 rescued do not appear in DHQ's archived statement and were corrected to not reported in v1.1.
- The neutralised count became largely vague from 2025: 19 of 46 briefings in 2025 gave only a vague term for those neutralised, against 12 that gave a number.
- DHQ's 2024 neutralised total rose from 8,034 on 5 December to 10,937 on 31 December, which on grade 2 figures implies 1,483 per uncovered week, 5.19 times the largest weekly figure of 2024.
- Most totals cannot be tested: 207 of 332 audit checks (62%) are not testable, because weekly figures are missing, periods overlap or no shorter briefings fall inside a total's period.

Details, sources and limitations are in docs/findings_v1.md. The audits test whether DHQ's figures are consistent with each other, not whether they are true.
