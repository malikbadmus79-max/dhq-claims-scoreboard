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
