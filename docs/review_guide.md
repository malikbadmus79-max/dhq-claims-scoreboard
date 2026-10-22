# Review guide: pilot_review_2024.csv

Coding the triage check sheet (data/review/triage_check_sheet.csv) follows docs/triage_check.md: code from the article itself, with the definitions below.

The three hand columns in data/review/pilot_review_2024.csv are coded from the article as published. The automated columns (suggested_type, suggested_group, likely_off_topic, independent_copies) are aids and do not decide a code.

## is_operational_briefing

- yes: a DHQ statement that reports troop results (neutralised, arrested, rescued, surrendered, recovered) over a stated period, such as one week, two weeks, a month or the year to date.
- no: incident statements about a single event, denials and clarifications, and statements from other agencies (NDLEA, EFCC, Police, Customs, NSCDC, Immigration, or Navy and Air Force statements not issued through DHQ).
- unsure: the article does not show whether the statement came from DHQ or whether it covers a stated period. A short note is required.

## confirmed_group_id

Items share a confirmed_group_id when they report the same briefing: the same briefing date and the same reporting period. Headline figures do not decide the group; copies of one briefing that lead with different figures belong together. Items coded no are left blank. IDs follow the form B2024-001, numbered in briefing date order.

## headline_body_check

Record "differs" when a headline figure differs from the figure in the same outlet's body, and give both figures in notes. These are media-relay observations, not DHQ inconsistencies. Left blank when headline and body agree.

## notes

A short note is required for every unsure code and for any item whose briefing date or period differs from its group. Notes record what the article states, in DHQ's terms ("neutralised" unless DHQ's own text says killed), and contain no quoted body text beyond one evidence sentence.
