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
