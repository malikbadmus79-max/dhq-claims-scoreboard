# Review guide: pilot_review_2024.csv

Coding the triage check sheet (data/review/triage_check_sheet.csv) follows docs/triage_check.md: code from the article itself, with the definitions below.

The three hand columns in data/review/pilot_review_2024.csv are coded from the article as published. The automated columns (suggested_type, suggested_group, likely_off_topic, independent_copies) are aids and do not decide a code.

## is_operational_briefing

- yes: a DHQ statement that reports troop results (neutralised, arrested, rescued, surrendered, recovered) over a stated period, such as one week, two weeks, a month or the year to date.
- no: incident statements about a single event, denials and clarifications, and statements from other agencies (NDLEA, EFCC, Police, Customs, NSCDC, Immigration, or Navy and Air Force statements not issued through DHQ).
- unsure: the article does not show whether the statement came from DHQ or whether it covers a stated period. A short note is required.
- In data/review/full_review_sheet.csv, items with has_text False are coded "unsure" with the note "no text".

## Coding conventions (full review)

1. A report of a periodic DHQ briefing is coded yes when it carries any troop result from that briefing, even if it leads with a single incident or covers only one region or operation.
2. A report of a briefing that carries only remarks (assurances, explanations, apologies) and no troop results is coded no.
3. Cumulative figures (since an operation began, or "so far") are coded yes with a note saying the figure is cumulative; extraction must not treat them as figures for a single week or month.

These conventions were recorded on 2026-10-22 after batch B01 and apply to all batches and to the blind validation.

### Further conventions, 2026-10-24

4. A report of a briefing that gives only the armed forces' own casualties is coded no, unless it also carries troop results for a reporting period.
5. A statement on a single operation or single campaign is coded no, even when it states dates (for example, the Timbuktu Triangle operation of January 2025 and the joint Nigeria-United States air strikes of May 2026).
6. Figures given at joint security briefings (the Strategic Communications Interagency Policy Committee briefing of June 2024; the Joint Security News Briefing of September 2026) are coded yes, with a note that the event was not a Defence Media Operations briefing.
7. Editorials, headline roundups, analysis features and reports of third-party reactions are coded no.
8. A periodic statement that reports results without figures for a stated period is coded yes, with a note that it gives no figures.

Borderline items for the validation coder to check:

- R0747: rebuttal statement quoting cumulative figures, coded no.
- R0835: milestone statement quoting cumulative figures, coded yes.

## confirmed_group_id

Items share a confirmed_group_id when they report the same briefing: the same briefing date and the same reporting period. Headline figures do not decide the group; copies of one briefing that lead with different figures belong together. Items coded no are left blank. IDs follow the form B2024-001, numbered in briefing date order.

### Grouping conventions, 2026-10-24

- An outlet's misstated period (for example, a cumulative figure headlined as two weeks) does not move its item out of the briefing it reports. Such cases are recorded in group_notes and checked in the headline-body review.
- Cumulative or annual claims made on the same day as period results form their own group.

## headline_body_check

Record "differs" when a headline figure differs from the figure in the same outlet's body, and give both figures in notes. These are media-relay observations, not DHQ inconsistencies. Left blank when headline and body agree.

### "rounded", 2026-10-24

Record "rounded" when the headline gives a rounded or qualified figure (for example, "over 150" or "1,000") and the outlet's body gives the exact figure it rounds (171 or 1,051). It is recorded separately from "differs".

### "not stated", 2026-10-24

Record "not stated" when the headline figure appears nowhere in the outlet's body. This includes a headline figure that is the outlet's own sum of figures given separately in the body (for example, theatre figures added together), since the body does not state that total. It is recorded separately from "differs", which applies where the body states a different figure for the same total.

## notes

A short note is required for every unsure code and for any item whose briefing date or period differs from its group. Notes record what the article states, in DHQ's terms ("neutralised" unless DHQ's own text says killed), and contain no quoted body text beyond one evidence sentence.

## Hand extraction of briefing figures, 2026-10-24

These conventions apply to data/review/figures_hand_coded.csv, which covers every briefing and outcome whose automatic status in data/briefings/briefing_figures.csv is conflict, majority or needs hand extraction.

- Only national figures are recorded. A figure is national when a copy attributes it to operations across the country, to all theatres, or to a national summary that names no region, zone or operation. Figures for one theatre, one operation, one incident or a named set of zones are recorded as not reported, with the figures in figure_notes. "Theatres of operation" followed or preceded by named zones (for example "the North-West and North-Central theatres") is not national.
- Arrests reported in a separate sentence, usually oil-theft arrests, are not added to the headline arrest figure; the sum is given in figure_notes.
- When a copy lists arrest categories in one sentence with no stated total, the value is their sum and the qualifier is "summed categories".
- When independent copies differ, the value carried by more independent copies is kept.
- A stated total resolves a conflict when it equals the sum of categories listed in one sentence of another copy.
- vague: the copies make a national claim for the outcome with no number. The qualifier records the term used, or is blank when none is used.
- unresolved: two national values with equal support among independent copies. The value is left blank, and checks that depend on it are not testable.
- A qualifier is recorded only when every independent copy carrying the value uses it.
- Counts of named commanders or kingpins are not totals.
- Persons arrested in a named or listed group beside a count of "others" follow the named-plus-others rule, with the qualifier "plus N".
