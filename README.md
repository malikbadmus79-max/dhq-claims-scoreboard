# The Scoreboard: Auditing Nigeria's Military Claims, 2021–2026

This project builds a structured dataset of operational claims made by Nigeria's Defence Headquarters (DHQ) in public briefings between 2021 and 2026. It audits those claims for arithmetic consistency, plausibility, language and the fidelity of their relay by news media.

## Data

- data/briefings/briefing_figures_final.csv: the per-briefing figures used by the audits, one row per briefing and outcome (neutralised, arrested, rescued), with the status and source of each value.
- data/briefings/full_briefings.csv: the confirmed briefings, one row per briefing.
- data/review/full_classification.csv: the classification of every discovered item.
- docs/data_dictionary.md: the columns, allowed values and sources of these files, and the review and validation files behind each value.
- docs/freeze_v1.0.md: the v1.0 freeze record, with row counts, SHA-256 checksums and the validation result.

Raw article text and HTML are not published.
