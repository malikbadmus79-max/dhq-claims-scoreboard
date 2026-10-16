# Project rules

- Neutral researcher voice in every file. No "we/our/you", no placeholders, no bold lead-in bullets, no rhetorical or promotional phrasing.
- Every number in any output must trace to a table in outputs/tables or a source in docs/sources.md.
- Raw article text and HTML stay in data_raw/ and are never committed. Published data holds only structured values, source URL, archived URL and at most one evidence sentence per value.
- "Neutralised" is DHQ's term. Never write "killed" unless DHQ's own text says killed.
- A figure counts as a DHQ inconsistency only if it appears in DHQ's own text or in at least two independent copies of the same briefing. Single-copy differences are media-relay differences.
- Web collection obeys robots.txt and the configured delay, and identifies itself with the configured user agent.
- The audits run only on a frozen, versioned dataset, using audit rules committed before they run.
- Work one step at a time; never commit or push.
