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

The rules were set on the same 230 pilot items they are evaluated on, so their pilot precision overstates what can be expected on other years. Their error rate on 2021–2026 is checked by the blind validation sample. The rules have not been applied to the full collection.
