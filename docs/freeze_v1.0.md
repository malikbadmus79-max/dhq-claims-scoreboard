# Data freeze v1.0

- Date: 2026-10-24
- Commit: aa4d69e

The audits run on the files below, frozen at version 1.0. The frozen data files are as committed in aa4d69e. Row counts exclude the header. Checksums are SHA-256 of each file with LF line endings, as stored in git (.gitattributes sets eol=lf); they equal `git show <commit>:<path> | sha256sum`. A working copy written on Windows may carry CRLF endings and must be converted to LF before comparison. tests/test_freeze.py recomputes the checksums and fails if a frozen file changes.

| File | Rows | SHA-256 |
|---|---|---|
| data/review/full_classification.csv | 1741 | 81bcd49e8307696d6c396a7a0f8ac5ff6d23341cc604a2998c91e036ca885dcd |
| data/briefings/full_briefings.csv | 220 | 20883da87e4dff52d97f6464860117d8759458a327d41a5c2e5fa3166d92f97a |
| data/briefings/briefing_figures.csv | 660 | 9d7a041d1f72a8dc163febb0954c8978281e0e5221c4e7172d6e695ab349d8ca |
| data/review/figures_hand_coded.csv | 357 | c41464cb64fac273fd4631be3174184fb7baa2d927e7c26cd27d3259fc850a96 |
| data/review/figures_corrections.csv | 38 | 265e891d559e10f4ca0134235372b0ec283a4cb0e2b42c78e3bedf0a632fef3d |
| data/briefings/briefing_figures_final.csv | 660 | 2025fd6154c91d705f702161b31abab419cc165a8083575869172df322ee5213 |

## Validation

In validation round 2, data/briefings/briefing_figures_final.csv was correct on 96 of 99 numeric fields (97.0%), meeting the 95% target under Validation in docs/audit_rules.md (data/validation/round2_adjudication.csv). Rounds 1 and 2 are described in docs/methods_changes.md.

## Changes after the freeze

Any later change to these files is logged under Deviations in docs/audit_rules.md, with its date and reason. Column definitions are in docs/data_dictionary.md.
