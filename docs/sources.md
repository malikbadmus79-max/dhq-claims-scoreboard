# Sources

Briefing-level sources collected later are recorded in the dataset itself, not in this file.

| ID | Title | Outlet or author | Date | URL |
|----|-------|------------------|------|-----|
| S01 | Press briefing on Armed Forces of Nigeria's military operations | Defence Headquarters | 28 July 2022 | https://defencehq.mil.ng/index.php/2022/07/28/press-briefing-by-directorate-of-defence-media-operations-on-armed-forces-of-nigerias-military-operations-held-at-defence-headquarters-new-conference-room-on-28-july-2022 |
| S02 | DHQ: Troops killed 974 terrorists, rescued 466 hostages in February | TheCable | 29 February 2024 | https://thecable.ng/dhq-troops-killed-974-terrorists-rescued-466-hostages-in-february |
| S03 | 1,166 terrorists killed, 2,742 surrendered across Nigeria: DHQ | Gazette | 29 August 2024 | https://gazettengr.com/1166-terrorists-killed-2742-surrendered-across-nigeria-dhq/ |
| S04 | Nigerian military conducts 7,062 operations, kills 1,487 terrorists | Premium Times | 1 September 2026 | https://www.premiumtimesng.com/news/top-news/906746-nigerian-military-conducts-7062-operations-kills-1487-terrorists.html |
| S05 | Troops killed 1,910 criminals, terrorists in 2021: DHQ | TheWill | 6 January 2022 | https://thewillnews.com/troops-killed-1910-criminals-terrorists-in-2021-dhq |
| S06 | DHQ: Over 8,000 terrorists killed, 11,000 suspects arrested in 2024 | Kola King (Substack) | 6 December 2024 | https://kolaking.substack.com/p/dhq-over-8000-terrorists-killed11000 |
| S07 | Nigerian Army Statements Bely Facts on the Ground in Northeast | Campbell, J. and McCaslin, J., Council on Foreign Relations | 9 July 2020 | https://www.cfr.org/blog/nigerian-army-statements-bely-facts-ground-northeast |
| S08 | Nigeria Security Tracker (May 2011 to July 2023) | Council on Foreign Relations | n.d. | https://www.cfr.org/articles/p29483 |
| S09 | myACLED FAQs (access tiers) | ACLED | n.d. | https://acleddata.com/myacled-faqs |
| S10 | Nigeria Watch | IFRA-Nigeria | n.d. | https://www.nigeriawatch.org/ |
| S11 | WordPress REST API, accessed 18 October 2026: robots.txt allows /wp-json/ and article paths; test search for "Defence Headquarters", March 2024: 39 posts, 3 candidates | Daily Trust | 18 October 2026 | https://dailytrust.com/wp-json/wp/v2/posts |
| S12 | WordPress REST API, accessed 18 October 2026: robots.txt allows /wp-json/ and article paths; test search for "Defence Headquarters", March 2024: 44 posts returned (X-WP-Total header sent as 0), 10 candidates | Daily Post | 18 October 2026 | https://dailypost.ng/wp-json/wp/v2/posts |
| S13 | WordPress REST API, accessed 18 October 2026: robots.txt allows /wp-json/ and article paths; test search for "Defence Headquarters", March 2024: 28 posts, 1 candidate | Channels TV | 18 October 2026 | https://channelstv.com/wp-json/wp/v2/posts |
| S14 | Wayback Machine availability API, accessed 18 October 2026: robots.txt for web.archive.org returns HTTP 404 (no restrictions); the availability query returned a snapshot for a pilot URL | Internet Archive | 18 October 2026 | https://archive.org/wayback/available |

Wayback Machine access setting: requests to archive.org and web.archive.org use a 15-second delay, against 5 seconds for every other domain (config/collection.yaml, domain_delay_seconds). The availability API answered HTTP 429 (too many requests) at the 5-second delay on 18 October 2026. On HTTP 429 the fetcher obeys a Retry-After header, capped at 300 seconds, or waits 60 seconds, and retries once; each 429 is recorded in docs/source_access_log.csv.

## Tried and not used

Outlets probed on 18 October 2026 and not added to the collection (docs/source_access_log.csv):

- vanguardngr.com: WordPress REST API refused with HTTP 403.
- punchng.com: no WordPress REST API (HTTP 403).
- thenationonlineng.net: no WordPress REST API (HTTP 403).
- guardian.ng: the REST API answers a plain request, but search requests are refused with HTTP 403.
- thisdaylive.com: the REST API answers, but the test search returns an empty list.
