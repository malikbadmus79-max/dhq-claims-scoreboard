# Audit rules

These rules govern the full collection, 2021 to 2026. They are committed before that collection starts and are applied, unchanged, to the frozen, versioned dataset. Any later change is logged under Deviations at the end of this file. The implementation is in `src/scoreboard/extract.py` and `src/scoreboard/checks.py`.

## Evidence grades

| Grade | Basis |
|---|---|
| 1 | DHQ's own text: a copy published by Defence Headquarters that carries the figure. |
| 2 | Two or more independent copies agree on the figure. Copies linked by same_wire (word 5-gram Jaccard similarity of 0.3 or more, digits removed) count as one, and so do copies crediting the News Agency of Nigeria (the NAN merge). |
| 3 | One independent copy, or several copies of the same wire only. |

- A check row takes the grade of its weakest figure. A row with no figures is grade 3.
- Headline findings use grades 1 and 2 only.
- Grade 3 results are reported separately and labelled "grade 3, media-relay level".
- A difference counts as a DHQ inconsistency only at grade 1 or 2.

## Development year

- 2024 is the development year: the extraction rules and the same_wire threshold of 0.3 were set on 2024 data.
- Every 2024 result carries the label "development year".
- A headline finding must either recur in a year other than 2024 or carry that label.

## Checks

- Effective period end: every arithmetic check uses the earlier of the stated end (the inferred end where none is stated) and the briefing date. A total announced before its period ended is thus compared only with the days up to the announcement.
- Within briefing: the sum of operation figures is compared with the national total stated in the same briefing. The row records whether any copy states that the listed operations make up the national figures (complete_set_stated). The status gives the direction of the difference (see Status labels).
- Period rule: a total is compared with shorter briefings only when the stated or inferred periods of those briefings lie wholly inside the total's period. This rule covers quarter against months, month against weeks, and annual against the year-to-date total plus the later weeklies.
- Coverage-based variant: a monthly or quarterly total is compared with the sum of the weekly briefings dated within its period. Briefing dates decide membership, whatever the inferred weekly periods. The variant is reported next to the period rule and never replaces it.
- Missing weeks in the coverage variant: a missing week is a Monday-to-Sunday week whose Thursday falls inside the period and that holds no weekly briefing in the sum.
- Period end: a total is flagged when the stated end of the period it names falls after the briefing date. This check uses the stated end, not the effective end.
- Implied residual (RQ2) applies when a total exceeds the sum of its known shorter briefings and weeks are missing under the period rule:
  - missing weeks = (days of the period not covered by the known briefings' periods) ÷ 7;
  - implied value per missing week = (total − known sum) ÷ missing weeks;
  - the implied value is flagged as an implausible residual when it exceeds the largest weekly figure DHQ reported for the same outcome in the same calendar year (the largest majority value among weekly briefings dated in that year);
  - the ratio of the implied value to that largest figure is reported, together with the briefing that holds the largest figure.

## Status labels

Every row carries one status and one evidence grade.

| Status | Meaning |
|---|---|
| consistent | Both sides are complete and equal; or the period had ended by the briefing date; or the implied residual does not exceed the largest weekly figure. |
| minor difference | The two sides differ by 1% or less of the larger side. Reported, but excluded from headline findings. |
| gap | Both sides are complete and differ by more than 1% of the larger side; or, with parts missing, the parts present already exceed the total by more than that; or the total was announced before the end of the period it names. |
| gap (parts exceed total) | Within briefing only: the sum of operation figures exceeds the national total by more than 1% of the larger side. |
| shortfall (listed operations may be incomplete) | Within briefing only: the national total exceeds the sum of operation figures by more than 1% of the larger side. Unless the text states that the listed operations are the complete set, a shortfall is not reported as an inconsistency. |
| implausible residual | The implied value per missing week exceeds the largest weekly figure of the same calendar year. |
| not testable | A side has no value; or parts are missing and the parts present do not exceed the total. |

## Extraction rules

- Outcomes and the copy terms matched to them: neutralised ("neutralised", "neutralized", "eliminated", "killed"; recorded under DHQ's term "neutralised"), arrested ("arrested", "apprehended", "nabbed") and rescued ("rescued").
- Sentence choice: the first sentence with a national marker; failing that, the first sentence naming no region, state or operation; failing that, a vague-only sentence.
- National markers: "across the country", "nationwide" and plural "theatres of operation(s)". Singular "theatre of operation" names a region.
- Qualifiers: no fewer than, not fewer than, not less than, at least, more than, over, about, approximately, nearly and almost are kept in a qualifier column next to the value.
- Vague terms in place of a count: "several", "scores", "dozens", "many" and "a large number" next to an outcome word are recorded as a qualifier with no value.
- Named subsets: a figure attached to leaders, commanders, kingpins or "notable" is skipped, and a total that follows it in the same list is used.
- Named individuals plus others: "a commander, [name], and 182 others" gives value 182 with qualifier "plus 1 named".
- Number ownership: a number directly after an outcome verb belongs to that verb, and a number followed by the next outcome verb belongs to the next verb.
- Excluded numbers: a number followed by a unit (days, litres, rounds, weapons, naira and similar) is skipped. So is a neutralised number followed by soldiers, troops, personnel or civilians.
- Section-only copies: a copy that opens on a region or operation and never states a national figure gives no national total.
- Spelled-out numbers: numbers containing hundred, thousand or million are read as digits. Small counts such as "one week" stay as words.
- Operation sections: an operation's section runs from the sentence naming it until another operation or region is named.
- Majority value: the value with the most independent copies, where copies without a value do not vote. A conflict flag marks a briefing whose copies report more than one distinct value.
- Ties: when values tie on independent copies, the value is left blank and flagged, and checks that depend on it are not testable.
- Periods: the briefing date is the earliest publication date among the copies. A named month, quarter or year is a stated period. A weekly period is inferred as 7 days ending on the briefing date unless the text states it.
- Evidence: one sentence per value, truncated to 300 characters, kept in `data_raw/extract/` only.

## RQ3 language rules

- Scope: RQ3 measures the language of the published record, that is, the copies as outlets published them. A statement about DHQ's own wording requires grade 1 text; wording found only in outlet copies is reported as the wording of the published record.
- Vague-term dictionary: several, scores, dozens, many, a large number, a cache of, among others, assorted, significant results.
- Qualifiers: the qualifiers listed under Extraction rules.
- Wording of a value: the qualifier or vague term attached to an outcome value in a copy. "plus N named" is an extraction note, not wording.
- Own losses: any copy sentence reporting soldiers or security personnel killed, wounded or missing. Sentences in which troops are the actors ("troops killed 43 terrorists") do not count, and neither do site links such as "READ ALSO".
- Spokesperson: the person named as Director of Defence Media Operations or DHQ spokesperson. A surname is resolved to the most frequent near-identical spelling in the briefing's copies.
- Measures, by year and spokesperson:
  - the share of reported outcome values whose wording is found in two or more independent copies (grade 2) or in DHQ's own text (grade 1);
  - the share of briefings whose own-losses sentence is found at grade 1 or 2.
  - Wording found in a single independent copy is grade 3 and is reported separately.
- Tables: `outputs/tables/pilot_language_<year>.csv` (one row per briefing) and `pilot_language_measures_<year>.csv` (the measures). Own-loss evidence sentences stay in `data_raw/extract/`.

## RQ4 relay rules

- Conflict flags in the briefing table: `<outcome>_conflict` is the raw flag, true whenever copies report more than one distinct value. `<outcome>_conflict_material` is true only when a conflicting value differs from the majority value by more than 1% of the larger of the two; when the majority is a tie, it is true when any two reported values differ by more than that. Headline findings use `<outcome>_conflict_material`.
- Copy conflict: independent copies report different values for the same outcome. A row is recorded for each copy whose body value differs from the majority value, or for each copy with a value when the majority is a tie.
- Headline-body difference: a headline figure absent from the same copy's body. For copies the review sheet codes as differing, the comparison also covers a headline figure that differs from the copy's own body value for that outcome; the detected_by column records which comparison found each row.
- Recorded for both: the outlet, the copy value, the majority value, and the direction (higher, lower, equal, or no majority when the majority is a tie or blank).
- Majority value: the value with the most independent copies. Copies joined by same_wire or by the NAN merge form one group and cast one vote between them.
- Rounded headline: a headline-body row is labelled "rounded" instead of "differs" when both of these hold:
  - the headline figure carries "over", "more than", "about", "nearly" or "almost";
  - the copy's own body figure for the same outcome (the majority value when the copy has none) is equal to it, or within the rounding unit implied by its trailing zeros.
- Rounding unit: 10 to the power of the headline figure's trailing zeros (40 gives 10, 2,300 gives 100, 1,000 gives 1,000). A figure with no trailing zero has no rounding unit and rounds only an equal body figure.
- The unit is applied as written, with no cap: "over 1,000" has a unit of 1,000 and accepts any body figure from 1,000 to 1,999.
  - "Over" and "more than" accept a body figure above the headline figure and below it plus one unit: "over 40" for 43, "over 2,300" for 2,351, "over 1,000" for 1,0xx.
  - "Nearly" and "almost" accept a body figure below the headline figure and above it minus one unit: "nearly 7,000" for 6,998.
  - "About" accepts a body figure within half a unit either side.
- Minor difference: a copy-conflict row is labelled "minor difference" instead of "differs" when the copy value is within 1% of the larger of it and the majority value. When the majority is a tie, the copy value must be within 1% of every other value reported.
- Rows labelled "rounded" or "minor difference" are reported but excluded from headline relay findings.
- Table: `outputs/tables/pilot_relay_<year>.csv`, built from the review sheet and the extraction. It holds structured values, outlets and URLs, never body text.
- Relay differences are media-relay observations, never DHQ inconsistencies.

## Validation

- Target: 95% accuracy on numeric fields in a 15% hand-coded sample of briefings.
- Sample: drawn at random by briefing.
- Blind coding: the author codes the sample without seeing the extraction output, before any audit runs.
- Numeric fields: the neutralised, arrested and rescued values, and the period start and end dates.
- Below target: the extraction rule is revised, the change is logged under Deviations, and a fresh sample is drawn and coded.

## Freeze

These rules are committed before the full collection begins. The audits run only on a frozen, versioned dataset, under the rules as committed. Any later change is logged below with its date and reason.

## Deviations

- 2026-10-24: hand-extracted figures replace the automatic values for the 357 briefing-outcome rows whose automatic status in data/briefings/briefing_figures.csv is conflict, majority or needs hand extraction (data/review/figures_hand_coded.csv). For these rows the national-scope test was applied by hand where the national-marker list under Extraction rules missed national wording: "theaters", "various parts of the country", "across the seven theatres", spelled-out numbers, and noun forms such as "the arrest of 121". Rows with automatic status agreed keep the automatic values. Conventions: docs/review_guide.md, "Hand extraction of briefing figures, 2026-10-24".
- 2026-10-24: validation round 1 fell below the 95% target: data/briefings/briefing_figures_final.csv was correct on 90 of 96 numeric outcome fields (93.8%) in the 32 coded briefings of the 33-briefing sample (data/validation/round1_adjudication.csv). The sample was coded with AI assistance, with 6 briefings also coded by the author, rather than by the author alone as stated under Validation. Corrections were applied: 27 automatic agreed values are overridden by data/review/figures_corrections.csv and two values in data/review/figures_hand_coded.csv were changed. The national-marker rule under Extraction rules does not apply when the same sentence names regions, zones or operations; "theatres of operation" followed or preceded by named zones is not national. Round 2 is a fresh 15% sample of 33 briefings drawn with seed 20261025, stratified by year and excluding the round 1 briefings (data/validation/round2_briefing_sheet.csv).
- 2026-10-24: validation round 2 met the 95% target on numeric fields: data/briefings/briefing_figures_final.csv was correct on 96 of 99 numeric outcome fields (97.0%) in the 33-briefing sample (data/validation/round2_adjudication.csv). A value with two national figures of equal independent support is recorded as unresolved, with the value blank, in data/review/figures_corrections.csv as in data/review/figures_hand_coded.csv. "thousands" is added to the vague terms used in both files (docs/review_guide.md).
- 2026-10-24: inputs for the v1.0 audits (src/scoreboard/audit_inputs.py), decided before any audit runs on the frozen data:
  - Biweekly period: a date range stated in the text overrides; otherwise 14 days ending on the briefing date, as a weekly period is 7 days ending on the briefing date. Proposals read stated ranges from the first 1,500 characters of each copy's body and are confirmed by hand in data/briefings/briefing_periods_sheet.csv.
  - Biweekly briefings count as parts in the period rule and the coverage variant. Missing weeks in the coverage variant are the Monday-to-Sunday weeks inside the total's period that no part's period covers.
  - The implied-residual check needs a weekly reference figure; years with no weekly briefing (2021, 2022) are not testable for it.
  - Evidence grades for hand and correction values count the independent copies (same_wire and the NAN merge, as in src/scoreboard/briefing_figures.py) whose body value under the "national marker" or "no region named" rule equals the final value. Automatic values keep independent_copies_with_value from data/briefings/briefing_figures.csv. Values with no matching copy are listed for hand review (data/briefings/value_grades.csv, needs_review).
  - The within-briefing check is limited to the 2024 pilot briefings with operation figures, B2024-035 and B2024-038; extending it is out of scope for v1.0.
  - Grade 1 is not available: no DHQ-published copy is in the data.
- 2026-10-25: overlapping parts in the v1.0 audits (src/scoreboard/checks.py, overlap_days; src/scoreboard/audit_v1.py), decided before the checks ran:
  - Parts whose periods overlap by 1 day or less are treated as adjacent (a shared boundary day in stated ranges) and summed normally.
  - Where a check would sum parts that overlap by more than 1 day, the row is "not testable" with the reason "overlapping parts" and the overlapping briefing IDs listed. The test "parts present already exceed the total" still applies, but only when a set of non-overlapping parts alone exceeds the total.
  - Confirmed periods with basis "unclear" or "cumulative" are never totals or parts; cumulative periods with an end date still go through the period-end check. Totals and parts are typed by their dates: a calendar month, quarter or year by name or dates; parts are periods of up to 27 days; other stated totals are compared with the parts inside them (check "b. period_parts").
  - In the quarter check, two monthly totals for the same month are used only when they agree; otherwise the month is not used.
- 2026-10-25: one grading rule for all values. The evidence grade of every reported value in data/briefings/value_grades.csv, whatever its source (automatic, hand or correction), counts the independent copies (same_wire and the NAN merge, as in src/scoreboard/briefing_figures.py) whose body value under the "national marker" or "no region named" rule equals the final value. This replaces the 2026-10-24 rule under which automatic values kept independent_copies_with_value from data/briefings/briefing_figures.csv, which counts national-marker copies only. Rows reviewed by hand (review_note filled) are kept as reviewed. The audits and sensitivity runs were rerun on the regraded values.
- 2026-10-25 (v1.1): a "DHQ statement, archived copy" (docs/sources.md) counts as DHQ's own text for grade 1. defencehq.mil.ng did not answer (docs/source_access_log.csv), so DHQ statements are read from the earliest Wayback Machine capture of each post. A briefing compared with such a statement (data/dhq_site/dhq_comparison_v1.1.csv, verdict other than "no match") counts one DHQ copy; a value agreeing with the statement is grade 1. Four values found to disagree with DHQ's text are corrected in data/review/figures_corrections_v1.1.csv and applied in data/briefings/briefing_figures_final_v1.1.csv; the v1.0 tables are unchanged. Reported single-copy national values dated before 2023-07-01 are listed in data/review/pre2023_single_copy_flags.csv and excluded in a sensitivity run (outputs/audit_v1.1/sensitivity/).
