# Data dictionary

This file describes the published data files of version 1.0 (docs/freeze_v1.0.md). All files are UTF-8 CSV with a header row. Blank cells are empty strings, not a missing-value code. Every value field is read as text; a number is a positive integer written without separators.

## data/briefings/briefing_figures_final.csv

One row per briefing and outcome: 220 briefings times 3 outcomes, 660 rows. Built by src/scoreboard/final_figures.py from data/briefings/briefing_figures.csv, data/review/figures_hand_coded.csv, data/review/figures_corrections.csv and data/briefings/full_briefings.csv. The key is briefing_id and outcome.

| Column | Type | Allowed values | Meaning | Source |
|---|---|---|---|---|
| briefing_id | text | B&lt;year&gt;-&lt;NNN&gt; | The confirmed briefing. Year is the year of the first publication date; numbers run from 001 within each year in order of first publication date. | data/briefings/full_briefings.csv |
| briefing_date | date | YYYY-MM-DD | The earliest publication date among the briefing's copies (first_date). | data/briefings/full_briefings.csv |
| period_class | text | weekly, biweekly, monthly, quarterly, year, cumulative; a list such as "weekly 5; biweekly 1"; or blank | The reporting period class shared by the copies that carry one. Where the copies carry more than one class, the cell holds period_classes instead: every class with its number of copies. Blank where no copy carries a class (4 briefings). | data/briefings/full_briefings.csv (period_class, else period_classes) |
| outcome | text | neutralised, arrested, rescued | The outcome counted. "Neutralised" is DHQ's term. | fixed |
| value | integer or blank | positive integer | The national figure for the outcome. Present only when final_status is reported. | see source |
| qualifier | text or blank | see Qualifiers below | The wording attached to the value, or the vague term used in place of one. | see source |
| final_status | text | reported, vague, not reported, unresolved | reported: a national figure is stated. vague: the copies make a national claim for the outcome with no number. not reported: no national figure; figures for one theatre, operation, incident or a named set of zones count as not reported. unresolved: two national values with equal support among independent copies; value blank. | see source |
| source | text | automatic, hand, correction | Which step set value, qualifier and final_status (see Sources below). | src/scoreboard/final_figures.py |
| auto_value | integer or blank | positive integer | The automatic value from data/briefings/briefing_figures.csv, kept for comparison. Blank when no copy has a national-marker value or when two values tie. | data/briefings/briefing_figures.csv (value) |
| auto_status | text | agreed, majority, conflict, needs hand extraction | The automatic status. agreed: all national-marker copies give one value. majority: one value has the most independent copies. conflict: values tie on independent copies. needs hand extraction: no copy has a national-marker value. | data/briefings/briefing_figures.csv (status) |
| notes | text or blank | free text | Blank for automatic rows; figure_notes for hand rows; reason for correction rows. At most one evidence sentence. | data/review/figures_hand_coded.csv, data/review/figures_corrections.csv |

### Sources

- automatic (265 rows): auto_status agreed and no correction. value and qualifier are the automatic values; final_status is reported.
- hand (357 rows): every row whose auto_status is majority, conflict or needs hand extraction. value, qualifier and final_status are confirmed_value, confirmed_qualifier and confirmed_status in data/review/figures_hand_coded.csv.
- correction (38 rows): agreed rows whose automatic value was found wrong in validation or the round 2 conflict review. value, qualifier and final_status are corrected_value, corrected_qualifier and corrected_status in data/review/figures_corrections.csv. Corrections are applied after the hand file.

### Qualifiers

- Precision wording on a reported value: "over", "more than", "no fewer than", "at least".
- "summed categories": the value is the sum of arrest categories listed in one sentence with no stated total.
- "plus N" (for example "plus 2"): a named or listed group arrested beside a count of others; the value is the count of others. The automatic rows write the same case as "plus N named".
- Vague terms, used only with final_status vague: "several", "scores", "dozens", "many", "thousands". A vague row may also have a blank qualifier when no term is used.

Hand-coding conventions are in docs/review_guide.md ("Hand extraction of briefing figures, 2026-10-24"); the extraction rules are in docs/audit_rules.md.

## data/briefings/full_briefings.csv

One row per confirmed briefing, 220 rows, built by src/scoreboard/briefings.py from the confirmed groups in data/review/group_review_coded.csv. Columns: briefing_id; year; first_date and last_date (earliest and latest publication date of the copies); period_class and period_classes (as above); items and outlets (numbers of copies and of outlets); outlet_list; items_auto_yes, items_hand and items_pilot (copies by decided_by); candidate_groups (the candidate groups merged into the briefing); pilot_group_id (the 2024 pilot ID, whose numbering differs); figure_flag (outcomes whose headline figures differ among the copies, with the values); merge_note (grouping notes other than a plain confirmation).

## data/review/full_classification.csv

One row per discovered item that was classified, 1,741 rows, built by src/scoreboard/review_merge.py. Columns: year, outlet, date (publication date), url; decided_by (auto_yes or auto_no from triage, hand from the hand review, pilot from the 2024 pilot); is_operational_briefing (yes, no, or unsure for items whose text could not be retrieved); review_id (hand review ID, or the pilot item ID); original_pilot_code (the pilot label before the recheck, pilot items only); overridden ("yes" where data/review/classification_overrides.csv changed the code). Inclusion rule: docs/review_guide.md.

## Review and validation files

These files document how each value in data/briefings/briefing_figures_final.csv was set or checked.

- data/briefings/briefing_figures.csv: the automatic values and statuses, with copy counts and other values.
- data/review/figures_hand_coded.csv: the hand extraction of the 357 non-agreed rows, with each copy's outlet, value, qualifier, rule and url, and figure_notes.
- data/review/figures_corrections.csv: the 38 corrections to agreed rows, with the automatic and corrected values and the reason.
- data/review/conflict_review_round2.csv: the 32 agreed values with a conflicting copy that names no region, the conflicting copies and the decision (9 corrected, 23 kept).
- data/validation/: the blind samples (blind_briefing_sheet.csv, round2_briefing_sheet.csv, blind_auto_no_sheet.csv), the coded samples (round1_ai_coded.xlsx, round1_author_chat_codes.csv, round2_ai_coded.csv, auto_no_ai_coded.csv) and the adjudications (round1_adjudication.csv, round2_adjudication.csv).

Changes to the method are recorded in docs/methods_changes.md and, for the audit rules, under Deviations in docs/audit_rules.md.
