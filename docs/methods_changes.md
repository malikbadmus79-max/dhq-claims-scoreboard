# Methods changes

Changes to collection methods after the pilot closed, in date order. Audit rules (docs/audit_rules.md) are not changed by any entry here.

## 2026-10-19: a complete yield row is never replaced by an incomplete rerun

Change. In src/scoreboard/collect.py a newer outlet-year result replaces the saved one only if it is complete, or if the saved one was also incomplete. An incomplete rerun of a complete outlet-year writes nothing to the inventory or yield tables; an access-log row "incomplete rerun not saved" records it. Reruns name their outlets (`--outlets`), so outlets not named are not requested again.

Reason. 21st Century Chronicle 2024 was completed by the full run of 2026-10-19: 756 unique posts, all four queries ending at the last page, 0 incomplete (docs/source_access_log.csv, row of 2026-10-19 for "Full discovery 2024 (first pass)" with stops {'invalid page number': 4}; earlier rows dated 2026-10-18 are incomplete attempts). A later rerun of all 2024 outlets, run to complete Leadership 2024, failed on this site (request failures and HTTP 500) and replaced the row with an incomplete one; a single retry with a 30-second delay also ended incomplete (rows of 2026-10-19 marked "retry started", "time budget exceeded" and "still incomplete"). The counts did not change: 756 posts and 46 candidates in every case. The row in outputs/tables/full_yield_by_outlet_year.csv is restored to complete with those counts (access-log row "complete row restored").

## 2026-10-19: spokesperson coverage check, 2021–2026

Nature. A coverage check, not a change of discovery: the full-collection search terms and candidate filter remain the four pilot terms and DHQ_RE in src/scoreboard/discover.py. Code: src/scoreboard/spokesperson.py.

Names. The check uses the 2021–2023 names, other than Buba, found next to "Director, Defence Media Operations", "Defence Media Operations", "Defence spokesperson" or "DHQ spokesperson" in the full inventory titles and excerpts, spelled as found there; no outside list of names was used (outputs/tables/full_spokesperson_names.csv). The spellings are John Enenche, Bernard Onyeuko, Benard Onyeuko, Bernard Onyeuku, Benard Onyeuku and Musa Danmadami.

Method. Each name was searched per year, 2021–2026, on every outlet with a REST API, through the polite fetcher (outputs/tables/full_spokesperson_dry_search.csv: one row per name, year and outlet). Links not already in that year's inventory were tested against the candidate filter twice: as it stands (column new_current_filter) and with the names counted as DHQ references, as "Buba" is (column new_with_name_terms).

Result. Under the current filter the check found 0 new candidates. With the names as DHQ references it found 11 distinct links, all in 2021–2023 (5 in 2021, 4 in 2022, 2 in 2023), against 725 existing candidates for those years. These 11 were added from the cached search pages, without new requests, to outputs/tables/full_inventory_2021.csv, full_inventory_2022.csv and full_inventory_2023.csv, flagged added_by "spokesperson_check"; every other row is added_by "discovery". Yield counts (outputs/tables/full_yield_by_outlet_year.csv) count discovery rows only and are unchanged.

Limits. Names are matched as full names: a report naming only a surname (for example "Enenche said") is not matched unless it also names DHQ or its media office. Spellings not found in the inventory text are not searched. 11 of the 396 searches ended incomplete (column complete), all on 21st Century Chronicle, so the check is a lower bound for that outlet. Added rows passed the filter only; they have not been reviewed by hand.

## 2026-10-24: hand coding of the uncertain triage items

Change. The 1,005 items the triage left undecided (decision "uncertain" or "no text"; data/review/full_review_sheet.csv, batches B01 to B17) were hand-coded with AI assistance under the conventions in docs/review_guide.md. src/scoreboard/review_merge.py checks and merges the batches into data/review/full_review_coded.csv and joins them with the triage auto-yes and auto-no items in data/review/full_classification.csv; counts are in outputs/tables/full_classification_summary.csv.

Validation. A blind human validation sample of 15 percent, including auto-no items, follows.

Pilot items. The 230 items of the 2024 pilot are included in data/review/full_classification.csv with decided_by "pilot". They were rechecked by hand against conventions 1 to 8 in docs/review_guide.md (data/review/pilot_recheck_sheet.csv, coded in data/review/pilot_recheck_coded.csv), and the recheck code is the one used. 17 of 230 codes changed, all from no to yes: mostly reports of periodic briefings that led with a single incident, arrest or remark (convention 1), plus four where the body carried weekly or biweekly figures (P141, P143, P154, P187). The original pilot labels are kept unchanged in data/review/pilot_review_2024.csv and data/review/full_labels.csv, and in the column original_pilot_code.

Override. One auto-yes item, a police statement, was recoded to no at grouping (Daily Post, 2021-01-01, "Katsina Police rescued 393 kidnap victims, neutralized 29 bandits in 2020 – CP Buba"). The change is recorded in data/review/classification_overrides.csv and applied by src/scoreboard/review_merge.py, which keeps decided_by "auto_yes" and marks the row overridden "yes" in data/review/full_classification.csv.

## 2026-10-24: hand extraction of briefing figures

Change. The 357 briefing-outcome rows whose automatic status in data/briefings/briefing_figures.csv is not agreed were extracted by hand in data/review/figures_hand_coded.csv: 331 needing hand extraction, 14 majority and 12 conflict. Majority and conflict are counted on independent copies (same_wire threshold 0.3, with News Agency of Nigeria copies counted once).

Result. Of the 357 rows, 107 are reported with a value, 195 not reported, 49 vague and 6 unresolved (confirmed_status in data/review/figures_hand_coded.csv). src/scoreboard/final_figures.py combines them with the 303 automatic agreed rows in data/briefings/briefing_figures_final.csv, keeping the automatic value and status beside each hand value.

Conventions. docs/review_guide.md, "Hand extraction of briefing figures, 2026-10-24". The replacement of automatic values is logged under Deviations in docs/audit_rules.md.

## 2026-10-24: blind validation sample

Blind validation sample. The validation sample under Validation in docs/audit_rules.md was drawn by src/scoreboard/validation_sample.py with numpy seed 20261024 (numpy.random.default_rng). Briefings: 15 percent of the 220 confirmed briefings in data/briefings/full_briefings.csv, 33 briefings, drawn at random by briefing and stratified by briefing year in proportion to the year counts; each year's share is rounded down and the remaining places go to the largest remainders, giving 3 (2021), 4 (2022), 6 (2023), 8 (2024), 7 (2025) and 5 (2026). Auto-no items: 15 percent of the 313 items with decided_by "auto_no" in data/review/full_classification.csv, 47 items, drawn with a fresh generator from the same seed. The coding sheets, data/validation/blind_briefing_sheet.csv and data/validation/blind_auto_no_sheet.csv, list the copies' outlets and urls (briefings) or the outlet, url and headline (auto-no items), with blank coding columns; they hold no extracted or hand-coded figure, date, period class or triage decision.

Round 1 coding. The 33-briefing sample was coded with AI assistance, without access to the extraction output (data/validation/round1_ai_coded.xlsx). The author coded 6 of the briefings by hand (data/validation/round1_author_chat_codes.csv). B2025-037 was not coded because its only copy could not be retrieved, which leaves 32 briefings and 96 outcome fields. Disagreements between the coders and data/briefings/briefing_figures_final.csv were adjudicated against the article texts (data/validation/round1_adjudication.csv).

Round 1 result. Against the adjudicated values the final table was correct on 90 of the 96 fields (93.8%), below the 95% target under Validation in docs/audit_rules.md. The AI-assisted coder was correct on 83 of 96 fields and the author on 14 of 18. The main cause was figures for named zones counted as national because the sentence said "theatres of operation", which the national-marker list treats as national (for example "various theatres of operation across the North-West and North-Central zones").

Corrections. data/review/figures_corrections.csv overrides 27 automatic agreed values in 15 briefings, 4 of them in briefings of the validation sample. Of the 27, 23 are figures for named theatres or zones introduced by "theatres of operation" wording, 2 follow a lead that covers the North East and North West only, 1 is a figure for a single operation, and 1 is a garbled lead where the other copies make a national claim without a number; 26 become not reported and 1 vague. src/scoreboard/final_figures.py checks the file (each key is an agreed row in data/briefings/briefing_figures.csv with the same auto_value, corrected_status is reported, vague or not reported, a value is given only when reported, and the reason is non-empty) and applies it after the hand file with source "correction" and the reason as notes. Two rows of data/review/figures_hand_coded.csv were also changed after the sample: B2024-014 neutralised from 121 to 212 and arrested from 253 to 252, since all three wire outlets' headlines and Leadership's "across the country" sentence give 212 and 252, and the theatre arrest figures sum to 252; the wire body is taken as a transposition. The rebuilt data/briefings/briefing_figures_final.csv has 276 automatic, 357 hand and 27 correction rows. The change is logged under Deviations in docs/audit_rules.md.

Commit record. Commit 8ff6cf0 carries the message of the previous commit, 00339d5 ("Parser fixes, extraction v2, briefing figures"), but added data/review/extraction_sheet_v3.csv, together with the version 3 section rule (src/scoreboard/extract.py, src/scoreboard/extraction_sheet.py), independent-copy counting in src/scoreboard/briefing_figures.py and the "rounded" definition in docs/review_guide.md.

## 2026-10-24: validation round 2

Round 2 coding. A fresh 33-briefing sample, drawn with seed 20261025, stratified by year and excluding the round 1 briefings (data/validation/round2_briefing_sheet.csv), was coded by a separate AI agent that saw only the article texts and the coding rules, never the figures table or earlier codes (data/validation/round2_ai_coded.csv). Disagreements between the coder and data/briefings/briefing_figures_final.csv were adjudicated against the article texts (data/validation/round2_adjudication.csv).

Round 2 result. The numeric values in the final table were correct on 96 of the 99 fields (97.0%), meeting the 95% target under Validation in docs/audit_rules.md, against 90 of 96 (93.8%) in round 1. When the distinction between vague and not reported is also counted, the table was correct on 93 of 99 fields (93.9%). The independent coder was correct on 97 of 99 fields.

Follow-up review. 32 automatic agreed values had a copy giving a different figure without naming a region (64 conflicting copies, marked "no region named" in data/review/extraction_sheet_v3.csv), excluding the one such value already corrected in round 1. Each was checked against the article texts and recorded in data/review/conflict_review_round2.csv; 9 were corrected and 23 kept. The 9 corrections are: 5 conflicts between two national values with one independent copy each, recorded as unresolved; 1 named-subset figure ("high profile terrorist leaders") replaced by the national total; 1 sum of arrest categories listed in one sentence with no stated total; 1 named-plus-others value; and 1 change to the majority of independent copies. Round 2 added 2 further corrections in sampled briefings, both unresolved, and changed 5 rows of data/review/figures_hand_coded.csv (B2021-011 arrested, B2025-029 arrested, B2025-044 arrested, B2025-046 neutralised and B2026-026 neutralised). Across the two rounds, data/review/figures_corrections.csv holds 38 corrections and 7 hand-file rows were changed (2 in round 1, 5 in round 2). src/scoreboard/final_figures.py now accepts unresolved as a corrected status, with the value blank, and "thousands" as a vague qualifier in both files. The rebuilt data/briefings/briefing_figures_final.csv has 265 automatic, 357 hand and 38 correction rows. The change is logged under Deviations in docs/audit_rules.md.

Auto-no recheck. The 47 sampled auto_no items (data/validation/blind_auto_no_sheet.csv, seed 20261024, drawn with the round 1 sample) were recoded by a separate AI agent that read the full article texts with only the inclusion rule in docs/review_guide.md and no access to the classification output (data/validation/auto_no_ai_coded.csv). It coded 46 items no and 1 yes, a false-negative rate of 1 of 47 (2.1%) among auto_no items. The yes, V021 (Daily Trust, dated 2024-09-07 in data/review/full_classification.csv), was confirmed against the text: it is a copy of the weekly statement grouped as B2024-038, whose 8 other copies give the same figures. The item is not added, because re-running grouping would change copy counts without changing any value. An earlier attempt to code this sheet from headlines only was not used.

## 2026-10-25: Audit v1.0

Run. The checks in docs/audit_rules.md were run on 2026-10-25 on the frozen v1.0 data (docs/freeze_v1.0.md) by src/scoreboard/audit_v1.py. Results are in outputs/audit_v1.0/: results.csv (every check row with status, evidence_grade and grade_label), one file per check, and week_coverage.csv.

Inputs. data/briefings/check_briefings.csv, built by src/scoreboard/audit_inputs.py from data/briefings/briefing_figures_final.csv, data/briefings/briefing_periods_sheet.csv and data/briefings/value_grades.csv. The periods sheet proposes a period for each of the 220 briefings; the 49 rows marked needs_reading, and B2021-011, B2023-010 and B2024-008, were confirmed against the article texts. Confirmed dates are used where present, otherwise the proposed dates. value_grades.csv grades the 378 reported values by one rule for every source (Deviations, 2026-10-25): the independent copies whose body value under the "national marker" or "no region named" rule equals the final value. The 22 values with no matching copy were reviewed by hand (review_note) and keep their reviewed grade. Under this rule 269 values are grade 2 and 109 grade 3. The first run on 2026-10-25 counted automatic values from national-marker copies only (data/briefings/briefing_figures.csv), which gave 187 grade 2 and 191 grade 3; regrading moved 82 automatic values from grade 3 to grade 2 and none the other way, and the audits and sensitivity runs were rerun.

Choices made during the run, logged under Deviations in docs/audit_rules.md (2026-10-24 and 2026-10-25):
- Weekly, biweekly and other periods of up to 27 days count as parts in the period rule and the coverage variant; stated totals other than a calendar month, quarter or year are compared with the parts inside them (check "b. period_parts").
- Missing weeks in the coverage variant are the weeks whose Thursday no part's period covers.
- Parts overlapping by 1 day or less are summed as adjacent. A row whose parts overlap by more than 1 day is not testable (reason "overlapping parts"), unless a set of non-overlapping parts alone exceeds the total.
- Confirmed periods with basis "unclear" or "cumulative" are never totals or parts; cumulative periods with an end date go through the period-end check.
- In the quarter check, two monthly totals for one month are used only when they agree.
- The implied-residual reference figure is the largest weekly figure of the same calendar year; years with no weekly briefing are not testable for it.
- The within-briefing check is the 2024 pilot result for B2024-037 and B2024-041 (pilot IDs B2024-035 and B2024-038), taken from outputs/tables/pilot_checks_2024.csv.
- The pilot run is reproduced unchanged by the same code with the v1.0 options off.

Counts. 332 check rows (outputs/audit_v1.0/results.csv):

| Check | Consistent | Gap | Gap (parts exceed total) | Shortfall | Minor difference | Implausible residual | Not testable | Rows |
|---|---|---|---|---|---|---|---|---|
| a. within_briefing | 0 | 0 | 1 | 3 | 0 | 0 | 0 | 4 |
| b. quarter_months | 0 | 0 | 0 | 0 | 0 | 0 | 24 | 24 |
| b. month_weeks | 0 | 7 | 0 | 0 | 1 | 0 | 55 | 63 |
| b. period_parts | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 12 |
| b. annual | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 3 |
| b. implied_residual | 28 | 6 | 0 | 0 | 1 | 2 | 41 | 78 |
| b. coverage_variant | 3 | 11 | 0 | 0 | 1 | 0 | 72 | 87 |
| c. period_end | 52 | 9 | 0 | 0 | 0 | 0 | 0 | 61 |
| All | 83 | 33 | 1 | 3 | 3 | 2 | 207 | 332 |

Of the 207 not-testable rows, 22 are not testable because of overlapping parts. By evidence grade, 119 rows are grade 2 and 213 grade 3; no row is grade 1. Against the first run, no row changed status and 41 rows moved from grade 3 to grade 2, among them A195 (B2024-037 neutralised, implied residual).

Review. outputs/audit_v1.0/audit_review_v1.0.csv records the author's review of the key rows against the article texts: A045 (B2024-010 arrested, month_weeks) not upheld; A052 (B2024-023 rescued, month_weeks) upheld with caveat; A195 (B2024-037 neutralised, implied residual) upheld at grade 3; A243 (B2024-057 neutralised, implied residual) upheld on grade 2 figures alone; the 9 period-end gaps (rows A112 to A162 of check c. period_end) upheld. The verdicts and their evidence are those stated in the review file.

Sensitivity runs (src/scoreboard/audit_sensitivity.py, outputs/audit_v1.0/sensitivity/):
- Arrested excluding oil-theft arrests (oil_theft_arrested.csv): B2024-008 arrested set to 160 (264 including 104 oil-theft arrests) and the month_weeks, coverage_variant and implied_residual checks rerun for arrested. Of 80 rows, 2 change status: A045 (B2024-010 month_weeks) from gap to not testable, and A184 (B2024-010 implied residual) from gap to consistent.
- Implied residual with grade 2 figures only (grade2_residual.csv): briefings whose figure for an outcome is grade 3 are left out for that outcome, so their periods count as missing; totals, base and reference figure are grade 2. 50 rows result: 33 consistent, 8 implausible residual, 6 not testable, 3 gap. A195 remains implausible with a ratio of 2.01, as in the main run. A243 is implausible with a ratio of 5.19 (9.64 in the main run): the known parts are the year-to-date total of B2024-053 and the grade 2 weekly figures of B2024-055 and B2024-056, with 1.71 weeks uncovered. Six rows in 2026 (A230, A234, A237, A239, A240, A242) are implausible in this run only; their reference figures rest on the grade 2 weekly figures of 2026, one for neutralised and two for rescued.
