# Triage check: coding instructions

Sheet: data/review/triage_check_sheet.csv (60 items, 2021–2023 and 2025–2026).

Code each item from the article itself: open the URL and read the published article. Apply the definition of is_operational_briefing in docs/review_guide.md unchanged: yes for a DHQ statement that reports troop results over a stated period; no for single-incident statements, denials and clarifications, and statements from other agencies; unsure when the article does not show whether the statement came from DHQ or covers a stated period, with a short note.

The sheet holds no automated decision, and none should be looked for: data/review/triage_check_key.csv and outputs/tables/full_triage_<year>.csv stay closed until every row is coded. Rows are in random order. Notes follow docs/review_guide.md: what the article states, in DHQ's terms, with at most one evidence sentence.

Sample. 30 items decided yes and 30 decided no by the accepted triage rules (docs/triage_rules.md), drawn from years other than 2024 with the fixed seed 20261022 (src/scoreboard/triage_check.py).

## Second sheet

Sheet: data/review/triage_check2_sheet.csv (30 items, IDs TC2-001 to TC2-030, 2021–2023 and 2025–2026). Key: data/review/triage_check2_key.csv. Hand codes: data/review/triage_check2_coded.csv.

Sample. 30 items decided no by the accepted rules after the auto-no guard (docs/triage_rules.md), drawn from years other than 2024 with the fixed seed 20261023, excluding the 60 items of the first sheet (src/scoreboard/triage_check.py, command sample2). Coding follows the instructions above; the key stays closed until every row is coded.
