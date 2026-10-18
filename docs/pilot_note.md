# Pilot note: 2024

Citations in brackets name the table in `outputs/tables/` (or `docs/source_access_log.csv`) and the row, column or check id that holds each number. "Neutralised" is DHQ's term and is used for every figure that copies report as "neutralised", "neutralized", "eliminated" or "killed".

## Scope

The pilot covers DHQ operational briefings published in 2024, collected on 2026-10-16 and 2026-10-17 [source_access_log.csv, date column].

Six outlets supplied candidate items: Blueprint 59, Gazette 54, 21st Century Chronicle 46, TheWill 29, Premium Times 28 and News Agency of Nigeria 14 [pilot_outlets_2024.csv, candidates].

Sources that failed:

- defencehq.mil.ng: robots.txt timed out on 2026-10-16 and again on 2026-10-17, so the site was skipped; the homepage and a 2022 briefing page did not load in a browser on 2026-10-17 [source_access_log.csv, defencehq.mil.ng rows].
- thecable.ng: WordPress REST API refused with HTTP 403 on 2026-10-16 and 2026-10-17 [source_access_log.csv, thecable.ng rows].
- leadership.ng: HTTP 403 on 2026-10-17 [source_access_log.csv, leadership.ng row].
- allafrica.com: HTTP 404, no REST API, on 2026-10-17 [source_access_log.csv, allafrica.com row].
- von.gov.ng: the API answers but holds no 2024 posts; the latest post before 2025 is dated 2023-05-24 and the earliest after 2024-01-01 is dated 2025-01-31 [source_access_log.csv, von.gov.ng rows, 2026-10-17].
- web.archive.org: did not load on 2026-10-17, so no archived URLs were recorded [source_access_log.csv, web.archive.org row].

Article pages also failed for most items at three of the six outlets: 21st Century Chronicle 1 of 48 fetched, Gazette 5 of 54, Premium Times 2 of 28 (JS challenge pages). The WordPress API filled 44 of 47, 49 of 49 and 26 of 26 missing texts respectively [source_access_log.csv, 2026-10-17 wire-copy and API rows]. Of 230 items, 124 have text from the API, 104 from the article page and 2 have none [pilot_item_checks_2024.csv, text_source].

## Corpus

- Candidates: 230 items [pilot_inventory_2024.csv, all rows].
- Briefings: 155 copies were coded as operational briefings and grouped into 50 briefings [pilot_briefings_2024.csv, sum of copies; rows]. The other 75 candidates (230 minus 155) were coded as not operational briefings.
- Briefings by type: 37 weekly, 7 monthly, 3 quarterly, 1 year to date, 1 annual and 1 covering one year [pilot_briefings_2024.csv, period_type].
- Independent copies: of 178 copy pairs compared, 79 are same_wire at the 0.3 threshold [pilot_copy_similarity_2024.csv, header and same_wire]; 76 of 230 items credit the News Agency of Nigeria [pilot_item_checks_2024.csv, nan_credit]. After the wire and NAN merges, 32 briefings rest on two or more independent copies and 18 on one [pilot_briefings_2024.csv, independent_copies]. No copy is DHQ's own text [pilot_briefings_2024.csv, dhq_copies, all 0].
- Coverage gaps: 16 of 53 Monday-to-Sunday weeks have no weekly briefing [pilot_week_coverage_2024.csv, weekly_found]. Eleven of these weeks hold another briefing type; five hold no briefing at all.

| Week | Dates | Briefing found that week |
|---|---|---|
| 2024-W09 | 2024-02-26 to 2024-03-03 | B2024-010 (monthly) |
| 2024-W10 | 2024-03-04 to 2024-03-10 | none |
| 2024-W11 | 2024-03-11 to 2024-03-17 | none |
| 2024-W14 | 2024-04-01 to 2024-04-07 | B2024-013 (quarterly) |
| 2024-W18 | 2024-04-29 to 2024-05-05 | B2024-017 (monthly) |
| 2024-W22 | 2024-05-27 to 2024-06-02 | B2024-021 (monthly) |
| 2024-W26 | 2024-06-24 to 2024-06-30 | B2024-026 (quarterly) |
| 2024-W31 | 2024-07-29 to 2024-08-04 | B2024-031 (monthly) |
| 2024-W35 | 2024-08-26 to 2024-09-01 | B2024-035 (monthly) |
| 2024-W37 | 2024-09-09 to 2024-09-15 | none |
| 2024-W39 | 2024-09-23 to 2024-09-29 | B2024-038 (quarterly) |
| 2024-W45 | 2024-11-04 to 2024-11-10 | B2024-044 (monthly) |
| 2024-W46 | 2024-11-11 to 2024-11-17 | none |
| 2024-W49 | 2024-12-02 to 2024-12-08 | B2024-047 (year to date) |
| 2024-W50 | 2024-12-09 to 2024-12-15 | none |
| 2025-W01 | 2024-12-30 to 2025-01-05 | B2024-050 (annual) |

[pilot_week_coverage_2024.csv, rows with weekly_found False]

## Results by research question

Status by evidence grade across the 103 check rows [pilot_checks_2024.csv, status and evidence_grade]. Arithmetic checks use the effective period end, the earlier of the stated or inferred end and the briefing date; the period_end check uses the stated end.

| Check | Consistent | Gap | Gap (parts exceed total) | Shortfall | Implausible residual | Not testable |
|---|---|---|---|---|---|---|
| a. within_briefing | – | – | 0 / 1 | 0 / 3 | – | – |
| b. quarter_months | 0 / 0 | 0 / 0 | – | – | – | 3 / 6 |
| b. month_weeks | 0 / 0 | 1 / 1 | – | – | – | 1 / 18 |
| b. annual | 0 / 0 | 0 / 0 | – | – | – | 2 / 1 |
| b. implied_residual | 2 / 13 | 1 / 1 | – | – | 1 / 1 | 0 / 5 |
| b. coverage_variant | 0 / 2 | 1 / 6 | – | – | – | 1 / 20 |
| c. period_end | 5 / 2 | 4 / 1 | – | – | – | – |

Cells give grade 2 / grade 3 counts. No row is a minor difference, and no row is grade 1, since no DHQ text was collected. Every row carries the label "development year" [pilot_checks_2024.csv, label].

### RQ1 arithmetic consistency: go with changes

- One arithmetic gap reaches grade 2. In May, the three weekly briefings report 599 rescued against a monthly total of 563 [pilot_checks_2024.csv, C025]. The coverage variant gives the same result [C088].
- Four totals at grade 2 were announced before the period they name had ended: May by 1 day [C042], August by 2 [C045], the third quarter by 4 [C046], and the year-to-date total by 26 days, with bodies stating "January to December" [C048]. The second-quarter total was announced 3 days early, at grade 3 [C043].
- Operation figures do not sum to the national totals.
  - Shortfalls (the national total exceeds the operation sum): B2024-035 neutralised, 1,166 against 629 [C001]; B2024-038 neutralised, 1,937 against 1,838 [C003]; B2024-038 arrested, 2,782 against 2,095 [C004].
  - Parts exceed the total: B2024-035 arrested, 1,179 against 1,096 [C002].
  - No copy of either briefing states that the listed operations are the complete set [pilot_briefings_2024.csv, operations_complete_set_stated, "no" for B2024-035 and B2024-038]. The shortfalls may therefore reflect operations not listed.
  - All four rows are grade 3, because the operation paragraphs appear only in copies that merge into one independent copy [pilot_operations_2024.csv, neutralised_independent_copies_agreeing and arrested_independent_copies_agreeing, all 1].
- The quarter checks cannot be tested: no monthly briefing was found for March, June or September [C005 to C013].
- Under the coverage variant, January matches exactly: 266 neutralised [C074] and 116 rescued [C076]. July does not: the weeklies dated in July exceed the July total for all three outcomes [C092 to C094]. October behaves the same way for neutralised and rescued [C101, C103]. All of these rows are grade 3, so the pilot neither supports nor rules out the coverage reading.
- Changes: a monthly briefing is needed for every month; operation-level extraction is extended to every monthly, quarterly and annual briefing; headline findings are restricted to grades 1 and 2.

### RQ2 plausibility: go with changes

- Of 24 implied-residual rows, 15 are consistent, 2 are implausible residuals, 2 are gaps and 5 are not testable [pilot_checks_2024.csv, b. implied_residual rows].
- The annual neutralised total of 10,937, against 8,394 known, leaves 2,543 for 1.71 missing weeks after the year-to-date briefing [C071]. That is 1,483.4 per missing week, 5.19 times the largest 2024 weekly figure of 286 from B2024-009, at grade 2 [C071].
  - The B2024-047 period now ends at its briefing date, 2024-12-05 (the effective end), not at the inferred 2024-11-30 [pilot_briefings_2024.csv, B2024-047, briefing_date].
  - The effective end shortens the uncovered window, so the implied value per missing week is higher than under the inferred end.
- The August neutralised total implies 575.6 per missing week, 2.01 times the same reference figure, at grade 3 [C065]. Here the effective end is the August briefing date, 2024-08-29 [pilot_briefings_2024.csv, B2024-035].
- Changes: weekly periods are taken from the text wherever it states them, since the residual depends on how weekly periods are drawn.

### RQ3 language: go with changes

RQ3 measures the language of the published record: the copies as outlets published them. Statements about DHQ's own wording require grade 1 text, and the pilot has none.

- Of 149 reported outcome values, none has a qualifier or vague term found in two or more independent copies, so the grade 1–2 wording share is 0.0 [pilot_language_measures_2024.csv, Edward Buba row].
- At grade 3, wording is attached to the neutralised value in 16 briefings, the arrested value in 2 and the rescued value in 2 [pilot_language_2024.csv, neutralised_wording_grade, arrested_wording_grade, rescued_wording_grade].
- Own losses appear in 2 briefings, B2024-011 and B2024-024, each in one independent copy (grade 3); the grade 1–2 share is 0.0 [pilot_language_2024.csv, own_losses_grade; pilot_language_measures_2024.csv].
- Dictionary terms found in two or more independent copies appear in 30 of 50 briefings, mostly terms describing recoveries [pilot_language_2024.csv, vague_terms_grade2].
- All 50 briefings name the same spokesperson, Edward Buba, so the spokesperson split cannot be tested in 2024 [pilot_language_2024.csv, spokesperson].
- Period wording does not match the announcement date in B2024-047 [pilot_checks_2024.csv, C048].
- With no DHQ text, the choice of verb in a copy cannot be attributed to DHQ.
- Changes: statements about DHQ's wording wait for grade 1 text. Until then, the measures describe the published record and need wording repeated across independent copies. The pilot shows that wording sits in single wire copies, which collapse to one independent copy.

### RQ4 media relay: go

- In 7 of 50 briefings, copies disagree on at least one outcome: B2024-004, B2024-013, B2024-021, B2024-032, B2024-034, B2024-048 and B2024-049 [pilot_briefings_2024.csv, conflict columns]. These give 17 copy-conflict rows [pilot_relay_2024.csv, relay_type "copy conflict"].
  - Copies disagree materially, by more than 1% of the larger value, in 5 of 50 briefings: B2024-004, B2024-021, B2024-032, B2024-034 and B2024-048 [pilot_briefings_2024.csv, neutralised_conflict_material and arrested_conflict_material]. Headline findings use these 5.
  - 7 rows are minor differences [pilot_relay_2024.csv, label "minor difference"]. Three are copies of B2024-013 reporting 2,352 against a majority of 2,351. Four are copies of B2024-049 in a tie between 256 and 258.
  - 10 rows differ, in 5 briefings: B2024-004, B2024-021, B2024-032, B2024-034 and B2024-048. One copy is lower than the majority value, and 9 are in briefings where the value is a tie [pilot_relay_2024.csv, label "differs", direction].
- Five values are left blank by a tie between independent copies: neutralised in B2024-021, and arrested in B2024-004, B2024-034, B2024-048 and B2024-049 [pilot_briefings_2024.csv, tie columns].
- Headline-body differences: the review sheet codes 8 copies as differing, and all 8 are in the relay table as 12 figure rows [pilot_relay_2024.csv, review_coded "yes"].
  - The 8 copies are Gazette and Blueprint for B2024-012, Gazette and Premium Times for B2024-013, Blueprint for B2024-019, Gazette for B2024-021, TheWill for B2024-031 and Blueprint for B2024-044.
  - 11 of the 12 rows differ, and 1 is rounded: TheWill's "over 500" neutralised for a body figure of 572 in B2024-031 [pilot_relay_2024.csv, review_coded "yes", label]. Every coded copy keeps at least one differing row.
  - Against the majority value, the 11 differing headline figures are 5 lower, 3 higher, 2 equal and 1 with no majority [pilot_relay_2024.csv, review_coded "yes", label "differs", direction]. The 2 equal rows are B2024-013 copies whose headline gives the majority 2,351 while their body gives 2,352.
  - In 10 of the 11 differing rows the headline figure is absent from the body. In B2024-044 (rescued 481), the figure appears in the body only as a different outcome [pilot_relay_2024.csv, detected_by].
- The absent-figure rule also finds 8 copies that the review sheet does not code [pilot_relay_2024.csv, review_coded "no"]. 7 of these are rounded headline figures carrying "over" or "nearly". One differs: TheWill's "over 150" neutralised for 171 in B2024-034, lower than the majority value.
- In total, 9 copies carry a headline figure that differs from the body after the rounding rule [pilot_relay_2024.csv, relay_type "headline-body difference", label "differs"].
- 18 of 50 briefings rest on a single independent copy [pilot_briefings_2024.csv, independent_copies].

### RQ5 context comparison: parked

No comparison source was accessed in the pilot.

## Limitations

- No DHQ text was collected, so no result reaches grade 1, and DHQ's own figures and wording cannot be separated from relay [source_access_log.csv, defencehq.mil.ng rows].
- Four configured outlets supplied nothing [pilot_outlets_2024.csv, candidates for Voice of Nigeria, TheCable, Leadership and AllAfrica].
- No archived URLs were recorded [source_access_log.csv, web.archive.org row].
- Weekly periods are inferred as 7 days ending on the briefing date [pilot_briefings_2024.csv, period_flag]. The B2024-047 period end is also inferred [pilot_briefings_2024.csv, B2024-047].
- Weeks with no weekly briefing found may be weeks DHQ did not brief, or collection gaps; the pilot cannot tell the two apart [pilot_week_coverage_2024.csv].
- The extraction rule and the same_wire threshold were both set on 2024 data, the same data the checks ran on. All 2024 results are therefore labelled "development year" [pilot_checks_2024.csv, label].
- First-pass coding of briefing grouping and type was done with Claude assistance, checked against the stored article text, by one human coder. No validation sample has been coded yet.
- Operation-level figures were extracted for two briefings only [pilot_operations_2024.csv].

## What changes for the full collection

- The rules in `docs/audit_rules.md` are frozen and committed before collection starts.
- defencehq.mil.ng and web.archive.org are retried at the start of each collection run. While robots.txt is unreachable, the DHQ site stays skipped.
- A hand-saved sample of DHQ's official social media posts for the pilot months is kept as a possible grade 1 source for language. The posts are saved manually, not scraped.
- Each year gets a week coverage table. Weeks with no briefing found are searched again in the outlets already in use before any audit runs.
- Operation-level extraction covers every monthly, quarterly and annual briefing.
- The language and relay tables are built for every year. A 2024 headline finding is reported only if it recurs in another year, or with the "development year" label.
- A hand-coded validation sample is coded blind and scored against the target in `docs/audit_rules.md` before any audit runs.
- Implied residuals and the coverage variant are reported alongside the period-rule checks, each with its evidence grade.
