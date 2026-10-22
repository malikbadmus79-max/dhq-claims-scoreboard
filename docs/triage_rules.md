# Triage rules for is_operational_briefing

Rules that decide is_operational_briefing ("yes" or "no", as defined in docs/review_guide.md) from an item's title and body text, so that hand review can concentrate on the items no rule decides. Code: src/scoreboard/triage.py. Evaluation table: outputs/tables/triage_pilot_evaluation.csv.

## Acceptance rule

A rule is accepted only if, on the 230 hand-labelled pilot items (data/review/pilot_review_2024.csv), it fires on at least 20 items with precision of at least 98%. Only accepted rules decide items. An item is decided when every accepted rule that fires on it gives the same decision; an item on which no accepted rule fires, or on which accepted rules disagree, is left for hand review. Pilot item IDs (P2024-r001 to P2024-r230) are row numbers in the pilot review sheet.

## Features

- Outcome number: an outcome verb (neutralised, killed, eliminated, arrested, apprehended, rescued, surrendered, recovered) next to a number, in either order.
- DHQ attribution: DHQ, Defence Headquarters, Defence Media Operations or Buba (not "Buba Marwa").
- Title period: "in one week", "last week", "in" a month name, "in" a year, "month", "weekly".
- Body period: "in the last one week", "over the past two weeks", "between January 4 and 10" and similar.
- National marker: "across the country", "theatre(s) of operation(s)", "across the nation", "nationwide".
- Briefing phrase: "while briefing", "bi-weekly", "Director, Defence Media Operations".

## Rules and pilot results

| Rule | Decision | Fires | Precision | Accepted |
|---|---|---|---|---|
| title_period_number: title states a period and an outcome number; text attributed to DHQ | yes | 57 | 1.000 | yes |
| title_number_body_period: outcome number in the title, a period stated in the body, DHQ named | yes | 52 | 1.000 | yes |
| title_number_national: outcome number in the title, a national marker, DHQ named | yes | 77 | 0.974 | no |
| national_results: DHQ named, a national marker and an outcome number anywhere | yes | 157 | 0.898 | no |
| briefing_format: briefing-format phrase and an outcome number anywhere | yes | 166 | 0.831 | no |
| dhq_outcome_number: DHQ named and an outcome number anywhere | yes | 189 | 0.815 | no |
| no_number_no_period: no outcome number and no stated period in title or body | no | 36 | 1.000 | yes |
| no_national_no_period: no national marker, no stated period and no briefing phrase | no | 22 | 1.000 | yes |
| no_outcome_number: no outcome verb next to a number in title or body | no | 41 | 0.976 | no |
| non_briefing_title: title is a denial, warning, vow, court, inquiry, wanted list or opinion | no | 25 | 0.880 | no |
| other_agency_source: police or another agency named and DHQ not named | no | 0 | – | no |

With the four accepted rules, the pilot splits into 66 items decided yes, 42 decided no and 122 left for hand review, with no item decided against its label. Coverage on the pilot is therefore 108 of 230 items (47%).

The rejected rules show where body text alone misleads: single-incident statements, denials and policy statements attributed to DHQ also name DHQ, use national phrases and give outcome numbers, so rules built on those features alone fall below 98%. other_agency_source never fires on the pilot because every pilot item came from searches for DHQ terms.

## Limitation

The rules were set on the same 230 pilot items they are evaluated on, so their pilot precision overstates what can be expected on other years. Their error rate on 2021–2026 is checked by the blind validation sample. The accepted rules and the auto-no guard have been applied to every full-collection item without a pilot label (outputs/tables/full_triage_<year>.csv); the decisions there are triage decisions, not hand codes.

## Triage check

Sample. 30 items decided yes and 30 decided no by the four accepted rules, drawn from the full-collection triage of 2021–2023 and 2025–2026 (outputs/tables/full_triage_<year>.csv), excluding 2024, with the fixed seed 20261022 (src/scoreboard/triage_check.py). By year, auto-yes/auto-no: 2021 2/5, 2022 4/7, 2023 15/7, 2025 4/4, 2026 5/7 (data/review/triage_check_key.csv).

Coding. Claude, an AI assistant, coded each item from the article text without seeing the key or the triage tables, following docs/triage_check.md. Hand codes and notes: data/review/triage_check_coded.csv.

Pass rule. The pass rule (at most 1 disagreement in each group of 30) was set in the planning notes on 2026-10-22 before the sample was drawn, and recorded in this file only after scoring. "Unsure" codes are reported separately and are not counted as errors.

Results (outputs/tables/triage_check_result.csv):

| Group | Items | Agreements | Disagreements | Unsure | Outcome |
|---|---|---|---|---|---|
| auto-yes | 30 | 30 | 0 | 0 | pass |
| auto-no | 30 | 28 | 2 | 0 | fail |

Disagreements, both in the auto-no group and both coded yes by hand:

- TC-010 (2022), decided no by no_number_no_period. The article reports a DHQ bi-weekly update covering 6 to 20 October 2022 but leads with a single arrest, so neither the title nor the body text read by the rule carries an outcome number with a stated period.
- TC-029 (2023), decided no by no_national_no_period. The article reports a DHQ update on Operation Hadarin Daji results "within the last three weeks", a regional section of a periodic update; the rule found no national marker, no period phrase it recognises and no briefing phrase.

Outcome. The auto-yes decisions pass. The auto-no decisions fail; the rules responsible are no_number_no_period (TC-010) and no_national_no_period (TC-029). Each fired alone on its disagreement item.

## Guard for auto-no

The guard was added because both disagreements in the triage check were DHQ periodic updates decided "no": TC-010 leads with a single arrest from a bi-weekly update, and TC-029 reports a regional section of a periodic update. The accepted rules are unchanged. The guard runs after them: an item decided "no" is left for hand review when its title or body names "Defence Media Operations", "Defence Headquarters" or "DHQ" and contains a briefing or period phrase ("briefing", "biweekly", "bi-weekly", "weekly", "update", "news conference", "press conference", "within the last", "in the last", "past two weeks", or "between" two dates). It never turns an item into "yes". Code: guard() in src/scoreboard/triage.py.

Applied to the full collection, the guard moves auto-no items to hand review (column guard = "moved" in outputs/tables/full_triage_<year>.csv), including TC-010 and TC-029. Of the 30 auto-no items in the first check, it moves 5 (TC-010, TC-029, TC-035, TC-042, TC-060); the other three were coded no by hand.

The guard was written after the first check was scored, so that check cannot test it. It is tested on a fresh sample of 30 auto-no items decided after the guard, drawn from 2021–2023 and 2025–2026 with seed 20261023, excluding the 60 items of the first check (data/review/triage_check2_sheet.csv, key data/review/triage_check2_key.csv, IDs TC2-001 to TC2-030). Pass rule, set before that sample was drawn: at most 1 disagreement in 30.

### Second triage check

Sample. 30 auto-no items after the guard (2021 5, 2022 5, 2023 5, 2025 6, 2026 9), seed 20261023, IDs TC2-001 to TC2-030 (data/review/triage_check2_key.csv).

Coding. Claude, an AI assistant, coded each item from the article text without seeing the key, following docs/triage_check.md. Hand codes and notes: data/review/triage_check2_coded.csv.

Result (outputs/tables/triage_check_result.csv, group "auto-no after guard"): 30 items, 30 agreements, 0 disagreements, 0 unsure.

Outcome. The auto-no decisions after the guard pass.

Limitation. The second sample held only auto-no items, and the coder knew this from the documentation, so the check is a weaker test than the first, mixed check: a coder who knows every item was decided "no" is not blind to the decision. The blind validation by the author will include auto-no items to cover this.
